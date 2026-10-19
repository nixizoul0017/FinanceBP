"""Only for the isolated stage11 MySQL instance, after earlier independent SQL checks."""
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analysis import FinancialEngine
from etl.common import db_engine, read_json, write_json
from etl.sources import load_facts
from reporting.service import build_report
from reporting.excel import excel_bytes, inspect_excel


def run(port):
    started = time.perf_counter()
    profile = read_json(ROOT / "configs/demo_mysql.example.json")
    settings = {"host": "127.0.0.1", "port": port, "user": "root", "database": "finance_bp_demo_stage9"}
    profile["source"]["connection"] = settings
    database = db_engine(settings, "")
    try:
        report = build_report(FinancialEngine(load_facts(profile, database)), "2026-09", data_origin="个人模拟数据")
        files = build_report(FinancialEngine(load_facts(ROOT / "configs/demo_files.json")), "2026-09", data_origin="个人模拟数据")
        checks = []
        def check(name, condition):
            checks.append({"check": name, "passed": bool(condition)})
            if not condition:
                raise AssertionError(name)
        check("all_commentary_facts_and_statements_equivalent", report["commentary"] == files["commentary"])
        for key in ("selected_scope", "company_scope", "selected_budget", "company_budget", "dimensions", "selected_trends", "selected_ytd"):
            check("report_analysis_" + key, report["sources"]["analysis"][key] == files["sources"]["analysis"][key])
        check("all_forecast_scenarios_equivalent", report["sources"]["forecast"]["scenarios"] == files["sources"]["forecast"]["scenarios"])
        check("ten_readable_report_sheets", len(inspect_excel(excel_bytes(report)).sheetnames) == 10)
        write_json(ROOT / "outputs/stage11/mysql_report_validation.json", {"passed": True, "port": port, "checks": checks, "fact_count": report["validation"]["fact_count"], "seconds": round(time.perf_counter()-started, 3), "note": "SQL verification uses separate database; report reads it without writes"})
        print("STAGE11_MYSQL_REPORT_PASS")
    finally:
        database.dispose()


if __name__ == "__main__":
    run(int(sys.argv[1]))
