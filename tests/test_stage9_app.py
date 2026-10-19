from copy import deepcopy
import csv
from decimal import Decimal
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis.forecast import forecast_base
from analysis.forecast_store import save_forecast,saved_forecasts
from etl.sources import load_facts
from test_stage9 import clone,simple_history


def app_start():
    app=AppTest.from_file(ROOT/"app.py",default_timeout=120)
    app.session_state["page"]="预测与情景"
    app.session_state["display_unit"]="元"  # Fixed reference values use yuan.
    return app.run()


class ForecastPageTests(unittest.TestCase):
    def test_annual_cards_timeline_and_cutoff_options(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=app_start()
        self.assertFalse(app.exception)
        values={item.label:item.value for item in app.metric}
        self.assertEqual(values["净收入"],"114,000.00")
        self.assertEqual(values["经营利润"],"33,600.00")
        self.assertNotIn("2026-10",app.selectbox("month").options)
        frame=next(item.value for item in app.dataframe if "数据性质" in item.value)
        self.assertEqual(list(frame["数据性质"]),["实际"]*9+["预测"]*3)

    def test_assumption_changes_reuse_base_and_only_adjust_future(self):
        with patch("etl.sources.load_facts",return_value=simple_history()),patch("analysis.forecast.forecast_base",wraps=forecast_base) as computed:
            app=app_start()
            app.number_input("forecast_quantity_change").set_value(-3.0).run()
            app.number_input("forecast_price_change").set_value(5.0).run()
            app.selectbox("forecast_scenario").set_value("custom").run()
        self.assertFalse(app.exception)
        self.assertEqual(computed.call_count,1)
        values={item.label:item.value for item in app.metric}
        self.assertEqual(values["净收入"],"114,527.25")
        frame=next(item.value for item in app.dataframe if "数据性质" in item.value)
        self.assertEqual(list(frame["净收入（元）"][:9]),["9,500.00"]*9)

    def test_company_forecast_does_not_follow_sales_filter(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=app_start()
            before={item.label:item.value for item in app.metric}
            app.multiselect("product_filter").set_value(["A"]).run()
            apply_filters(app)
        self.assertFalse(app.exception)
        self.assertEqual({item.label:item.value for item in app.metric}["经营利润"],before["经营利润"])

    def test_missing_cost_and_missing_fees_do_not_show_zero_profit(self):
        for source in ("cost","expenses"):
            facts=simple_history()
            if source=="cost":
                facts.tables["sales"].loc[len(facts.tables["sales"])-1,"cogs_amount"]=None
            else:
                facts.tables["expenses"]=facts.tables["expenses"].iloc[:0]
                facts.metadata["data_availability"]["expenses"]=False
            with patch("etl.sources.load_facts",return_value=facts):
                app=app_start()
            self.assertFalse(app.exception)
            values={item.label:item.value for item in app.metric}
            self.assertEqual(values["经营利润"],"—")
            self.assertEqual(values["净收入"],"114,000.00")

    def test_save_and_archive_reuse_frozen_version(self):
        directory=ROOT/"outputs/stage9/test_ui_versions"
        directory.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            with patch("etl.sources.load_facts",return_value=simple_history()),patch("analysis.forecast_store.save_forecast",side_effect=lambda pack:save_forecast(pack,temporary)),patch("analysis.forecast_store.saved_forecasts",side_effect=lambda entity:saved_forecasts(entity,temporary)):
                app=app_start()
                app.button("forecast_save").click().run()
                first=app.session_state["forecast_last_saved"]
                self.assertFalse(app.exception)
                self.assertFalse(first["reused"])
                self.assertIn("forecast_archive",[box.key for box in app.selectbox])
                app.button("forecast_save").click().run()
                self.assertFalse(app.exception)
                self.assertTrue(app.session_state["forecast_last_saved"]["reused"])
                self.assertEqual(app.session_state["forecast_last_saved"]["run_id"],first["run_id"])

    def test_future_download_matches_custom_scenario(self):
        recorded=[]
        original=st.download_button
        def capture(*args,**kwargs):
            if args and args[0]=="下载当前情景未来销售（精确元）":
                recorded.append((args[1],kwargs["file_name"]))
            return original(*args,**kwargs)
        with patch("etl.sources.load_facts",return_value=simple_history()),patch("streamlit.download_button",side_effect=capture):
            app=app_start()
            app.number_input("forecast_quantity_change").set_value(-3.0).run()
            app.number_input("forecast_price_change").set_value(5.0).run()
            app.selectbox("forecast_scenario").set_value("custom").run()
        self.assertFalse(app.exception)
        payload,name=recorded[-1]
        self.assertIn("custom",name)
        self.assertIn("FC9_",name)
        rows=list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
        self.assertEqual(len(rows),3)
        self.assertTrue(all(row["month"]>"2026-09-01" for row in rows))
        self.assertEqual({Decimal(row["sales_revenue"]) for row in rows},{Decimal(10185)})

    def test_source_switch_clears_forecast_cache_and_assumptions(self):
        sample=load_facts(ROOT/"configs/sample_files.json")
        def source_facts(profile,*args):
            return sample if profile["entity_id"]=="XCYX_SAMPLE" else simple_history()
        with patch("etl.sources.load_facts",side_effect=source_facts):
            app=app_start()
            app.number_input("forecast_price_change").set_value(5.0).run()
            app.selectbox("source").set_value("小样本核对").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.number_input("forecast_price_change").value,0.0)
        self.assertEqual(len(app.session_state["forecast_cache"]),1)
        self.assertEqual(next(iter(app.session_state["forecast_cache"].values()))["metadata"]["entity_id"],"XCYX_SAMPLE")
        self.assertEqual({item.label:item.value for item in app.metric}["净收入"],"—")


if __name__=="__main__":
    unittest.main()
