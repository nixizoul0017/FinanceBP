from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from reporting.excel import excel_bytes,inspect_excel
from test_stage9 import simple_history

def start():
    app=AppTest.from_file(ROOT/"app.py",default_timeout=120)
    app.session_state["page"]="点评与月报"
    app.session_state["display_unit"]="元"  # Fixed reference values use yuan.
    return app.run()


class ReportPageTests(unittest.TestCase):
    def test_generation_button_produces_report_and_downloads(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=start()
            self.assertNotIn("report_generated",app.session_state)
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
        self.assertFalse(app.exception)
        generated=app.session_state["report_generated"]
        self.assertEqual(inspect_excel(generated["excel"])["总览点评"]["D9"].value,9500)
        self.assertEqual(generated["report"]["validation"]["status"],"passed")
        self.assertEqual({m.label:m.value for m in app.metric}["经营利润"],"2,800.00")
    def test_scope_change_hides_stale_report_then_regenerates(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=start()
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
            app.multiselect("product_filter").set_value(["A"]).run()
            apply_filters(app)
            self.assertFalse(app.metric)
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
        self.assertFalse(app.exception)
        self.assertEqual({m.label:m.value for m in app.metric}["经营利润"],"2,800.00")
    def test_custom_changes_report_and_download_keeps_same_snapshot(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=start()
            app.number_input("report_quantity_change").set_value(-3.0)
            app.number_input("report_price_change").set_value(5.0)
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
        self.assertFalse(app.exception)
        r=app.session_state["report_generated"]["report"]
        self.assertEqual(float(r["sources"]["forecast"]["scenarios"]["custom"]["company_annual"]["net_revenue"]),114527.25)
    def test_export_failure_clears_old_report(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=start()
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
            with patch("reporting.excel.excel_bytes",side_effect=OSError("test failure")):
                app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
        self.assertFalse(app.exception)
        self.assertNotIn("report_generated",app.session_state)
        self.assertTrue(app.error)
    def test_source_switch_resets_generated_report_and_assumptions(self):
        with patch("etl.sources.load_facts",return_value=simple_history()):
            app=start()
            app.number_input("report_price_change").set_value(5.0)
            app.button("FormSubmitter:report_generation-生成点评与Excel月报").click().run()
            app.selectbox("source").set_value("小样本核对").run()
        self.assertFalse(app.exception)
        self.assertNotIn("report_generated",app.session_state)
        self.assertEqual(app.number_input("report_price_change").value,0)


if __name__=="__main__":
    unittest.main()
