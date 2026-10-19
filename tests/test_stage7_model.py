"""验证展示/下载没有改变统一财务口径与金额精度。"""

from copy import deepcopy
import csv
from datetime import date
from decimal import Decimal
import io
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.comparison import expense_budget_comparison, sales_budget_comparison
from dashboard import budget_rows, chart_frame, csv_bytes, detail_tables, money_text, monthly_trend, percent_text, safe_export_name
from etl.sources import Facts, load_facts


def read_csv(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


class DashboardModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = load_facts(ROOT / "configs/sample_files.json")

    def setUp(self):
        self.engine = FinancialEngine(self.facts)

    def test_download_sales_and_refunds_reconcile_with_sample(self):
        tables = detail_tables(self.engine, "2026-09")
        sales = read_csv(csv_bytes(tables["sales"]))
        refunds = read_csv(csv_bytes(tables["refunds"]))
        sale_amount = sum(Decimal(row["sales_amount_before_refund"]) for row in sales)
        refund_amount = sum(Decimal(row["refund_amount"]) for row in refunds)
        self.assertEqual((len(sales), len(refunds)), (9, 5))
        self.assertEqual((sale_amount, refund_amount, sale_amount-refund_amount), (Decimal("4150"), Decimal("910"), Decimal("3240")))
        self.assertTrue(tables["sales"]["period_is_complete"].all())

    def test_filter_details_and_company_expenses_keep_different_scope(self):
        filters = Filters(products="P001", channels="C02", regions="R02")
        tables = detail_tables(self.engine, "2026-09", filters)
        sale = tables["sales"]
        self.assertEqual((len(sale), sale.iloc[0]["sales_amount_before_refund"], sale.iloc[0]["cogs_amount"]), (1, Decimal("550"), Decimal("350")))
        self.assertTrue(tables["refunds"].empty)
        fees = tables["company_expenses"]
        self.assertEqual((len(fees), sum(fees["amount"])), (5, Decimal("400")))
        self.assertTrue(fees["scope"].eq("company_expenses").all())
        self.assertEqual(fees.attrs["filters"], Filters().as_dict())
        self.assertEqual(len(read_csv(csv_bytes(fees))), 5)

    def test_refund_filter_uses_original_sale_dimensions(self):
        tables = detail_tables(self.engine, "2026-09", Filters(products="P001", channels="C01", regions="R01"))
        refunds = tables["refunds"]
        self.assertEqual(sum(refunds["refund_amount"]), Decimal("910"))
        self.assertTrue(refunds["product_id"].eq("P001").all())
        self.assertTrue(refunds["channel_id"].eq("C01").all())
        self.assertTrue(refunds["region_id"].eq("R01").all())

    def test_crossmonth_refund_is_observed_with_partial_period_flag(self):
        tables = detail_tables(self.engine, "2026-10", Filters(products="P001"))
        self.assertTrue(tables["sales"].empty)
        refunds = tables["refunds"]
        self.assertEqual(len(refunds), 1)
        self.assertEqual((refunds.iloc[0]["refund_amount"], refunds.iloc[0]["cost_reversal_amount"]), (Decimal("110"), Decimal("70")))
        self.assertEqual(refunds.iloc[0]["revenue_date"].month, 9)
        self.assertEqual(refunds.iloc[0]["refund_date"].month, 10)
        self.assertFalse(refunds.iloc[0]["period_is_complete"])
        self.assertFalse(refunds.attrs["period_is_complete"])

    def test_empty_tables_and_missing_source_have_explicit_metadata(self):
        facts = Facts({name: frame.copy(deep=True) for name, frame in self.facts.tables.items()}, deepcopy(self.facts.metadata))
        facts.tables["expenses"] = facts.tables["expenses"].iloc[:0]
        facts.metadata["data_availability"]["expenses"] = False
        tables = detail_tables(FinancialEngine(facts), "2026-09", Filters(products="P002", channels="C01"))
        self.assertTrue(tables["sales"].empty)
        self.assertTrue(tables["company_expenses"].empty)
        self.assertIn("amount", tables["company_expenses"].columns)
        self.assertIn("source_available", tables["company_expenses"].columns)
        self.assertFalse(tables["company_expenses"].attrs["source_available"])
        self.assertFalse(tables["company_expenses"].attrs["period_is_complete"])
        self.assertTrue(tables["company_expenses"].attrs["calendar_is_complete"])
        self.assertIn("source_available", csv_bytes(tables["company_expenses"]).decode("utf-8-sig").splitlines()[0])

    def test_helpers_do_not_mutate_engine_or_return_shared_frames(self):
        before = {name: frame.copy(deep=True) for name, frame in self.engine.tables.items()}
        events_before = self.engine.events.copy(deep=True)
        tables = detail_tables(self.engine, "2026-09")
        series = monthly_trend(self.engine, "2026-08", "2026-10")
        chart_frame(series, ["net_revenue"], unit="万元")
        csv_bytes(tables["sales"])
        tables["sales"].loc[0, "sales_amount_before_refund"] = Decimal("0")
        for name in before:
            pd.testing.assert_frame_equal(before[name], self.engine.tables[name])
        pd.testing.assert_frame_equal(events_before, self.engine.events)
        self.assertEqual(self.engine.summary("2026-09")["net_revenue"], Decimal("3240"))

    def test_trend_unknown_months_are_gaps_and_exact_original_is_retained(self):
        series = monthly_trend(self.engine, "2026-08", "2026-10")
        self.assertEqual(list(series["month"]), [date(2026,8,1), date(2026,9,1), date(2026,10,1)])
        self.assertEqual(list(series["net_revenue"]), [None, Decimal("3240"), None])
        plot = chart_frame(series, ["net_revenue"], unit="万元")
        self.assertTrue(pd.isna(plot.iloc[0]["net_revenue"]))
        self.assertEqual(plot.iloc[1]["net_revenue"], 0.324)
        self.assertTrue(pd.isna(plot.iloc[2]["net_revenue"]))
        self.assertIsInstance(series.iloc[1]["net_revenue"], Decimal)
        decoded = read_csv(csv_bytes(series))
        self.assertEqual([row["net_revenue"] for row in decoded], ["", "3240", ""])

    def test_chart_default_keeps_identity_and_does_not_scale_ratios(self):
        frame = pd.DataFrame([{"entity_id": "甲", "product_id": "P001", "month": "2026-09", "net_revenue": Decimal("3240"), "gross_margin_rate": Decimal("0.125"), "missing": None}], dtype=object)
        plot = chart_frame(frame, unit="万元")
        self.assertEqual(list(plot.columns), list(frame.columns))
        self.assertEqual((plot.iloc[0]["entity_id"], plot.iloc[0]["product_id"], plot.iloc[0]["month"]), ("甲", "P001", "2026-09"))
        self.assertEqual((plot.iloc[0]["net_revenue"], plot.iloc[0]["gross_margin_rate"]), (0.324, 0.125))
        self.assertIsNone(plot.iloc[0]["missing"])
        self.assertIsInstance(frame.iloc[0]["net_revenue"], Decimal)

    def test_sales_budget_rows_preserve_metrics_and_exact_nulls(self):
        comparison = sales_budget_comparison(self.engine, "2026-09", filters=Filters(products="P001", channels="C02", regions="R02"))
        rows = budget_rows(comparison)
        revenue = rows[rows["metric"].eq("net_revenue")].iloc[0]
        self.assertEqual((revenue["actual"], revenue["budget"], revenue["variance"]), (Decimal("550"), Decimal("600"), Decimal("-50")))
        self.assertEqual(revenue["completion_rate"], Decimal("550")/600)
        self.assertEqual(revenue["budget_version"], "B2026_V1")
        self.assertEqual(revenue["scope"], "sales_dimensions")
        self.assertEqual(revenue["direction"], "unfavorable")
        self.assertEqual(len(rows), 3)

    def test_expense_budget_rows_do_not_gain_product_filters(self):
        rows = budget_rows(expense_budget_comparison(self.engine, "2026-09"))
        self.assertEqual((len(rows), sum(rows["actual"]), sum(rows["budget"])), (5, Decimal("400"), Decimal("380")))
        self.assertTrue(rows["scope"].eq("company_expenses").all())
        self.assertTrue(rows["product_id"].isna().all())

    def test_missing_budget_row_csv_is_blank_not_zero(self):
        facts = Facts({name: frame.copy(deep=True) for name, frame in self.facts.tables.items()}, deepcopy(self.facts.metadata))
        frame = facts.tables["sales_budget"]
        facts.tables["sales_budget"] = frame[~(frame["product_id"].eq("P003"))]
        comparison = sales_budget_comparison(FinancialEngine(facts), "2026-09")
        row = next(row for row in read_csv(csv_bytes(budget_rows(comparison))) if row["product_id"] == "P003" and row["metric"] == "net_revenue")
        self.assertEqual(row["actual"], "240")
        self.assertEqual((row["budget"], row["variance"], row["completion_rate"]), ("", "", ""))

    def test_decimal_csv_precision_null_chinese_and_negative_numbers(self):
        frame = pd.DataFrame([{"商品": "厨房置物架", "精确金额": Decimal("0.9999"), "负数": Decimal("-110.00"), "缺失": None, "nan": float("nan"), "日期": date(2026,9,1)}], dtype=object)
        data = csv_bytes(frame)
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        row = read_csv(data)[0]
        self.assertEqual(row, {"商品": "厨房置物架", "精确金额": "0.9999", "负数": "-110.00", "缺失": "", "nan": "", "日期": "2026-09-01"})

    def test_formula_injection_protects_only_text(self):
        values = ["=HYPERLINK(\"https://example.com\")", "+1+2", "-2+3", "@SUM(1)", " \t=1+1", "\tplain", "\r=1+1", "正常商品", "1+2"]
        frame = pd.DataFrame({"=header": values, "number": [Decimal("-2.00")]*len(values)}, dtype=object)
        rows = read_csv(csv_bytes(frame))
        self.assertEqual(list(rows[0]), ["'=header", "number"])
        for position, value in enumerate(values):
            self.assertEqual(rows[position]["'=header"], "'"+value if position < 7 else value)
            self.assertEqual(rows[position]["number"], "-2.00")

    def test_labels_round_display_only(self):
        number = Decimal("123456.7899")
        self.assertEqual(money_text(number), "123,456.79")
        self.assertEqual(money_text(number, "万元"), "12.35")
        self.assertEqual(percent_text(Decimal("0.9585798816568047337278106509")), "95.86%")
        self.assertEqual(money_text(Decimal("-0.001")), "0.00")
        self.assertEqual((money_text(None), percent_text(None), money_text(pd.NA)), ("—", "—", "—"))
        self.assertEqual(number, Decimal("123456.7899"))
        with self.assertRaises(ValueError):
            money_text(number, "美元")

    def test_export_names_identify_scope_and_sanitize_windows_paths(self):
        filters = Filters(products=["P002", "P001"], channels="C02", regions="R02")
        name = safe_export_name("企业/甲", "2026-09", "sales", filters, fingerprint="abcdef1234567890")
        self.assertIn("企业_甲__2026-09__sales", name)
        self.assertIn("products-P001+P002", name)
        self.assertIn("snapshot-abcdef123456", name)
        self.assertTrue(name.endswith(".csv"))
        self.assertNotIn("/", name)
        company = safe_export_name("企业甲", "2026-09", "company_expenses", filters)
        self.assertIn("__company.csv", company)
        self.assertNotIn("P001", company)
        long_name = safe_export_name("CON", "2024-01", "trend", Filters(products=["P"+str(i) for i in range(100)]), end="2026-09", version="B2026_V1")
        self.assertTrue(long_name.startswith("_CON__2024-01_to_2026-09"))
        self.assertTrue(safe_export_name("CON.txt", "2026-09", "sales").startswith("_CON.txt__"))
        self.assertLessEqual(len(long_name), 204)
        self.assertNotEqual(safe_export_name("X", "2026-09", "sales", Filters(products="P001")), safe_export_name("X", "2026-09", "sales", Filters(products="P002")))

    def test_invalid_filter_rejected_consistently(self):
        with self.assertRaisesRegex(ValueError, "未知筛选"):
            detail_tables(self.engine, "2026-09", Filters(products="UNKNOWN"))
        with self.assertRaises(ValueError):
            monthly_trend(self.engine, "2026-10", "2026-09")


class DifferentSourceEquivalence(unittest.TestCase):
    def test_renamed_full_source_has_equal_monthly_and_detail_exports(self):
        first = FinancialEngine(load_facts(ROOT / "configs/demo_files.json"))
        second = FinancialEngine(load_facts(ROOT / "configs/demo_renamed_files.json"))
        filters = Filters(products="P001", channels="C02", regions="R02")
        pd.testing.assert_frame_equal(monthly_trend(first, "2026-01", "2026-09", filters), monthly_trend(second, "2026-01", "2026-09", filters))
        one, two = detail_tables(first, "2026-09", filters), detail_tables(second, "2026-09", filters)
        for name in one:
            key = {"sales": "sale_line_id", "refunds": "refund_id", "company_expenses": "expense_id"}[name]
            self.assertEqual(csv_bytes(one[name].sort_values(key)), csv_bytes(two[name].sort_values(key)))


if __name__ == "__main__":
    unittest.main()
