from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.checks import assert_equivalent, monthly_company, verify_reference
from etl.common import db_engine, read_json, write_json
from etl.ingest import Importer, initialize_demo
from etl.sources import load_facts
from generate_demo_data import generate


def run_demo():
    started = time.perf_counter()
    sample = load_facts(ROOT / "configs/sample_files.json")
    reference = verify_reference(sample, ROOT / "tests/fixtures/sample_sql_reference.json")
    write_json(ROOT / "outputs/stage5/sample_python_vs_sql.json", reference)
    if not reference["passed"]:
        raise ValueError("小样本SQL基准不一致")
    if not (ROOT / "data/demo/manifest.json").exists():
        generate(ROOT / "data/demo", 50000, 20261012)
    first = load_facts(ROOT / "configs/demo_files.json")
    second = load_facts(ROOT / "configs/demo_renamed_files.json")
    equivalence = assert_equivalent(first, second)
    companies = monthly_company(first)
    write_json(ROOT / "outputs/stage5/demo_monthly.json", companies.to_dict("records"))
    report = {"passed": True, "mode": "files", "sample_vs_sql": reference["passed"], "sample_checks": len(reference["checks"]), "full_demo": first.metadata, "renamed_source_equivalence": equivalence, "history_months": len(companies), "seconds": round(time.perf_counter()-started, 3), "next": "可选连接本机MySQL；正式财务函数在阶段6继续"}
    write_json(ROOT / "outputs/stage5/offline_validation.json", report)
    print(f"STAGE5_FILES_COMPLETED：SQL基准{len(reference['checks'])}项一致；完整数据{len(first.tables['sales'])}条确认明细、{len(companies)}个月；第二套来源逐行一致。")


def run_mysql(profile_path, import_demo=False):
    profile = read_json(profile_path)
    settings = profile["source"]["connection"]
    from getpass import getpass
    import os
    password = os.environ.get(settings.get("password_env", "FINANCE_DB_PASSWORD"))
    if password is None:
        password = getpass("MySQL密码（仅本地输入，不保存）: ")
    if import_demo:
        admin_engine = db_engine({**settings, "database": None}, password)
        try:
            print("演示库状态：", initialize_demo(admin_engine, settings["database"]))
        finally:
            admin_engine.dispose()
    engine = db_engine(settings, password)
    try:
        if import_demo:
            with Importer(engine, ROOT / "outputs/stage5/imports") as importer:
                first_run = importer.import_manifest(ROOT / "data/demo")
                second_run = importer.import_manifest(ROOT / "data/demo")
            write_json(ROOT / "outputs/stage5/local_import.json", {"first": first_run, "second": second_run})
        facts = load_facts(profile, engine)
        if profile["entity_id"] == "XCYX_SAMPLE":
            report = verify_reference(facts, ROOT / "tests/fixtures/sample_sql_reference.json")
        else:
            report = assert_equivalent(load_facts(ROOT / "configs/demo_files.json"), facts)
        write_json(ROOT / "outputs/stage5/local_mysql_validation.json", {"profile": Path(profile_path).name, "metadata": facts.metadata, "validation": report})
        if not report["passed"]:
            raise ValueError("MySQL读取结果核对失败")
        print("STAGE5_MYSQL_COMPLETED：数据库读取与文件/SQL基准一致。")
    finally:
        engine.dispose()


def preview_source(profile_path):
    facts = load_facts(profile_path)
    report = {"metadata": facts.metadata, "preview": {name: frame.head(5).to_dict("records") for name, frame in facts.tables.items()}}
    output = ROOT / "outputs/stage5" / ("preview_" + facts.metadata["source_fingerprint"][:12] + ".json")
    write_json(output, report)
    print(f"SOURCE_PREVIEW_COMPLETED：{facts.metadata['row_counts']}；功能条件{facts.metadata['capabilities']}；结果{output.name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="阶段5数据处理入口")
    parser.add_argument("mode", choices=["demo", "mysql-read", "mysql-import", "preview"])
    parser.add_argument("--profile")
    args = parser.parse_args()
    try:
        if args.mode == "demo":
            run_demo()
        elif args.mode == "preview":
            if not args.profile:
                raise ValueError("preview需要--profile指定数据源配置")
            preview_source(args.profile)
        else:
            default = "configs/sample_mysql.example.json" if args.mode == "mysql-read" else "configs/demo_mysql.example.json"
            path = Path(args.profile) if args.profile else ROOT / default
            run_mysql(path, import_demo=args.mode == "mysql-import")
    except Exception as error:
        # 数据库异常的原始消息可能包含凭据/企业数据，不将其直接写进公共日志。
        if isinstance(error, ValueError):
            print("处理已停止：", str(error)[:1500], file=sys.stderr)
        else:
            print(f"处理已停止：{type(error).__name__}。检查本地连接、依赖和批次报告。", file=sys.stderr)
        sys.exit(1)
