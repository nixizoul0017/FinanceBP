import csv
import io
from decimal import Decimal
import streamlit as st
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from etl.sources import load_facts
from test_stage8 import clone


def start():
    app=AppTest.from_file(ROOT/"app.py",default_timeout=60)
    app.session_state["source"]="小样本核对"
    app.session_state["page"]="预算比较"
    return app.run()


class DriverPageTests(unittest.TestCase):
    def test_factor_download_identifies_selection_and_matches_exact_amount(self):
        app=start()
        recorded=[]
        original=st.download_button
        def capture(*args,**kwargs):
            if args and args[0]=="下载净收入差异桥明细（精确元）":
                recorded.append((kwargs["data"],kwargs["file_name"]))
            return original(*args,**kwargs)
        with patch("streamlit.download_button",side_effect=capture):
            next(item for item in app.selectbox if item.label=="查看因素明细 · 净收入差异桥").set_value("price").run()
        self.assertFalse(app.exception)
        payload,name=recorded[-1]
        self.assertIn("共同商品均价",name)
        self.assertIn("B2026_V1",name)
        rows=list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertEqual({row["factor"] for row in rows},{"price"})
        self.assertEqual(sum((Decimal(row["amount"]) for row in rows),Decimal(0)),Decimal(-50))

    def test_three_bridge_charts_and_model_values(self):
        app=start()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")),3)
        pack=next(iter(app.session_state["driver_cache"].values()))
        self.assertEqual(str(pack["selected"]["revenue_bridge"]["variance"]),"-140")
        self.assertEqual(str(pack["company_operating_bridge"]["variance"]),"-115")

    def test_factor_selector_shows_only_chosen_price_details(self):
        app=start()
        selector=next(item for item in app.selectbox if item.label=="查看因素明细 · 净收入差异桥")
        selector.set_value("price").run()
        self.assertFalse(app.exception)
        frame=next(item.value for item in app.dataframe if "差异因素" in item.value)
        self.assertEqual(set(frame["差异因素"]),{"共同商品均价"})
        self.assertEqual(set(frame["因素编码"]),{"price"})

    def test_future_month_has_no_false_bridge(self):
        app=start()
        app.selectbox("month").set_value("2026-10").run()
        apply_filters(app)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")),0)
        self.assertTrue(any("暂不能拆解" in item.value for item in app.info))

    def test_product_filters_keep_company_bridge_separate(self):
        app=start()
        original=next(iter(app.session_state["driver_cache"].values()))["company_operating_bridge"]
        app.multiselect("product_filter").set_value(["P001"]).run()
        apply_filters(app)
        self.assertFalse(app.exception)
        newest=list(app.session_state["driver_cache"].values())[-1]
        self.assertEqual(newest["company_operating_bridge"],original)
        app.selectbox("source").set_value("异名模拟数据").run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.session_state["driver_cache"]),1)

    def test_missing_cost_keeps_revenue_chart_and_hides_margin(self):
        facts=clone(load_facts(ROOT/"configs/sample_files.json"))
        facts.tables["sales"].loc[0,"cogs_amount"]=None
        with patch("etl.sources.load_facts",return_value=facts):
            app=start()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get("plotly_chart")),1)
        self.assertTrue(any("实际缺历史成本" in item.value for item in app.info))


if __name__=="__main__":
    unittest.main()
