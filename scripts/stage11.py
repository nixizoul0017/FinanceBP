"""Read-only acceptance of the released file pipeline, reports and traceable cases."""
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from decimal import Decimal
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analysis import FinancialEngine, Filters
from analysis.scenario import Assumptions, forecast_pack
from etl.checks import assert_equivalent, verify_reference
from etl.common import read_json, write_json, encode
from etl.sources import load_facts
from reporting.service import build_report, markdown_report
from reporting.excel import excel_bytes, inspect_excel
import json


def run(output=None):
    output = Path(output) if output else ROOT / "outputs/validation"
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    timings, checks = {}, []
    def check(name, condition):
        checks.append({"check": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
    tick = time.perf_counter()
    sample = load_facts(ROOT / "configs/sample_files.json")
    reference = verify_reference(sample, ROOT / "tests/fixtures/sample_sql_reference.json")
    check("sample_matches_independent_sql_reference", reference["passed"])
    original = load_facts(ROOT / "configs/demo_files.json")
    renamed = load_facts(ROOT / "configs/demo_renamed_files.json")
    check("renamed_source_row_equivalence", assert_equivalent(original, renamed)["passed"])
    timings["load_and_validate_two_sources_seconds"] = round(time.perf_counter()-tick, 3)
    engine = FinancialEngine(original)
    monthly = engine.monthly("2024-01", "2026-09").to_dict("records")
    check("33_complete_months", len(monthly) == 33 and all(row["is_complete"] for row in monthly))
    check("33_month_financial_identities", all(row["net_revenue"]-row["net_cost"] == row["gross_margin"] and row["gross_margin"]-row["expenses"] == row["operating_profit"] for row in monthly))
    tick = time.perf_counter()
    report = build_report(engine, "2026-09", data_origin="个人模拟数据")
    timings["analysis_drivers_backtest_forecast_commentary_seconds"] = round(time.perf_counter()-tick, 3)
    # Round-trip comparison includes every exact number, scope and source reference.
    portable = json.loads(json.dumps(report, default=encode, ensure_ascii=False))
    check("complete_report_matches_stage10_snapshot", portable == json.loads((ROOT / "tests/fixtures/report_reference.json").read_text(encoding="utf-8")))
    tick = time.perf_counter()
    payload = excel_bytes(report)
    book = inspect_excel(payload)
    check("ten_sheets_without_formula_errors", len(book.sheetnames) == 10)
    for sheet in book:
        ranges = list(sheet.merged_cells.ranges)
        from openpyxl.worksheet.cell_range import CellRange
        check("no_table_merged_overlap_" + sheet.title, all(CellRange(table.ref).isdisjoint(area) for table in sheet.tables.values() for area in ranges))
    timings["excel_generate_and_readback_seconds"] = round(time.perf_counter()-tick, 3)
    (output / "acceptance_report.xlsx").write_bytes(payload)
    (output / "acceptance_commentary.md").write_text(markdown_report(report), encoding="utf-8")
    write_json(output / "acceptance_report.json", report)
    scenarios = report["sources"]["forecast"]["scenarios"]
    historical_cases = []
    for prior, current in zip(monthly, monthly[12:]):
        if current["net_revenue"] > prior["net_revenue"] and current["gross_margin"] < prior["gross_margin"]:
            historical_cases.append({"comparison": "同比", "prior": prior, "current": current})
    check("real_simulated_month_for_growth_margin_case", bool(historical_cases))
    cases = {"growth_margin": historical_cases[-1], "budget_miss": report["sources"]["drivers"],
             "scenario": {name: row["company_annual"] for name, row in scenarios.items()}}
    write_json(output / "case_evidence.json", cases)
    result = {"passed": True, "date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), "environment": {"python": platform.python_version(), "platform": platform.platform(), "project_root": str(ROOT), "prefix": sys.prefix, "base_prefix": sys.base_prefix},
              "checks": checks, "sample_sql_checks": len(reference["checks"]), "row_counts": original.metadata["row_counts"],
              "report_id": report["report_id"], "forecast_content_id": report["forecast_content_id"],
              "timings": timings, "total_seconds": round(time.perf_counter()-started, 3),
              "physical_other_computer_tested": False, "source_database_writes": False}
    write_json(output / "acceptance_result.json", result)
    print(f"STAGE11_PASS: {len(checks)} checks; {result['total_seconds']}s; {report['report_id']}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    run(parser.parse_args().output)
