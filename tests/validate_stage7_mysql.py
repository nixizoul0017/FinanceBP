"""真实MySQL读取和刷新通过页面控件触发，仅连接临时项目数据库。"""
from decimal import Decimal
from pathlib import Path
import sys
import time

from sqlalchemy import text
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.common import db_engine, read_json, write_json
from etl.ingest import Importer, initialize_demo


def metrics(app):
    result = {}
    for value in app.metric:
        result.setdefault(value.label, value.value)
    return result


def run(port):
    started = time.perf_counter()
    settings = {"host": "127.0.0.1", "port": port, "user": "root", "database": "finance_bp_demo_stage7"}
    admin = db_engine({**settings, "database": None}, "")
    initialize_demo(admin, settings["database"])
    admin.dispose()
    database = db_engine(settings, "")
    results = []
    def check(name, condition):
        results.append({"check": name, "passed": bool(condition)})
        assert condition, name
    try:
        with Importer(database, ROOT / "outputs/stage7/validation_imports") as importer:
            imports = importer.import_manifest(ROOT / "data/demo")
        check("temporary_database_import", all(row["rejected_rows"] == 0 for row in imports))
        def row_counts():
            with database.connect() as connection:
                return {table: connection.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one() for table in ("products", "customers", "orders", "order_items", "returns", "expenses", "budget_sales", "budget_expenses", "import_batches")}
        before = row_counts()
        app = AppTest.from_file(ROOT / "app.py", default_timeout=60)
        app.session_state["source"] = "本机MySQL完整数据"
        app.run()
        check("no_implicit_database_read", not app.exception and not app.metric and "engine" not in app.session_state)
        app.number_input("db_port").set_value(port)
        app.text_input("db_name").set_value(settings["database"])
        next(button for button in app.button if button.label == "读取 / 刷新数据库").click().run()
        check("explicit_mysql_read", not app.exception and "engine" in app.session_state)
        values = metrics(app)
        reference = read_json(ROOT / "outputs/stage6/mysql_validation.json")["full_demo_september"]
        expected = {"净收入": "net_revenue", "净成本": "net_cost", "毛利": "gross_margin", "公司费用": "expenses", "经营利润": "operating_profit"}
        check("page_money_same_as_sql", all(values[label] == f"{Decimal(reference[field]):,.2f}" for label, field in expected.items()))
        check("password_widget_cleared", app.text_input("db_password").value == "")
        fingerprint = app.session_state["engine"].metadata["source_fingerprint"]
        app.button("nav_预算比较").click().run()
        check("mysql_budget_page", not app.exception and not app.dataframe[0].value["预算（元）"].eq("—").all())
        # 仅更改此临时库预算，确认页面刷新读入新内容，排除地址不变时缓存陈旧。
        with database.begin() as connection:
            connection.execute(text("UPDATE budget_sales SET budget_net_unit_price=budget_net_unit_price+1 WHERE month='2026-09-01' AND product_id='P001' AND channel_code='C01' AND region_code='R01'"))
        next(button for button in app.button if button.label == "读取 / 刷新数据库").click().run()
        with database.connect() as connection:
            budget = connection.execute(text("SELECT SUM(budget_quantity*budget_net_unit_price-budget_refund_amount) FROM budget_sales WHERE month='2026-09-01' AND budget_version='B2026_V1'")).scalar_one()
        check("refresh_updates_content_fingerprint", app.session_state["engine"].metadata["source_fingerprint"] != fingerprint)
        check("refresh_updates_budget_amount", not app.exception and app.dataframe[0].value.loc[0, "预算（元）"] == f"{budget:,.2f}")
        check("page_does_not_write_source_tables", before == row_counts())
        write_json(ROOT / "outputs/stage7/mysql_validation.json", {"passed": True, "port": port, "checks": results, "seconds": round(time.perf_counter()-started, 3), "source_rows": before})
        print(f"STAGE7_MYSQL_PASS：{len(results)}组页面数据库核对。")
    finally:
        database.dispose()


if __name__ == "__main__":
    run(int(sys.argv[1]))
