from copy import deepcopy
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis import FinancialEngine,Filters
from analysis.scenario import Assumptions
from etl.sources import load_facts
from reporting.service import build_report,markdown_report,validate_report,value_at
from reporting.tables import workbook_tables
from reporting.excel import excel_bytes,inspect_excel
from test_stage9 import simple_history,clone


def make(facts=None,**kwargs):
    return build_report(FinancialEngine(facts or simple_history()),"2026-09",version="V1",data_origin="个人模拟数据",**kwargs)


class MonthlyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.simple=make()
        cls.payload=excel_bytes(cls.simple)
    def test_manual_actual_budget_forecast_and_fact_paths(self):
        r=self.simple
        self.assertEqual(r["sources"]["analysis"]["selected_scope"]["net_revenue"],Decimal(9500))
        self.assertEqual(r["sources"]["analysis"]["company_scope"]["operating_profit"],Decimal(2800))
        self.assertEqual(r["sources"]["forecast"]["scenarios"]["base"]["company_annual"]["net_revenue"],Decimal(114000))
        for fact in r["commentary"]["facts"]:
            self.assertEqual(value_at(r["sources"],fact["source_path"]),fact["value"])
        self.assertIn("9,500.00元",markdown_report(r))
        self.assertEqual(validate_report(r)["status"],"passed")
        predictions=[row for row in r["commentary"]["statements"] if row["section"]=="全年预测" and row["fact_ids"]]
        self.assertTrue(all(row["kind"]=="模型测算" for row in predictions))
    def test_statement_and_fact_tampering_rejected_before_export(self):
        for field in ("text","value"):
            r=deepcopy(self.simple)
            if field=="text":
                r["commentary"]["statements"][0]["text"]+="999元"
            else:
                r["commentary"]["facts"][0]["value"]+=1
            with self.assertRaises(ValueError):
                excel_bytes(r)
    def test_mismatched_period_source_scope_and_model_rejected(self):
        for field,value in (("month",date(2026,8,1)),("entity_id","OTHER"),("source_fingerprint","WRONG"),("sales_filters",Filters(products="A").as_dict())):
            r=deepcopy(self.simple)
            r["sources"]["drivers"]["metadata"][field]=value
            with self.assertRaises(ValueError):
                validate_report(r)
        r=deepcopy(self.simple)
        r["sources"]["forecast"]["metadata"]["window"]=1
        with self.assertRaises(ValueError):
            validate_report(r)
    def test_missing_cost_retains_known_revenue_and_unknown_profit(self):
        facts=simple_history()
        facts.tables["sales"].loc[len(facts.tables["sales"])-1,"cogs_amount"]=None
        r=make(facts)
        self.assertIsNone(r["sources"]["analysis"]["company_scope"]["operating_profit"])
        self.assertIn("历史成本缺失",markdown_report(r))
        self.assertIn("全年净收入",markdown_report(r))
        book=inspect_excel(excel_bytes(r))
        self.assertEqual(book["总览点评"]["D14"].value,"不可用")
    def test_missing_refunds_and_fees_are_not_invented(self):
        for key in ("refunds","expenses"):
            facts=simple_history()
            facts.tables[key]=facts.tables[key].iloc[:0]
            facts.metadata["data_availability"][key]=False
            r=make(facts)
            self.assertIsNone(r["sources"]["analysis"]["company_scope"]["operating_profit"])
            self.assertIn("来源未提供",markdown_report(r))
            validate_report(r)
    def test_incomplete_month_has_no_forecast_or_false_actual(self):
        facts=simple_history()
        facts.metadata["coverage"]["complete_end"]="2026-08-31"
        r=make(facts)
        self.assertIsNone(r["sources"]["forecast"])
        self.assertIsNone(r["sources"]["analysis"]["selected_scope"]["net_revenue"])
        self.assertIn("不是已确认完整实际",markdown_report(r))
        self.assertEqual(len(inspect_excel(excel_bytes(r)).sheetnames),10)
    def test_missing_budget_keeps_actual_and_unavailable_comparison(self):
        facts=simple_history()
        for key in ("sales_budget","expense_budget"):
            facts.tables[key]=facts.tables[key].iloc[:0]
            facts.metadata["data_availability"][key]=False
        r=make(facts)
        self.assertEqual(r["sources"]["analysis"]["selected_scope"]["net_revenue"],Decimal(9500))
        self.assertIn("预算缺失",markdown_report(r))
        self.assertIsNone(r["sources"]["analysis"]["selected_budget"]["totals"]["net_revenue"]["budget"])
    def test_filter_keeps_company_fees_and_forecast_scope(self):
        r=make(filters=Filters(products="A"))
        self.assertIsNone(r["sources"]["analysis"]["selected_scope"]["operating_profit"])
        self.assertEqual(r["sources"]["analysis"]["company_scope"]["operating_profit"],Decimal(2800))
        self.assertIsNone(r["sources"]["forecast"]["scenarios"]["base"]["selected_annual"]["operating_profit"])
        self.assertEqual(r["sources"]["forecast"]["scenarios"]["base"]["company_annual"]["operating_profit"],Decimal(33600))
    def test_custom_scenario_preserves_actual_and_changes_future(self):
        r=make(assumptions=Assumptions(quantity_change="-0.03",price_change="0.05"))
        self.assertEqual(r["sources"]["analysis"],self.simple["sources"]["analysis"])
        self.assertEqual(r["sources"]["forecast"]["scenarios"]["custom"]["company_annual"]["net_revenue"],Decimal("114527.25"))
        self.assertNotEqual(r["report_id"],self.simple["report_id"])
    def test_zero_identity_stable_and_inputs_unchanged(self):
        facts=simple_history()
        original=deepcopy(facts)
        before=make(facts)
        after=make(facts,assumptions=Assumptions(price_change="0.00"))
        self.assertEqual(before["report_id"],after["report_id"])
        for name in facts.tables:
            self.assertTrue(facts.tables[name].equals(original.tables[name]))
    def test_excel_has_typed_values_dates_missing_markers_and_no_formulas(self):
        book=inspect_excel(self.payload)
        self.assertEqual(len(book.sheetnames),10)
        self.assertEqual(book["总览点评"]["D9"].value,9500)
        self.assertEqual(book["总览点评"]["D12"].value,.4)
        self.assertEqual(book["总览点评"]["D12"].number_format,"0.00%;(0.00%);\"-\"")
        for sheet in book:
            self.assertFalse(sheet.sheet_view.showGridLines)
        self.assertEqual(book["销售明细"]["D9"].value.year,2026)
    def test_external_text_is_literal_not_excel_formula(self):
        r=deepcopy(self.simple)
        r["metadata"]["data_origin"]="=1+2"
        r["sources"]["details"]["sales"][0]["sale_line_id"]="=HYPERLINK(\"https://example.invalid\")"
        book=inspect_excel(excel_bytes(r))
        self.assertEqual(book["销售明细"]["B9"].data_type,"s")
        self.assertTrue(book["销售明细"]["B9"].value.startswith("="))
    def test_every_spec_numeric_and_date_cell_roundtrips(self):
        # 验证全部工作表的所有区段，而非只看封面数值。
        book=inspect_excel(self.payload)
        count=0
        for spec in workbook_tables(self.simple):
            ws=book[spec["name"]]
            for table in ws.tables.values():
                header=table.ref.split(":")[0]
                header_row=ws[header].row
                block=next(b for b in spec["sections"] if b["headers"]==[ws.cell(header_row,c).value for c in range(2,ws[table.ref.split(":")[1]].column+1)])
                for offset,values in enumerate(block["rows"],1):
                    for column,value in enumerate(values,2):
                        stored=ws.cell(header_row+offset,column).value
                        if isinstance(value,(Decimal,int,float)) and not isinstance(value,bool):
                            self.assertAlmostEqual(float(value),stored,delta=max(.00000001,abs(float(value))*1e-14))
                            count+=1
                        elif isinstance(value,date):
                            self.assertEqual(value,stored.date())
        self.assertGreater(count,500)


if __name__=="__main__":
    unittest.main()
