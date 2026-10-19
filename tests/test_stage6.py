from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
import unittest
import json

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.comparison import company_budget_comparison, sales_budget_comparison, trend_comparison, year_to_date
from analysis.service import analysis_pack
from etl.common import ZERO, encode, read_json
from etl.sources import CONTRACT, Facts, load_facts


def clone(facts):
    return Facts({name: frame.copy(deep=True) for name, frame in facts.tables.items()}, deepcopy(facts.metadata))


def empty_facts(start="2026-01-01", end="2026-09-30"):
    return Facts({name: pd.DataFrame(columns=columns) for name, columns in CONTRACT.items()}, {"entity_id": "EDGE", "rule_version": "sales_v1", "coverage": {"complete_start": start, "complete_end": end}, "data_availability": {name: True for name in CONTRACT}})


class FinancialRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = load_facts(ROOT / "configs/sample_files.json")

    def test_company_matches_sql_and_manual_baseline(self):
        result = FinancialEngine(self.sample).summary("2026-09")
        expected = read_json(ROOT / "tests/fixtures/sample_sql_reference.json")["company"]
        for field, value in expected.items():
            self.assertEqual(result[field], value, field)
        self.assertEqual((result["confirmed_lines"], result["sales_quantity"]), (9, 40))
        self.assertEqual(result["gross_margin_rate"], Decimal(1185)/3240)
        self.assertEqual(result["average_selling_price"], Decimal("103.75"))
        self.assertEqual(result["average_order_value"], Decimal("518.75"))

    def test_dimensions_reconcile_and_use_weighted_rate(self):
        engine = FinancialEngine(self.sample)
        for field in ("product_id", "channel_id", "region_id"):
            detail = engine.dimensions("2026-09", by=field)
            self.assertEqual(sum(detail["net_revenue"], ZERO), Decimal("3240"))
            self.assertEqual(sum(detail["net_cost"], ZERO), Decimal("2055"))
            self.assertEqual(sum(detail["gross_margin"], ZERO), Decimal("1185"))
            self.assertTrue(detail["operating_profit"].isna().all())
        product = engine.dimensions("2026-09")
        self.assertNotEqual(sum(product["gross_margin_rate"], ZERO)/len(product), engine.summary("2026-09")["gross_margin_rate"])
        self.assertEqual(sum(product["confirmed_orders"]), 9)
        self.assertEqual(engine.summary("2026-09")["confirmed_orders"], 8)

    def test_dimension_filter_retains_separate_company_profit(self):
        result = analysis_pack(FinancialEngine(self.sample), "2026-09", Filters(products="P001", channels="C02", regions="R02"))
        selected = result["selected_scope"]
        self.assertEqual((selected["net_revenue"], selected["net_cost"], selected["gross_margin"]), (Decimal("550"), Decimal("350"), Decimal("200")))
        self.assertIsNone(selected["expenses"])
        self.assertIsNone(selected["operating_profit"])
        self.assertEqual((result["company_scope"]["expenses"], result["company_scope"]["operating_profit"]), (Decimal("400"), Decimal("785")))
        self.assertEqual(result["company_budget"]["operating_profit"]["variance"], Decimal("-115"))

    def test_known_empty_combination_zero_not_unknown(self):
        result = FinancialEngine(self.sample).summary("2026-09", filters=Filters(products="P002", channels="C01"))
        self.assertTrue(result["is_complete"])
        self.assertEqual(result["net_revenue"], ZERO)
        self.assertIsNone(result["gross_margin_rate"])

    def test_calendar_empty_month_and_unknown_month_distinct(self):
        facts = clone(self.sample)
        facts.metadata["coverage"]["complete_start"] = "2026-08-01"
        engine = FinancialEngine(facts)
        self.assertEqual(engine.summary("2026-08")["net_revenue"], ZERO)
        self.assertIsNone(engine.summary("2026-07")["net_revenue"])
        mom = trend_comparison(engine, "2026-09")["mom"]["net_revenue"]
        self.assertEqual(mom["change_amount"], Decimal("3240"))
        self.assertIsNone(mom["change_rate"])
        self.assertEqual(mom["rate_unavailable_reason"], "nonpositive_base")

    def test_boundary_refund_is_observed_not_complete_october(self):
        result = FinancialEngine(self.sample).summary("2026-10")
        self.assertFalse(result["is_complete"])
        self.assertEqual(result["actual_status"], "partial")
        self.assertIsNone(result["net_revenue"])
        self.assertEqual((result["observed_metrics"]["net_revenue"], result["observed_metrics"]["net_cost"], result["observed_metrics"]["gross_margin"]), (Decimal("-110"), Decimal("-70"), Decimal("-40")))

    def test_complete_refund_only_month_and_nonpositive_base(self):
        facts = clone(self.sample)
        facts.metadata["coverage"]["complete_end"] = "2026-11-30"
        engine = FinancialEngine(facts)
        october = engine.summary("2026-10")
        self.assertEqual((october["net_revenue"], october["net_cost"], october["gross_margin"]), (Decimal("-110"), Decimal("-70"), Decimal("-40")))
        self.assertIsNone(october["gross_margin_rate"])
        self.assertIsNone(october["average_order_value"])
        self.assertIsNone(trend_comparison(engine, "2026-11")["mom"]["net_revenue"]["change_rate"])

    def test_ytd_requires_january_to_chosen_month(self):
        result = year_to_date(FinancialEngine(self.sample), "2026-09")
        self.assertIsNone(result["current"]["net_revenue"])
        self.assertEqual(result["current"]["observed_metrics"]["net_revenue"], Decimal("3240"))
        self.assertEqual(len(result["current"]["missing_months"]), 8)

    def test_gap_is_not_replaced_with_last_active_month(self):
        facts = clone(self.sample)
        facts.metadata["coverage"] = {"complete_start": "2026-01-01", "complete_end": "2026-09-30", "incomplete_months": ["2026-08"]}
        engine = FinancialEngine(facts)
        self.assertIsNone(trend_comparison(engine, "2026-09")["mom"]["net_revenue"]["change_rate"])
        self.assertIsNone(year_to_date(engine, "2026-09")["current"]["net_revenue"])
        self.assertEqual(len(engine.monthly("2026-01", "2026-09")), 9)

    def test_expense_only_month_and_loaded_zero_expenses(self):
        facts = empty_facts()
        facts.tables["expenses"] = pd.DataFrame([{"entity_id": "EDGE", "expense_id": "E1", "expense_date": date(2026,9,1), "expense_category": "payroll", "department": "D04", "channel_scope": "ALL", "region_scope": "ALL", "amount": Decimal("100")}], columns=CONTRACT["expenses"])
        engine = FinancialEngine(facts)
        result = engine.summary("2026-09")
        self.assertEqual((result["net_revenue"], result["gross_margin"], result["expenses"], result["operating_profit"]), (ZERO, ZERO, Decimal("100"), Decimal("-100")))
        self.assertIsNone(result["operating_margin_rate"])
        self.assertEqual(engine.summary("2026-08")["expenses"], ZERO)

    def test_missing_cost_retains_revenue_and_blocks_profit(self):
        facts = clone(self.sample)
        facts.tables["sales"].loc[facts.tables["sales"]["product_id"] == "P001", "cogs_amount"] = None
        engine = FinancialEngine(facts)
        result = engine.summary("2026-09")
        self.assertEqual(result["net_revenue"], Decimal("3240"))
        self.assertIsNone(result["gross_margin"])
        self.assertIsNone(result["operating_profit"])
        known = engine.summary("2026-09", filters=Filters(products="P002"))
        self.assertEqual(known["gross_margin"], Decimal("30"))

    def test_missing_expense_source_differs_from_loaded_empty(self):
        facts = clone(self.sample)
        facts.tables["expenses"] = facts.tables["expenses"].iloc[:0]
        facts.metadata["data_availability"]["expenses"] = False
        result = FinancialEngine(facts).summary("2026-09")
        self.assertIsNone(result["expenses"])
        self.assertIsNone(result["operating_profit"])
        facts.metadata["data_availability"]["expenses"] = True
        self.assertEqual(FinancialEngine(facts).summary("2026-09")["operating_profit"], Decimal("1185"))

    def test_missing_refund_source_not_assumed_zero(self):
        facts = clone(self.sample)
        facts.tables["refunds"] = facts.tables["refunds"].iloc[:0]
        facts.metadata["data_availability"]["refunds"] = False
        result = FinancialEngine(facts).summary("2026-09")
        self.assertEqual(result["sales_revenue"], Decimal("4150"))
        self.assertIsNone(result["net_revenue"])
        self.assertIsNone(result["net_quantity"])

    def test_budget_baseline_direction_and_profit_bridge(self):
        result = company_budget_comparison(FinancialEngine(self.sample), "2026-09")
        totals = result["sales"]["totals"]
        self.assertEqual((totals["net_revenue"]["budget"], totals["net_cost"]["budget"], totals["gross_margin"]["budget"]), (Decimal("3380"), Decimal("2100"), Decimal("1280")))
        self.assertEqual(totals["net_revenue"]["completion_rate"], Decimal("3240")/3380)
        self.assertEqual(result["expenses"]["total"]["variance"], Decimal("20"))
        self.assertEqual(result["expenses"]["total"]["direction"], "unfavorable")
        self.assertEqual(totals["net_cost"]["direction"], "favorable")
        self.assertEqual(result["operating_profit"]["variance"], totals["gross_margin"]["variance"]-result["expenses"]["total"]["variance"])

    def test_missing_budget_key_keeps_actual_and_null_total_budget(self):
        facts = clone(self.sample)
        budget = facts.tables["sales_budget"]
        facts.tables["sales_budget"] = budget[~((budget["month"] == date(2026,9,1)) & (budget["product_id"] == "P001") & (budget["channel_id"] == "C01"))]
        result = sales_budget_comparison(FinancialEngine(facts), "2026-09")
        self.assertEqual(result["status"], "missing_budget")
        self.assertEqual(len(result["missing_keys"]), 1)
        self.assertEqual(result["totals"]["net_revenue"]["actual"], Decimal("3240"))
        self.assertIsNone(result["totals"]["net_revenue"]["budget"])

    def test_zero_budget_distinct_from_missing(self):
        facts = clone(self.sample)
        for field in ("quantity", "refund_amount", "cost_reversal_amount"):
            facts.tables["sales_budget"][field] = 0 if field == "quantity" else ZERO
        result = sales_budget_comparison(FinancialEngine(facts), "2026-09")
        self.assertEqual(result["status"], "complete")
        revenue = result["totals"]["net_revenue"]
        self.assertEqual((revenue["budget"], revenue["variance"]), (ZERO, Decimal("3240")))
        self.assertIsNone(revenue["completion_rate"])

    def test_missing_expense_budget_blocks_company_budget_profit(self):
        facts = clone(self.sample)
        budget = facts.tables["expense_budget"]
        facts.tables["expense_budget"] = budget[budget["expense_category"] != "marketing"]
        result = company_budget_comparison(FinancialEngine(facts), "2026-09")
        self.assertEqual(result["sales"]["totals"]["net_revenue"]["budget"], Decimal("3380"))
        self.assertIsNone(result["expenses"]["total"]["budget"])
        self.assertIsNone(result["operating_profit"]["budget"])

    def test_versions_not_added_together(self):
        facts = clone(self.sample)
        extra = facts.tables["sales_budget"].copy()
        extra["budget_version"] = "B2026_V2"
        for field in ("quantity", "refund_amount", "cost_reversal_amount"):
            extra[field] *= 2
        facts.tables["sales_budget"] = pd.concat([facts.tables["sales_budget"], extra], ignore_index=True)
        engine = FinancialEngine(facts)
        first = sales_budget_comparison(engine, "2026-09", version="B2026_V1")
        second = sales_budget_comparison(engine, "2026-09", version="B2026_V2")
        self.assertEqual(first["totals"]["net_revenue"]["budget"], Decimal("3380"))
        self.assertEqual(second["totals"]["net_revenue"]["budget"], Decimal("6760"))
        with self.assertRaisesRegex(ValueError, "未知预算版本"):
            sales_budget_comparison(engine, "2026-09", version="TYPO")

    def test_missing_budget_month_and_no_budget_source(self):
        facts = clone(self.sample)
        facts.metadata["coverage"]["complete_start"] = "2026-08-01"
        result = sales_budget_comparison(FinancialEngine(facts), "2026-08", "2026-09")
        self.assertEqual(result["missing_months"], [date(2026,8,1)])
        self.assertIsNone(result["totals"]["net_revenue"]["budget"])
        facts.tables["sales_budget"] = facts.tables["sales_budget"].iloc[:0]
        facts.tables["expense_budget"] = facts.tables["expense_budget"].iloc[:0]
        result = company_budget_comparison(FinancialEngine(facts), "2026-09")
        self.assertEqual(result["sales"]["status"], "no_budget")
        self.assertIsNone(result["operating_profit"]["budget"])

    def test_missing_budget_cost_and_precision_not_rounded(self):
        facts = clone(self.sample)
        facts.tables["sales_budget"].loc[0, "unit_cost"] = None
        result = sales_budget_comparison(FinancialEngine(facts), "2026-09")
        self.assertEqual(result["totals"]["net_revenue"]["budget"], Decimal("3380"))
        self.assertIsNone(result["totals"]["gross_margin"]["budget"])
        self.assertEqual(result["cost_status"], "missing_unit_cost")
        facts = clone(self.sample)
        row = facts.tables["sales_budget"].iloc[0].copy()
        row["quantity"], row["net_unit_price"], row["unit_cost"] = 3, Decimal("0.3333"), Decimal("0.1234")
        row["refund_amount"] = row["cost_reversal_amount"] = ZERO
        facts.tables["sales_budget"] = pd.DataFrame([row], columns=CONTRACT["sales_budget"])
        result = sales_budget_comparison(FinancialEngine(facts), "2026-09", filters=Filters(products="P001", channels="C01", regions="R01"))
        self.assertEqual(result["totals"]["net_revenue"]["budget"], Decimal("0.9999"))

    def test_entity_identity_and_invalid_parameters(self):
        facts = clone(self.sample)
        facts.tables["sales"].loc[0, "entity_id"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "一个企业"):
            FinancialEngine(facts)
        with self.assertRaises(ValueError):
            Filters(products=[])
        engine = FinancialEngine(self.sample)
        with self.assertRaises(ValueError):
            engine.summary("2026-09-30")
        with self.assertRaises(ValueError):
            engine.summary("2026-10", "2026-09")
        with self.assertRaisesRegex(ValueError, "未知筛选"):
            engine.summary("2026-09", filters=Filters(products="BAD"))

    def test_monthly_unknown_counts_are_json_null_and_known_counts_integer(self):
        series = FinancialEngine(self.sample).monthly("2026-08", "2026-10")
        records = series.to_dict("records")
        self.assertIsNone(records[0]["confirmed_orders"])
        self.assertIsInstance(records[1]["confirmed_orders"], int)
        self.assertIsNone(records[2]["confirmed_orders"])
        json.dumps(records, default=encode, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
