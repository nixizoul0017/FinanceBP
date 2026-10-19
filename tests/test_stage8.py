from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analysis import FinancialEngine, Filters
from analysis.variance import variance_pack
from etl.common import ZERO
from etl.sources import CONTRACT, Facts, load_facts


def clone(facts):
    return Facts({name: frame.copy(deep=True) for name, frame in facts.tables.items()}, deepcopy(facts.metadata))


def example():
    tables = {name: pd.DataFrame(columns=columns) for name, columns in CONTRACT.items()}
    entity = "EXAMPLE"
    tables["sales"] = pd.DataFrame([dict(entity_id=entity, sale_line_id="S"+name, order_id="O"+name, revenue_date=date(2026,9,1), product_id=name, channel_id="C", region_id="R", quantity=q, sales_amount_before_refund=Decimal(revenue), cogs_amount=Decimal(cost)) for name,q,revenue,cost in [("A",12,"1080","780"),("B",8,"1600","920")]], columns=CONTRACT["sales"])
    tables["refunds"] = pd.DataFrame([dict(entity_id=entity,refund_id="F",sale_line_id="SA",refund_date=date(2026,9,2),refund_amount=Decimal(80),returned_quantity=1,recoverable_quantity=1,cost_reversal_amount=Decimal(32))],columns=CONTRACT["refunds"])
    tables["sales_budget"] = pd.DataFrame([dict(entity_id=entity,budget_version="V1",month=date(2026,9,1),product_id=name,channel_id="C",region_id="R",quantity=10,net_unit_price=Decimal(price),unit_cost=Decimal(cost),refund_amount=ZERO,cost_reversal_amount=ZERO) for name,price,cost in [("A",100,60),("B",200,120)]], columns=CONTRACT["sales_budget"])
    fees=dict(entity_id=entity,expense_category="marketing",department="sales",channel_scope="ALL",region_scope="ALL")
    tables["expenses"] = pd.DataFrame([{**fees,"expense_id":"E","expense_date":date(2026,9,1),"amount":Decimal(100)}],columns=CONTRACT["expenses"])
    tables["expense_budget"] = pd.DataFrame([{**fees,"budget_version":"V1","month":date(2026,9,1),"amount":Decimal(90)}],columns=CONTRACT["expense_budget"])
    return Facts(tables,{"entity_id":entity,"rule_version":"sales_v1","coverage":{"complete_start":"2026-09-01","complete_end":"2026-09-30"},"semantics":{"quantity_unit":"件"}})


def amounts(bridge):
    return {row["factor"]:row["amount"] for row in bridge["components"]}


class VarianceRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample=load_facts(ROOT/"configs/sample_files.json")
        cls.demo=load_facts(ROOT/"configs/demo_files.json")

    def test_manual_price_volume_mix_refund(self):
        result=variance_pack(FinancialEngine(example()),"2026-09",version="V1")
        bridge=result["selected"]["revenue_bridge"]
        self.assertEqual((bridge["budget"],bridge["actual"],bridge["variance"]),(Decimal(3000),Decimal(2600),Decimal(-400)))
        values=amounts(bridge)
        self.assertEqual((values["volume"],values["mix"],values["price"],values["refund"]),(ZERO,Decimal(-200),Decimal(-120),Decimal(-80)))

    def test_manual_margin_and_company_profit_bridge(self):
        result=variance_pack(FinancialEngine(example()),"2026-09",version="V1")
        bridge=result["selected"]["gross_margin_bridge"]
        self.assertEqual(bridge["variance"],Decimal(-268))
        values=amounts(bridge)
        self.assertEqual((values["product_volume"],values["price"],values["unit_cost"],values["refund"],values["cost_reversal"]),(Decimal(-80),Decimal(-120),Decimal(-20),Decimal(-80),Decimal(32)))
        self.assertNotIn("mix",values)
        profit=result["company_operating_bridge"]
        self.assertEqual(profit["variance"],Decimal(-278))
        self.assertEqual(amounts(profit)["expense"],Decimal(-10))

    def test_sample_reconciles_with_prior_sql(self):
        result=variance_pack(FinancialEngine(self.sample),"2026-09")
        for kind,difference in (("sales_bridge",-130),("revenue_bridge",-140),("gross_margin_bridge",-95)):
            bridge=result["selected"][kind]
            self.assertEqual(bridge["variance"],Decimal(difference))
            self.assertTrue(bridge["reconciled"])
        self.assertEqual(result["company_operating_bridge"]["variance"],Decimal(-115))

    def test_all_nine_budget_months_and_filtered_scope_reconcile(self):
        engine=FinancialEngine(self.demo)
        for month in range(1,10):
            for filters in (Filters(),Filters(channels="C03",regions="R01")):
                result=variance_pack(engine,f"2026-{month:02}",filters)
                for bridge in [result["selected"][kind] for kind in ("sales_bridge","revenue_bridge","gross_margin_bridge")]+[result["company_operating_bridge"]]:
                    self.assertTrue(bridge["reconciled"])
                    self.assertLess(abs(bridge["representation_residual"]),Decimal("1e-40"))

    def test_company_profit_and_fees_do_not_follow_product_filter(self):
        engine=FinancialEngine(self.sample)
        company=variance_pack(engine,"2026-09")
        filtered=variance_pack(engine,"2026-09",Filters(products="P001",channels="C02",regions="R02"))
        self.assertEqual(filtered["company_operating_bridge"],company["company_operating_bridge"])
        self.assertEqual(filtered["company_expense_details"],company["company_expense_details"])
        self.assertEqual(filtered["selected"]["revenue_bridge"]["actual"],Decimal(550))

    def test_explicit_zero_budget_new_sales_is_separate(self):
        facts=example()
        facts.tables["sales_budget"].loc[0,"quantity"]=0
        result=variance_pack(FinancialEngine(facts),"2026-09",version="V1")
        revenue=result["selected"]["revenue_bridge"]
        self.assertTrue(revenue["reconciled"])
        self.assertEqual(amounts(revenue)["new_product"],Decimal(1080))
        row=next(row for row in result["selected"]["products"] if row["product_id"]=="A")
        self.assertIsNone(row["price_budget"])
        self.assertEqual(row["product_state"],"actual_only")

    def test_budget_sales_with_no_actual_is_separate(self):
        facts=example()
        facts.tables["sales"]=facts.tables["sales"].iloc[:1]
        result=variance_pack(FinancialEngine(facts),"2026-09",version="V1")
        self.assertEqual(amounts(result["selected"]["revenue_bridge"])["no_sales_product"],Decimal(-2000))
        self.assertEqual(amounts(result["selected"]["gross_margin_bridge"])["no_sales_product"],Decimal(-800))

    def test_zero_total_actual_quantity_preserves_refunds(self):
        facts=clone(self.sample)
        facts.metadata["coverage"]["complete_end"]="2026-10-31"
        budget=facts.tables["sales_budget"]
        budget=budget[budget["month"].eq(date(2026,10,1))]
        facts.tables["sales_budget"]=budget
        result=variance_pack(FinancialEngine(facts),"2026-10")
        bridge=result["selected"]["revenue_bridge"]
        self.assertTrue(bridge["reconciled"])
        self.assertEqual(bridge["actual"],Decimal(-110))
        self.assertEqual(result["selected"]["common_product_count"],0)
        self.assertTrue(all(row["price_actual"] is None for row in result["selected"]["products"]))

    def test_all_zero_budget_and_actual_has_no_forced_prices(self):
        facts=example()
        facts.tables["sales"]=facts.tables["sales"].iloc[:0]
        facts.tables["refunds"]=facts.tables["refunds"].iloc[:0]
        facts.tables["sales_budget"]["quantity"]=0
        result=variance_pack(FinancialEngine(facts),"2026-09",version="V1")
        self.assertEqual(result["selected"]["revenue_bridge"]["variance"],ZERO)
        self.assertTrue(result["selected"]["revenue_bridge"]["reconciled"])
        self.assertTrue(all(row["price_budget"] is None for row in result["selected"]["products"]))

    def test_missing_budget_key_is_not_new_product(self):
        facts=example()
        facts.tables["sales_budget"]=facts.tables["sales_budget"].iloc[1:]
        result=variance_pack(FinancialEngine(facts),"2026-09",version="V1")
        bridge=result["selected"]["revenue_bridge"]
        self.assertEqual(bridge["reason"],"budget_incomplete")
        self.assertEqual(bridge["components"],[])
        self.assertIsNone(bridge["budget"])

    def test_future_partial_month_is_not_complete_actual(self):
        result=variance_pack(FinancialEngine(self.sample),"2026-10")
        self.assertEqual(result["selected"]["revenue_bridge"]["reason"],"actual_incomplete")
        self.assertIsNone(result["company_operating_bridge"]["actual"])

    def test_no_budget_source_keeps_unknown(self):
        facts=clone(self.sample)
        facts.tables["sales_budget"]=facts.tables["sales_budget"].iloc[:0]
        facts.tables["expense_budget"]=facts.tables["expense_budget"].iloc[:0]
        facts.metadata["data_availability"]["sales_budget"]=False
        result=variance_pack(FinancialEngine(facts),"2026-09")
        self.assertEqual(result["selected"]["sales_bridge"]["reason"],"budget_incomplete")

    def test_missing_refund_source_keeps_sales_pvm_only(self):
        facts=clone(self.sample)
        facts.metadata["data_availability"]["refunds"]=False
        facts.tables["refunds"]=facts.tables["refunds"].iloc[:0]
        result=variance_pack(FinancialEngine(facts),"2026-09")
        self.assertTrue(result["selected"]["sales_bridge"]["reconciled"])
        self.assertEqual(result["selected"]["revenue_bridge"]["reason"],"refund_source_missing")
        self.assertIsNone(result["selected"]["revenue_bridge"]["actual"])

    def test_missing_actual_cost_does_not_remove_revenue_bridge(self):
        facts=clone(self.sample)
        facts.tables["sales"].loc[0,"cogs_amount"]=None
        result=variance_pack(FinancialEngine(facts),"2026-09")
        self.assertTrue(result["selected"]["revenue_bridge"]["reconciled"])
        self.assertEqual(result["selected"]["gross_margin_bridge"]["reason"],"historic_cost_missing")
        healthy=variance_pack(FinancialEngine(facts),"2026-09",Filters(products="P003"))
        self.assertTrue(healthy["selected"]["gross_margin_bridge"]["reconciled"])

    def test_missing_budget_cost_blocks_margin_only(self):
        facts=clone(self.sample)
        facts.tables["sales_budget"].loc[0,"unit_cost"]=None
        result=variance_pack(FinancialEngine(facts),"2026-09")
        self.assertTrue(result["selected"]["revenue_bridge"]["reconciled"])
        self.assertEqual(result["selected"]["gross_margin_bridge"]["reason"],"budget_cost_missing")

    def test_missing_expenses_or_expense_budget_blocks_company_profit(self):
        for source in ("expenses","expense_budget"):
            facts=clone(self.sample)
            facts.tables[source]=facts.tables[source].iloc[:0]
            facts.metadata["data_availability"][source]=False
            result=variance_pack(FinancialEngine(facts),"2026-09")
            self.assertTrue(result["selected"]["gross_margin_bridge"]["reconciled"])
            self.assertEqual(result["company_operating_bridge"]["status"],"unavailable")

    def test_unknown_quantity_unit_does_not_guess_pvm(self):
        facts=clone(self.sample)
        facts.metadata["semantics"]["quantity_unit"]="工时"
        result=variance_pack(FinancialEngine(facts),"2026-09")
        self.assertEqual(result["selected"]["revenue_bridge"]["reason"],"quantity_unit_unconfirmed")
        self.assertEqual(result["selected"]["revenue_bridge"]["variance"],Decimal(-140))

    def test_budget_versions_are_isolated(self):
        facts=example()
        second=facts.tables["sales_budget"].copy()
        second["budget_version"]="V2"
        second["net_unit_price"]=second["net_unit_price"]*2
        facts.tables["sales_budget"]=pd.concat([facts.tables["sales_budget"],second],ignore_index=True)
        fees=facts.tables["expense_budget"].copy()
        fees["budget_version"]="V2"
        facts.tables["expense_budget"]=pd.concat([facts.tables["expense_budget"],fees],ignore_index=True)
        engine=FinancialEngine(facts)
        self.assertEqual(variance_pack(engine,"2026-09",version="V1")["selected"]["revenue_bridge"]["budget"],Decimal(3000))
        self.assertEqual(variance_pack(engine,"2026-09",version="V2")["selected"]["revenue_bridge"]["budget"],Decimal(6000))
        with self.assertRaises(ValueError):
            variance_pack(engine,"2026-09",version="BAD")

    def test_contribution_ranking_reconciles_and_does_not_use_net_denominator(self):
        result=variance_pack(FinancialEngine(self.demo),"2026-09")
        for dimension,rows in result["selected"]["rankings"].items():
            self.assertEqual(sum((row["variance"] for row in rows),ZERO),result["selected"]["revenue_bridge"]["variance"])
            negative=[row for row in rows if row["variance"]<0]
            self.assertAlmostEqual(sum((row["negative_contribution_share"] for row in negative),ZERO),Decimal(1))
        self.assertEqual(result["expense_ranking"][0]["direction"],"unfavorable")

    def test_input_snapshot_not_mutated_and_renamed_source_equal(self):
        engine=FinancialEngine(self.demo)
        before={name:frame.copy(deep=True) for name,frame in engine.tables.items()}
        first=variance_pack(engine,"2026-09")
        renamed=variance_pack(FinancialEngine(load_facts(ROOT/"configs/demo_renamed_files.json")),"2026-09")
        self.assertEqual(first["selected"],renamed["selected"])
        self.assertEqual(first["company_operating_bridge"],renamed["company_operating_bridge"])
        for name,frame in before.items():
            pd.testing.assert_frame_equal(frame,engine.tables[name])

    def test_product_factor_details_sum_to_components(self):
        result=variance_pack(FinancialEngine(self.demo),"2026-09")
        for bridge in (result["selected"]["revenue_bridge"],result["selected"]["gross_margin_bridge"],result["company_operating_bridge"]):
            with localcontext() as context:
                context.prec=60
                for row in bridge["components"]:
                    summed=sum((r["amount"] for r in bridge["details"] if r["factor"]==row["factor"]),ZERO)
                    self.assertLess(abs(summed-row["amount"]),Decimal("1e-40"))


if __name__=="__main__":
    unittest.main()
