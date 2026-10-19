from copy import deepcopy
from datetime import date
from decimal import Decimal,localcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis import FinancialEngine,Filters
from analysis.forecast import History,accuracy,forecast_base,known_sum,period_summary,predict
from analysis.scenario import Assumptions,apply_scenario,forecast_pack
from analysis.forecast_store import load_forecast,save_forecast
from etl.sources import CONTRACT,Facts,load_facts
from etl.common import ZERO


def clone(facts):
    return Facts({name:frame.copy(deep=True) for name,frame in facts.tables.items()},deepcopy(facts.metadata))


def simple_history():
    tables={name:[] for name in CONTRACT}
    for year,last in ((2025,12),(2026,9)):
        for month in range(1,last+1):
            when=date(year,month,1)
            tag=f"{year}{month:02}"
            tables["sales"].append(dict(entity_id="EDGE9",sale_line_id="S"+tag,order_id="O"+tag,revenue_date=when,product_id="A",channel_id="C",region_id="R",quantity=100,sales_amount_before_refund=Decimal(10000),cogs_amount=Decimal(6000)))
            tables["refunds"].append(dict(entity_id="EDGE9",refund_id="F"+tag,sale_line_id="S"+tag,refund_date=date(year,month,2),returned_quantity=5,recoverable_quantity=5,refund_amount=Decimal(500),cost_reversal_amount=Decimal(300)))
            tables["expenses"].append(dict(entity_id="EDGE9",expense_id="E"+tag,expense_date=when,expense_category="administration",department="D",channel_scope="ALL",region_scope="ALL",amount=Decimal(1000)))
    for month in range(1,13):
        when=date(2026,month,1)
        tables["sales_budget"].append(dict(entity_id="EDGE9",budget_version="V1",month=when,product_id="A",channel_id="C",region_id="R",quantity=100,net_unit_price=Decimal(100),unit_cost=Decimal(60),refund_amount=Decimal(500),cost_reversal_amount=Decimal(300)))
        tables["expense_budget"].append(dict(entity_id="EDGE9",budget_version="V1",month=when,expense_category="administration",department="D",channel_scope="ALL",region_scope="ALL",amount=Decimal(1000)))
    return Facts({name:pd.DataFrame(rows,columns=CONTRACT[name]) for name,rows in tables.items()},{"entity_id":"EDGE9","rule_version":"sales_v1","coverage":{"complete_start":"2025-01-01","complete_end":"2026-09-30"},"semantics":{"quantity_unit":"件"},"data_availability":{name:True for name in CONTRACT}})


def base_for(facts,method="recent_mean",cutoff="2026-09",window=3):
    return forecast_base(FinancialEngine(facts),cutoff,method,window,"V1")


class ForecastRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simple=simple_history()
        cls.demo=load_facts(ROOT/"configs/demo_files.json")
        cls.demo_base=forecast_base(FinancialEngine(cls.demo),"2026-09")

    def test_recent_mean_manual_drivers(self):
        base=base_for(self.simple)
        row=base["forecast_periods"][0]["sales"][0]
        self.assertEqual((row["sales_quantity"],row["net_unit_price"],row["unit_cost"]),(100,Decimal(100),Decimal(60)))
        summary=period_summary(base["forecast_periods"][0],base["metadata"]["available_sources"])
        self.assertEqual((summary["net_revenue"],summary["net_cost"],summary["gross_margin"],summary["operating_profit"]),(Decimal(9500),Decimal(5700),Decimal(3800),Decimal(2800)))

    def test_seasonal_baseline_equals_original_same_month(self):
        base=base_for(self.simple,"last_year_same_month")
        engine=FinancialEngine(self.simple)
        for period in base["forecast_periods"]:
            expected=engine.summary(period["month"].replace(year=2025))
            actual=period_summary(period,base["metadata"]["available_sources"])
            for field in ("net_revenue","net_cost","gross_margin","expenses","operating_profit"):
                self.assertEqual(actual[field],expected[field])

    def test_annual_actual_plus_remaining_and_future_boundary(self):
        pack=forecast_pack(self.demo_base)
        cutoff=date(2026,9,1)
        self.assertTrue(all(row["month"]<=cutoff and row["kind"]=="actual" for row in pack["actual_company_monthly"]))
        for item in pack["scenarios"].values():
            self.assertTrue(all(row["month"]>cutoff and row["kind"]=="forecast" for row in item["company_monthly"]))
            with localcontext() as context:
                context.prec=60
                for field in ("net_revenue","gross_margin","expenses","operating_profit"):
                    self.assertEqual(item["company_annual"][field],item["company_ytd"][field]+item["company_remaining"][field])

    def test_zero_scenario_exactly_preserves_base(self):
        self.assertEqual(apply_scenario(self.demo_base["forecast_periods"],self.demo_base["metadata"]["available_sources"],Assumptions()),self.demo_base["forecast_periods"])
        pack=forecast_pack(self.demo_base)
        self.assertEqual(pack["scenarios"]["base"],pack["scenarios"]["custom"])

    def test_price_and_quantity_multiply_not_add(self):
        base=base_for(self.simple)
        periods=apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(price_change="0.05",quantity_change="-0.03"))
        row=periods[0]["sales"][0]
        self.assertEqual((row["sales_quantity"],row["net_unit_price"],row["sales_revenue"]),(97,Decimal(105),Decimal(10185)))
        self.assertEqual(row["refund_amount"],Decimal("509.25"))
        self.assertEqual(row["cogs_reversal_amount"],Decimal("305.55"))

    def test_cost_and_fixed_expense_effects(self):
        base=base_for(self.simple)
        old=period_summary(base["forecast_periods"][0],base["metadata"]["available_sources"])
        new=period_summary(apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(unit_cost_change="0.10",expense_change="0.10"))[0],base["metadata"]["available_sources"])
        self.assertEqual(new["operating_profit"]-old["operating_profit"],Decimal(-700))

    def test_marketing_only_changes_its_category(self):
        facts=clone(self.simple)
        extra=facts.tables["expenses"].copy()
        extra["expense_id"]=extra["expense_id"]+"M"
        extra["expense_category"]="marketing"
        facts.tables["expenses"]=pd.concat([facts.tables["expenses"],extra],ignore_index=True)
        base=base_for(facts)
        new=apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(marketing_change="0.10"))[0]
        values={row["expense_category"]:row["amount"] for row in new["expense_rows"]}
        self.assertEqual(values,{"administration":Decimal(1000),"marketing":Decimal(1100)})

    def test_variable_commission_and_logistics_follow_correct_drivers(self):
        facts=clone(self.simple)
        facts.tables["expenses"]["expense_category"]="platform_commission"
        extra=facts.tables["expenses"].copy()
        extra["expense_id"]=extra["expense_id"]+"L"
        extra["expense_category"]="logistics"
        facts.tables["expenses"]=pd.concat([facts.tables["expenses"],extra],ignore_index=True)
        base=base_for(facts)
        new=apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(price_change="0.05",quantity_change="-0.03"))[0]
        values={row["expense_category"]:row["amount"] for row in new["expense_rows"]}
        self.assertEqual(values,{"platform_commission":Decimal("1018.50"),"logistics":Decimal(970)})

    def test_forecast_quantity_rounds_half_up_and_no_negative(self):
        facts=clone(self.simple)
        facts.tables["sales"].loc[facts.tables["sales"]["revenue_date"].ge(date(2026,7,1)),"quantity"]=1
        base=base_for(facts)
        new=apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(quantity_change="-0.50"))[0]
        self.assertEqual(new["sales"][0]["sales_quantity"],1)
        zero=apply_scenario(base["forecast_periods"],base["metadata"]["available_sources"],Assumptions(quantity_change=-1))[0]
        self.assertEqual((zero["sales"][0]["sales_quantity"],zero["sales"][0]["sales_revenue"]),(0,ZERO))

    def test_future_actual_new_dimensions_and_budget_do_not_leak(self):
        changed=clone(self.simple)
        changed.metadata["coverage"]["complete_end"]="2026-12-31"
        extra=changed.tables["sales"].iloc[-1].copy()
        extra["sale_line_id"]="FUTURE_S"
        extra["order_id"]="FUTURE_O"
        extra["revenue_date"]=date(2026,10,1)
        extra["product_id"]="FUTURE_SKU"
        extra["sales_amount_before_refund"]=Decimal(9999999)
        changed.tables["sales"]=pd.concat([changed.tables["sales"],pd.DataFrame([extra])],ignore_index=True)
        changed.tables["sales_budget"]["net_unit_price"]*=9
        before=base_for(self.simple)
        after=base_for(changed)
        self.assertEqual(before["forecast_periods"],after["forecast_periods"])
        self.assertEqual(before["backtest"],after["backtest"])
        self.assertEqual(before["metadata"]["training_fingerprint"],after["metadata"]["training_fingerprint"])
        self.assertNotIn("FUTURE_SKU",after["metadata"]["known_dimensions"]["product_id"])

    def test_backtest_uses_six_origins_and_paired_months(self):
        test=self.demo_base["backtest"]
        self.assertEqual(len(test["origins"]),6)
        self.assertEqual(len(test["details"]),54)
        self.assertTrue(all(row["origin"]<row["target_month"]<=date(2026,9,1) for row in test["details"]))
        self.assertTrue(all(row["n"]==18 for row in test["scores"]))
        self.assertEqual(self.demo_base["metadata"]["method"],"driver_based")

    def test_profit_objective_can_choose_a_different_method(self):
        base=forecast_base(FinancialEngine(self.demo),"2026-09",primary_metric="operating_profit")
        self.assertEqual(base["metadata"]["method"],"last_year_same_month")
        self.assertEqual(base["backtest"]["primary_metric"],"company_operating_profit")

    def test_accuracy_manual_and_zero_denominator(self):
        score=accuracy([(Decimal(100),Decimal(110)),(Decimal(200),Decimal(180))])
        self.assertEqual((score["n"],score["mae"],score["wape"],score["bias"]),(2,Decimal(15),Decimal("0.1"),Decimal(-5)))
        self.assertIsNone(accuracy([(ZERO,Decimal(1))])["wape"])
        self.assertIsNone(accuracy([(None,Decimal(1))])["mae"])
        self.assertEqual(accuracy([(Decimal(-100),Decimal(-90))])["wape"],Decimal("0.1"))

    def test_missing_history_future_cutoff_and_method_validation(self):
        sample=FinancialEngine(load_facts(ROOT/"configs/sample_files.json"))
        base=forecast_base(sample,"2026-09")
        self.assertTrue(all(not period["available"] for period in base["forecast_periods"]))
        self.assertEqual(base["backtest"]["selection_reason"],"insufficient_paired_history_fallback")
        one=forecast_base(sample,"2026-09","recent_mean",1)
        self.assertTrue(all(period["available"] for period in one["forecast_periods"]))
        self.assertIsNone(forecast_pack(one)["scenarios"]["base"]["company_annual"]["net_revenue"])
        with self.assertRaises(ValueError):
            forecast_base(sample,"2026-10")
        with self.assertRaises(ValueError):
            forecast_base(sample,"2026-09","BAD")

    def test_missing_calendar_month_keeps_annual_unknown(self):
        facts=clone(self.simple)
        facts.metadata["coverage"]["incomplete_months"]=["2026-02"]
        pack=forecast_pack(base_for(facts))
        self.assertTrue(all(period["available"] for period in pack["scenarios"]["base"]["future_periods"]))
        self.assertIsNone(pack["scenarios"]["base"]["company_annual"]["net_revenue"])

    def test_missing_cost_preserves_revenue_only(self):
        facts=clone(self.simple)
        facts.tables["sales"].loc[facts.tables["sales"]["revenue_date"].eq(date(2026,8,1)),"cogs_amount"]=None
        pack=forecast_pack(base_for(facts))
        self.assertIsNotNone(pack["scenarios"]["base"]["company_annual"]["net_revenue"])
        self.assertIsNone(pack["scenarios"]["base"]["company_annual"]["gross_margin"])

    def test_missing_refunds_and_expenses_are_not_zero(self):
        for name in ("refunds","expenses"):
            facts=clone(self.simple)
            facts.tables[name]=facts.tables[name].iloc[:0]
            facts.metadata["data_availability"][name]=False
            pack=forecast_pack(base_for(facts))
            annual=pack["scenarios"]["base"]["company_annual"]
            self.assertIsNone(annual["operating_profit"])
            self.assertIsNone(annual["net_revenue"]) if name=="refunds" else self.assertIsNotNone(annual["net_revenue"])

    def test_zero_activity_complete_source_has_zero_forecast(self):
        facts=clone(self.simple)
        for name in ("sales","refunds","expenses"):
            facts.tables[name]=facts.tables[name].iloc[:0]
        pack=forecast_pack(base_for(facts))
        self.assertEqual(pack["scenarios"]["base"]["company_annual"]["operating_profit"],ZERO)

    def test_refund_only_history_can_forecast_negative_net_revenue(self):
        facts=clone(self.simple)
        mask=facts.tables["sales"]["revenue_date"].ge(date(2026,7,1))
        facts.tables["sales"]=facts.tables["sales"][~mask]
        mask=facts.tables["refunds"]["refund_date"].ge(date(2026,7,1))
        facts.tables["refunds"].loc[mask,"sale_line_id"]="S202606"
        base=base_for(facts)
        summary=period_summary(base["forecast_periods"][0],base["metadata"]["available_sources"])
        self.assertEqual(summary["net_revenue"],Decimal(-500))
        self.assertIsNone(summary["gross_margin_rate"])

    def test_year_end_has_no_future_and_zero_remaining(self):
        facts=clone(self.simple)
        facts.metadata["coverage"]["complete_end"]="2026-12-31"
        base=base_for(facts,cutoff="2026-12")
        self.assertEqual(base["forecast_periods"],[])
        pack=forecast_pack(base)
        self.assertEqual(pack["scenarios"]["base"]["company_remaining"]["net_revenue"],ZERO)

    def test_sales_filter_does_not_allocate_company_fees(self):
        all_business=forecast_pack(self.demo_base)
        selected=forecast_pack(self.demo_base,Filters(products="P001",channels="C02"))
        self.assertIsNone(selected["scenarios"]["base"]["selected_annual"]["operating_profit"])
        self.assertEqual(selected["scenarios"]["base"]["company_annual"],all_business["scenarios"]["base"]["company_annual"])
        self.assertLess(selected["scenarios"]["base"]["selected_annual"]["net_revenue"],all_business["scenarios"]["base"]["selected_annual"]["net_revenue"])

    def test_unobserved_scope_is_unknown_not_zero(self):
        pack=forecast_pack(base_for(self.simple),Filters(products="FUTURE_SKU"))
        self.assertFalse(pack["metadata"]["selected_scope_known"])
        self.assertIsNone(pack["scenarios"]["base"]["selected_annual"]["net_revenue"])

    def test_future_budget_month_missing_does_not_change_prediction(self):
        facts=clone(self.simple)
        facts.tables["sales_budget"]=facts.tables["sales_budget"][facts.tables["sales_budget"]["month"].ne(date(2026,12,1))]
        before=base_for(self.simple)
        after=base_for(facts)
        self.assertEqual(before["forecast_periods"],after["forecast_periods"])
        pack=forecast_pack(after)
        self.assertIsNone(pack["scenarios"]["base"]["company_budget_comparison"]["net_revenue"]["budget"])
        self.assertIn(date(2026,12,1),pack["budget_reference"]["company"]["missing_sales_months"])

    def test_no_budget_sources_do_not_block_prediction_or_invent_budget(self):
        facts=clone(self.simple)
        for name in ("sales_budget","expense_budget"):
            facts.tables[name]=facts.tables[name].iloc[:0]
            facts.metadata["data_availability"][name]=False
        result=forecast_pack(base_for(facts))
        self.assertEqual(result["scenarios"]["base"]["company_annual"]["net_revenue"],Decimal(114000))
        self.assertIsNone(result["scenarios"]["base"]["company_budget_comparison"]["net_revenue"]["budget"])

    def test_assumptions_validate_and_inputs_not_mutated(self):
        for value in ("NaN","Infinity","bad","-1.01","10.01"):
            with self.assertRaises(ValueError):
                Assumptions(price_change=value)
        before=deepcopy(self.demo_base)
        forecast_pack(self.demo_base,custom=Assumptions(price_change="0.05"))
        self.assertEqual(self.demo_base,before)

    def test_saved_version_is_frozen_reused_and_tamper_detected(self):
        directory=ROOT/"outputs/stage9/test_versions"
        directory.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            pack=forecast_pack(base_for(self.simple))
            first=save_forecast(pack,temporary)
            self.assertFalse(first["reused"])
            self.assertTrue(save_forecast(pack,temporary)["reused"])
            equivalent=forecast_pack(base_for(self.simple),custom=Assumptions(price_change="0.00",quantity_change="-0.0"))
            self.assertEqual(save_forecast(equivalent,temporary)["run_id"],first["run_id"])
            record=load_forecast(first["path"])
            self.assertEqual(record["scenario_versions"]["optimistic"]["base_run_id"],record["base_run_id"])
            new=save_forecast(forecast_pack(base_for(self.simple),custom=Assumptions(price_change="0.01")),temporary)
            self.assertNotEqual(first["run_id"],new["run_id"])
            record["result"]["metadata"]["method"]="TAMPERED"
            Path(first["path"]).write_text(json.dumps(record),encoding="utf-8")
            with self.assertRaises(ValueError):
                save_forecast(pack,temporary)


if __name__=="__main__":
    unittest.main()
