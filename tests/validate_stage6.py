"""阶段6：手算/SQL基准、全历史、两套来源与真实MySQL核对。"""
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
import time

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.comparison import company_budget_comparison, trend_comparison, year_to_date
from etl.common import ZERO, db_engine, read_json, write_json
from etl.ingest import Importer, initialize_demo
from etl.sources import load_facts


def check_rows(expected, actual, key_fields, value_fields):
    oracle = {tuple(row[field] for field in key_fields): row for row in expected}
    result = {tuple(row[field] for field in key_fields): row for row in actual}
    assert oracle.keys() == result.keys(), "分组键不一致"
    for key, row in oracle.items():
        for field in value_fields:
            assert row[field] == result[key][field], (key, field, row[field], result[key][field])


def run(mysql_port=None):
    started = time.perf_counter()
    engine = FinancialEngine(load_facts(ROOT / "configs/demo_files.json"))
    sample = FinancialEngine(load_facts(ROOT / "configs/sample_files.json"))
    renamed = FinancialEngine(load_facts(ROOT / "configs/demo_renamed_files.json"))
    report = {"checks": [], "mode": "files_and_mysql" if mysql_port else "files"}

    def check(name, condition, detail=None):
        report["checks"].append({"check": name, "passed": bool(condition), "detail": detail})
        assert condition, name

    baseline = read_json(ROOT / "tests/fixtures/sample_sql_reference.json")
    sample_result = sample.summary("2026-09")
    check("sample_sql_company_exact", all(sample_result[field] == value for field, value in baseline["company"].items()))
    budgets = company_budget_comparison(sample, "2026-09")
    check("sample_sql_budget_exact", all(budgets["sales"]["totals"][field]["budget"] == baseline["sales_budget"][field] for field in ("net_revenue", "net_cost", "gross_margin")) and budgets["expenses"]["total"]["budget"] == baseline["expenses_budget"])
    monthly = engine.monthly("2024-01", "2026-09").to_dict("records")
    oracle = read_json(ROOT / "tests/fixtures/monthly_reference.json")
    for row in oracle:
        row["month"] = date.fromisoformat(row["month"])
        for field in ("net_revenue", "net_cost", "gross_margin", "expenses", "operating_profit"):
            row[field] = Decimal(row[field])
    money = ("net_revenue", "net_cost", "gross_margin", "expenses", "operating_profit")
    check_rows(oracle, monthly, ["month"], money)
    check("33_month_prior_sql_reference_exact", len(monthly) == 33)
    check("financial_identities_all_months", all(row["net_revenue"]-row["net_cost"] == row["gross_margin"] and row["gross_margin"]-row["expenses"] == row["operating_profit"] for row in monthly))
    other = renamed.monthly("2024-01", "2026-09").to_dict("records")
    check_rows(monthly, other, ["month"], [*money, "confirmed_orders", "confirmed_lines", "gross_margin_rate"])
    selected = Filters(products=("P001", "P002"), channels="C02", regions="R02")
    first, second = engine.summary("2026-01", "2026-09", selected), renamed.summary("2026-01", "2026-09", selected)
    check("renamed_source_same_metrics_and_filters", all(first[field] == second[field] for field in (*money, "confirmed_orders", "gross_margin_rate")))
    ytd = year_to_date(engine, "2026-09")["current"]
    check("ytd_exact_and_no_future_actual", all(ytd[field] == sum((row[field] for row in monthly if row["month"].year == 2026), ZERO) for field in money) and engine.summary("2026-10")["net_revenue"] is None)
    check("dimension_totals_equal_company", all(sum(engine.dimensions("2026-09", by=field)["net_revenue"], ZERO) == engine.summary("2026-09")["net_revenue"] for field in ("product_id", "channel_id", "region_id")))
    if mysql_port is not None:
        settings = {"host": "127.0.0.1", "port": mysql_port, "user": "root", "database": "finance_bp_demo_stage6"}
        admin = db_engine({**settings, "database": None}, "")
        initialize_demo(admin, settings["database"])
        admin.dispose()
        database = db_engine(settings, "")
        try:
            with Importer(database, ROOT / "outputs/stage6/validation_imports") as importer:
                imported = importer.import_manifest(ROOT / "data/demo")
            check("mysql_full_import_no_reject", all(row["rejected_rows"] == 0 for row in imported))
            script = (ROOT / "sql/stage4/01_analysis_views.sql").read_text(encoding="utf-8-sig").replace("finance_bp_stage3", settings["database"])
            with database.begin() as connection:
                for statement in script.split(";"):
                    if statement.strip():
                        connection.exec_driver_sql(statement)
            profile = read_json(ROOT / "configs/demo_mysql.example.json")
            profile["source"]["connection"] = settings
            mysql_engine = FinancialEngine(load_facts(profile, database))
            check_rows(monthly, mysql_engine.monthly("2024-01", "2026-09").to_dict("records"), ["month"], [*money, "gross_margin_rate", "confirmed_orders"])
            check("mysql_standard_snapshot_same_financial_results", True)
            with database.connect() as connection:
                sql_company = list(connection.execute(text("SELECT month,sales_quantity,sales_revenue,refund_amount,net_revenue,net_cost,gross_margin,expense_amount AS expenses,operating_profit,confirmed_orders FROM vw_monthly_company ORDER BY month")).mappings())
                check_rows(sql_company, monthly, ["month"], [*money, "sales_quantity", "sales_revenue", "refund_amount", "confirmed_orders"])
                check("fresh_sql_33_month_company_exact", len(sql_company) == 33)
                temporal = connection.execute(text("""SELECT month,net_revenue,
                    LAG(net_revenue) OVER(ORDER BY month) AS previous_month,
                    LAG(net_revenue,12) OVER(ORDER BY month) AS previous_year,
                    SUM(net_revenue) OVER(PARTITION BY YEAR(month) ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ytd
                    FROM vw_calendar_company WHERE month BETWEEN '2024-01-01' AND '2026-09-01' ORDER BY month""")).mappings()
                for row in temporal:
                    comparison = trend_comparison(engine, row["month"])
                    assert comparison["mom"]["net_revenue"]["base"] == row["previous_month"]
                    assert comparison["yoy"]["net_revenue"]["base"] == row["previous_year"]
                    assert year_to_date(engine, row["month"])["current"]["net_revenue"] == row["ytd"]
                check("sql_calendar_lag_and_ytd_exact", True)
                dimension_sql = list(connection.execute(text("""SELECT product_id,channel_code AS channel_id,region_code AS region_id,
                    SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin
                    FROM vw_monthly_financials WHERE month BETWEEN '2024-01-01' AND '2026-09-01'
                    GROUP BY product_id,channel_code,region_code""")).mappings())
                check_rows(dimension_sql, engine.dimensions("2024-01", "2026-09", by=("product_id", "channel_id", "region_id")).to_dict("records"), ["product_id", "channel_id", "region_id"], ["net_revenue", "net_cost", "gross_margin"])
                check("sql_joint_dimension_totals_exact", len(dimension_sql) == 240)
                for start in (date(2026,9,1), date(2026,1,1)):
                    sql = connection.execute(text("""SELECT SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin
                        FROM vw_monthly_financials WHERE month BETWEEN :start AND '2026-09-01'
                        AND product_id IN ('P001','P002') AND channel_code='C02' AND region_code='R02'"""), {"start": start}).mappings().one()
                    selected_result = engine.summary(start, "2026-09", selected)
                    assert all(sql[field] == selected_result[field] for field in ("net_revenue", "net_cost", "gross_margin"))
                    assert selected_result["expenses"] is selected_result["operating_profit"] is None
                check("sql_selected_month_and_period_exact", True)
                sql_sales_budget = connection.execute(text("""SELECT month,SUM(budget_net_revenue) AS net_revenue,SUM(budget_net_cost) AS net_cost,
                    SUM(budget_gross_margin) AS gross_margin FROM vw_budget_sales_metrics WHERE budget_version='B2026_V1' GROUP BY month""")).mappings()
                sql_fees_budget = {row["month"]: row["amount"] for row in connection.execute(text("SELECT month,SUM(budget_amount) AS amount FROM budget_expenses WHERE budget_version='B2026_V1' GROUP BY month")).mappings()}
                for row in sql_sales_budget:
                    result = company_budget_comparison(engine, row["month"])
                    assert all(result["sales"]["totals"][field]["budget"] == row[field] for field in ("net_revenue", "net_cost", "gross_margin"))
                    assert result["expenses"]["total"]["budget"] == sql_fees_budget[row["month"]]
                    assert result["operating_profit"]["budget"] == row["gross_margin"]-sql_fees_budget[row["month"]]
                    if row["month"] > date(2026,9,1):
                        assert result["operating_profit"]["actual"] is None
                check("sql_12_month_budget_and_future_unknown_exact", True)
        finally:
            database.dispose()
    report.update(passed=True, seconds=round(time.perf_counter()-started, 3), history_months=33, sample_metrics={field: sample_result[field] for field in money}, full_demo_september={field: engine.summary("2026-09")[field] for field in money})
    write_json(ROOT / "outputs/stage6" / ("mysql_validation.json" if mysql_port else "file_validation.json"), report)
    print(f"STAGE6_VALIDATION_PASS：{len(report['checks'])}组核对，{report['seconds']}秒。")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else None)
