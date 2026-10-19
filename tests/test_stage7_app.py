"""阶段7网页集成验收：真实财务显示、筛选、来源隔离及下载。

使用Streamlit AppTest运行真正的app.py；只在缺来源与数据库失败场景
替换读取边界，财务引擎、控件和导出仍使用正式实现。
"""
from copy import deepcopy
import csv
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.sources import Facts, load_facts


def clone(facts):
    return Facts({name: frame.copy(deep=True) for name, frame in facts.tables.items()},
                 deepcopy(facts.metadata))


def metrics(app):
    """同名本年累计指标排在月度指标后，优先取本月卡片。"""
    result = {}
    for item in app.metric:
        result.setdefault(item.label, item.value)
    return result


def displayed_text(app):
    return "\n".join(str(item.value) for kind in
                     ("markdown", "caption", "info", "warning", "error")
                     for item in getattr(app, kind))


class DashboardAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = load_facts(ROOT / "configs/sample_files.json")

    def start(self, source="小样本核对"):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=60)
        app.session_state["source"] = source
        app.session_state["display_unit"] = "元"  # Reference amounts are denominated in yuan.
        app.run()
        self.assert_clean(app)
        return app

    def assert_clean(self, app):
        self.assertFalse(app.exception, [item.message for item in app.exception])

    def page(self, app, name):
        app.button("nav_" + name).click().run()
        self.assert_clean(app)

    def test_sample_company_cards_match_verified_sql(self):
        app = self.start()
        values = metrics(app)
        self.assertEqual(values["净收入"], "3,240.00")
        self.assertEqual(values["净成本"], "2,055.00")
        self.assertEqual(values["毛利"], "1,185.00")
        self.assertEqual(values["毛利率"], "36.57%")
        self.assertEqual(values["公司费用"], "400.00")
        self.assertEqual(values["经营利润"], "785.00")
        self.assertEqual(app.selectbox("month").value, "2026-09")
        self.assertIn("本年1月至当前月", displayed_text(app))
        self.assertEqual(app.metric[-3].value, "—")

    def test_filter_updates_sales_and_retains_company_profit(self):
        app = self.start()
        app.multiselect("product_filter").set_value(["P001"])
        app.multiselect("channel_filter").set_value(["C02"])
        app.multiselect("region_filter").set_value(["R02"])
        app.run()
        apply_filters(app)
        self.assert_clean(app)
        values = metrics(app)
        self.assertEqual((values["净收入"], values["净成本"], values["毛利"]),
                         ("550.00", "350.00", "200.00"))
        self.assertEqual((values["公司费用"], values["经营利润"]),
                         ("400.00", "785.00"))
        self.assertIn("公司全口径", displayed_text(app))
        self.assertIn("不随上方商品", displayed_text(app))

    def test_known_empty_filter_is_zero_with_unknown_rate(self):
        app = self.start()
        app.multiselect("product_filter").set_value(["P002"])
        app.multiselect("channel_filter").set_value(["C01"])
        app.run()
        apply_filters(app)
        self.assert_clean(app)
        values = metrics(app)
        self.assertEqual(values["净收入"], "0.00")
        self.assertEqual(values["毛利"], "0.00")
        self.assertEqual(values["毛利率"], "—")
        self.assertIn("没有交易", displayed_text(app))

    def test_all_pages_render_and_unknown_october_stays_unknown(self):
        app = self.start()
        for page in ("月度趋势", "维度分析", "预算比较", "数据与下载", "经营总览"):
            self.page(app, page)
        app.selectbox("month").select("2026-10").run()
        apply_filters(app)
        self.assert_clean(app)
        self.assertEqual(metrics(app)["净收入"], "—")
        self.assertEqual(metrics(app)["经营利润"], "—")
        self.assertIn("没有完整实际数据", displayed_text(app))
        self.page(app, "数据与下载")
        refund = next(item.value for item in app.dataframe if "退款ID" in item.value.columns)
        self.assertEqual(len(refund), 1)
        self.assertEqual(refund.loc[0, "退款金额（元）"], "110")
        self.assertFalse(bool(refund.loc[0, "期间完整"]))
        self.assertIn("不代表该月完整实际", displayed_text(app))

    def test_future_month_budget_does_not_invent_actual(self):
        app = self.start("完整模拟数据")
        app.selectbox("month").select("2026-12").run()
        apply_filters(app)
        self.assert_clean(app)
        self.assertEqual(metrics(app)["净收入"], "—")
        self.assertIn("预算或实际数据不足，完成率未知", displayed_text(app))
        self.page(app, "预算比较")
        sales = app.dataframe[0].value
        self.assertTrue(sales["实际（元）"].eq("—").all())
        self.assertTrue(sales["完成率"].eq("—").all())
        self.assertFalse(sales["预算（元）"].eq("—").all())

    def test_source_switch_resets_month_filters_and_identity(self):
        app = self.start("完整模拟数据")
        original = app.session_state["engine"].entity_id
        app.selectbox("month").select("2024-01")
        app.multiselect("product_filter").set_value(["P020"])
        app.run()
        apply_filters(app)
        self.assert_clean(app)
        self.page(app, "月度趋势")
        app.selectbox("source").select("小样本核对").run()
        self.assert_clean(app)
        self.assertNotEqual(app.session_state["engine"].entity_id, original)
        self.assertEqual(app.session_state["engine"].entity_id, "XCYX_SAMPLE")
        self.assertEqual(app.selectbox("month").value, "2026-09")
        self.assertEqual(app.multiselect("product_filter").value, [])
        self.assertEqual(app.selectbox("trend_start").value, "2026-09")
        self.assertTrue(all(key[0] == "XCYX_SAMPLE" for key in app.session_state["pack_cache"]))

    def test_missing_refunds_and_expenses_do_not_become_zero(self):
        facts = clone(self.sample)
        for name in ("refunds", "expenses"):
            facts.tables[name] = facts.tables[name].iloc[:0]
            facts.metadata["data_availability"][name] = False
        with patch("etl.sources.load_facts", return_value=facts):
            app = self.start()
            values = metrics(app)
            self.assertEqual(values["净收入"], "—")
            self.assertEqual(values["公司费用"], "—")
            self.assertEqual(values["经营利润"], "—")
            self.assertIn("尚未提供退款来源", displayed_text(app))
            self.assertIn("尚未提供费用来源", displayed_text(app))

    def test_missing_cost_only_blocks_affected_scope(self):
        facts = clone(self.sample)
        facts.tables["sales"].loc[facts.tables["sales"]["product_id"].eq("P001"), "cogs_amount"] = None
        facts.metadata["capabilities"]["margin"] = False
        with patch("etl.sources.load_facts", return_value=facts):
            app = self.start()
            self.assertEqual(metrics(app)["净收入"], "3,240.00")
            self.assertEqual(metrics(app)["毛利"], "—")
            self.assertEqual(metrics(app)["经营利润"], "—")
            app.multiselect("product_filter").set_value(["P002"]).run()
            apply_filters(app)
            self.assert_clean(app)
            self.assertEqual(metrics(app)["毛利"], "30.00")

    def test_no_budget_source_and_version_selection_remain_distinct(self):
        facts = clone(self.sample)
        for name in ("sales_budget", "expense_budget"):
            facts.tables[name] = facts.tables[name].iloc[:0]
            facts.metadata["data_availability"][name] = False
        with patch("etl.sources.load_facts", return_value=facts):
            app = self.start()
            self.assertEqual(app.selectbox("budget_version").value, "无预算数据")
            self.assertEqual(metrics(app)["净收入"], "3,240.00")
            self.assertIn("预算或实际数据不足，完成率未知", displayed_text(app))
            self.page(app, "预算比较")
            self.assertTrue(app.dataframe[0].value["预算（元）"].eq("—").all())

    def test_budget_versions_are_not_added_together(self):
        import pandas as pd
        facts = clone(self.sample)
        for name in ("sales_budget", "expense_budget"):
            extra = facts.tables[name].copy(deep=True)
            extra["budget_version"] = "B2026_V2"
            if name == "sales_budget":
                for field in ("quantity", "refund_amount", "cost_reversal_amount"):
                    extra[field] *= 2
            else:
                extra["amount"] *= 2
            facts.tables[name] = pd.concat([facts.tables[name], extra], ignore_index=True)
        with patch("etl.sources.load_facts", return_value=facts):
            app = self.start()
            self.page(app, "预算比较")
            self.assertEqual(app.dataframe[0].value.loc[0, "预算（元）"], "3,380.00")
            app.selectbox("budget_version").select("B2026_V2").run()
            apply_filters(app)
            self.assert_clean(app)
            self.assertEqual(app.dataframe[0].value.loc[0, "预算（元）"], "6,760.00")
            self.assertEqual(app.dataframe[0].value.loc[0, "实际（元）"], "3,240.00")

    def test_downloads_follow_filter_but_company_expenses_stay_company(self):
        captured = {}
        original = st.download_button

        def capture(*args, **kwargs):
            captured[kwargs.get("key")] = {"data": kwargs.get("data", args[1] if len(args) > 1 else None),
                                           "file_name": kwargs["file_name"]}
            return original(*args, **kwargs)

        with patch("streamlit.download_button", side_effect=capture):
            app = self.start()
            app.multiselect("product_filter").set_value(["P001"])
            app.multiselect("channel_filter").set_value(["C02"])
            app.multiselect("region_filter").set_value(["R02"])
            app.run()
            apply_filters(app)
            self.assert_clean(app)
            pack = json.loads(captured["download_metrics"]["data"])
            self.assertEqual(pack["selected_scope"]["net_revenue"], "550")
            self.assertEqual(pack["metadata"]["entity_id"], "XCYX_SAMPLE")
            self.page(app, "数据与下载")
            sales_file = captured["download_销售明细"]
            sales = list(csv.DictReader(io.StringIO(sales_file["data"].decode("utf-8-sig"))))
            self.assertEqual(len(sales), 1)
            self.assertEqual(sales[0]["sales_amount_before_refund"], "550")
            self.assertEqual((sales[0]["product_id"], sales[0]["channel_id"], sales[0]["region_id"]), ("P001", "C02", "R02"))
            self.assertEqual(sales[0]["entity_id"], "XCYX_SAMPLE")
            fees_file = captured["download_公司费用明细"]
            fees = list(csv.DictReader(io.StringIO(fees_file["data"].decode("utf-8-sig"))))
            self.assertEqual(sum((Decimal(row["amount"]) for row in fees), Decimal(0)), Decimal("400"))
            self.assertIn("company", fees_file["file_name"])
            self.assertNotIn("products-P001", fees_file["file_name"])
            self.assertEqual(len(app.dataframe[0].value), len(sales))

    def test_mysql_requires_explicit_load_and_failure_clears_old_data(self):
        app = self.start()
        app.selectbox("source").select("本机MySQL小样本").run()
        self.assert_clean(app)
        self.assertFalse(app.metric)
        self.assertNotIn("engine", app.session_state)
        self.assertIn("读取 / 刷新数据库", displayed_text(app))
        fake_engine = MagicMock()
        with patch("etl.common.db_engine", return_value=fake_engine) as create_engine, \
             patch("etl.sources.load_facts", side_effect=RuntimeError("secret=password_raw_example")):
            app.text_input("db_password").set_value("test_password")
            next(button for button in app.button if button.label == "读取 / 刷新数据库").click().run()
        self.assert_clean(app)
        create_engine.assert_called_once()
        self.assertEqual(create_engine.call_args.kwargs["password"], "test_password")
        fake_engine.dispose.assert_called_once()
        self.assertNotIn("engine", app.session_state)
        self.assertFalse(app.metric)
        self.assertTrue(app.error)
        self.assertNotIn("password_raw_example", displayed_text(app))
        self.assertEqual(app.text_input("db_password").value, "")

    def test_successful_mysql_read_removes_password_and_uses_snapshot(self):
        fake_engine = MagicMock()
        app = self.start("本机MySQL小样本")
        with patch("etl.common.db_engine", return_value=fake_engine) as create_engine, \
             patch("etl.sources.load_facts", return_value=clone(self.sample)) as read:
            app.text_input("db_password").set_value("one_read_password")
            next(button for button in app.button if button.label == "读取 / 刷新数据库").click().run()
            self.assert_clean(app)
            self.assertEqual(metrics(app)["净收入"], "3,240.00")
            self.assertEqual(app.text_input("db_password").value, "")
            self.page(app, "维度分析")
            create_engine.assert_called_once()
            read.assert_called_once()
            fake_engine.dispose.assert_called_once()
            self.assertNotIn("one_read_password", displayed_text(app))


if __name__ == "__main__":
    unittest.main()
