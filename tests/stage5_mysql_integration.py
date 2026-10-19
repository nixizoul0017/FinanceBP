"""只运行在自行创建的临时验证MySQL；不接触用户3306数据库。"""
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.checks import assert_equivalent, monthly_company
from etl.common import db_engine, read_json, write_json
from etl.ingest import Importer, initialize_demo
from etl.sources import CONTRACT, DATE_FIELDS, INTEGER_FIELDS, MONEY_FIELDS, load_facts
from etl.validation import SCHEMAS


def run(port):
    started = time.perf_counter()
    temporary = ROOT / ".stage5_validation"
    settings = {"host": "127.0.0.1", "port": port, "user": "root", "database": "finance_bp_demo_validation"}
    admin = db_engine({**settings, "database": None}, "")
    initialize_demo(admin, settings["database"])
    admin.dispose()
    engine = db_engine(settings, "")
    report = {"mysql_port": port, "checks": []}
    def check(name, condition, detail=None):
        report["checks"].append({"check": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(name)
    try:
        with Importer(engine, ROOT / "outputs/stage5/validation_imports") as importer:
            first = importer.import_manifest(ROOT / "data/demo")
            second = importer.import_manifest(ROOT / "data/demo")
            check("full_import_no_rejects", all(row["rejected_rows"] == 0 and row["status"] == "completed" for row in first), first)
            check("same_content_import_skipped", all(row["status"] == "same_file_skipped" and row["accepted_rows"] == 0 for row in second))
            # 另一文件含同业务ID，识别相同和冲突，拒绝新ID重复的费用来源引用。
            product = read_json(ROOT / "data/sample/stage3/products.json")[0]
            existing = importer.catalog.rows["products"][("P001",)]
            duplicate = temporary / "duplicate_products.json"
            write_json(duplicate, [existing, {**existing, "product_name": "冲突名称"}])
            result = importer.import_file("products", duplicate)
            check("different_file_business_id_policy", result["accepted_rows"] == 0 and result["rejected_rows"] == result["skipped_rows"] == 1)
            # 新的好行+坏行：好行进入数据库，坏行输出逐行原因。
            mixed = temporary / "mixed_customers.json"
            write_json(mixed, [{"customer_id": "TEST_OK", "signup_date": "2024-01-01"}, {"customer_id": "TEST_BAD", "signup_date": "2024-02-30"}])
            result = importer.import_file("customers", mixed)
            check("valid_rows_and_rejected_rows_isolated", result["accepted_rows"] == result["rejected_rows"] == 1)
            # 在业务INSERT之后故意失败；回滚业务行，保留失败批次，再原批次重试。
            retry = temporary / "retry_customers.json"
            write_json(retry, [{"customer_id": "TEST_RETRY", "signup_date": "2024-01-01"}])
            try:
                importer.import_file("customers", retry, fail_after_insert=True)
            except RuntimeError:
                pass
            failed = importer.connection.execute(text("SELECT batch_id,status,accepted_rows,attempt_count FROM import_batches WHERE file_name='retry_customers.json'")).mappings().one()
            count = importer.connection.execute(text("SELECT COUNT(*) FROM customers WHERE customer_id='TEST_RETRY'")).scalar_one()
            importer.connection.commit()
            check("transaction_rollback_and_failed_batch", count == 0 and failed["status"] == "failed" and failed["accepted_rows"] == 0)
            retried = importer.import_file("customers", retry)
            check("retry_reuses_batch_increments_attempt", retried["batch_id"] == failed["batch_id"] and retried["attempt"] == 2 and retried["accepted_rows"] == 1)
            # 所有成功批次的数量守恒。
            bad = importer.connection.execute(text("SELECT COUNT(*) FROM import_batches WHERE status IN ('completed','completed_with_errors') AND source_rows<>accepted_rows+rejected_rows+skipped_rows")).scalar_one()
            importer.connection.commit()
            check("batch_row_count_conservation", bad == 0)
        profile = read_json(ROOT / "configs/demo_mysql.example.json")
        profile["source"]["connection"] = settings
        mysql_facts = load_facts(profile, engine)
        file_facts = load_facts(ROOT / "configs/demo_files.json")
        check("mysql_vs_file_full_standard_rows", assert_equivalent(file_facts, mysql_facts)["passed"])
        # 在演示库内创建第二套異名源表，直接保存标准金额；接入时仍只SELECT。
        renamed = read_json(ROOT / "configs/demo_renamed_mysql.example.json")
        renamed["source"]["connection"] = settings
        with engine.begin() as connection:
            for name, frame in file_facts.tables.items():
                mapping = renamed["tables"][name]["mapping"]
                definitions = []
                for field, original in mapping.items():
                    kind = "DATE" if field in DATE_FIELDS else "INT" if field in INTEGER_FIELDS else "DECIMAL(18,4)" if field in {"net_unit_price", "unit_cost"} else "DECIMAL(18,2)" if field in MONEY_FIELDS else "VARCHAR(64)"
                    definitions.append(f"`{original}` {kind}")
                table = renamed["tables"][name]["table"]
                connection.exec_driver_sql(f"CREATE TABLE `{table}` ({','.join(definitions)})")
                rows = [{original: row[field] for field, original in mapping.items()} for row in frame.to_dict("records")]
                insert = text(f"INSERT INTO `{table}` ({','.join('`'+f+'`' for f in mapping.values())}) VALUES ({','.join(':'+f for f in mapping.values())})")
                for offset in range(0, len(rows), 1000):
                    connection.execute(insert, rows[offset:offset+1000])
        renamed_facts = load_facts(renamed, engine)
        check("different_mysql_table_and_column_names_equivalent", assert_equivalent(mysql_facts, renamed_facts)["passed"])
        # 安装已有SQL视图，独立核对全33个月公司汇总。
        script = (ROOT / "sql/stage4/01_analysis_views.sql").read_text(encoding="utf-8-sig").replace("finance_bp_stage3", settings["database"])
        with engine.begin() as connection:
            for statement in script.split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
            sql = pd.read_sql_query(text("SELECT month,net_revenue,net_cost,gross_margin,expense_amount AS expenses,operating_profit FROM vw_monthly_company ORDER BY month"), connection, coerce_float=False)
        python = monthly_company(file_facts).drop(columns="entity_id")
        pd.testing.assert_frame_equal(sql, python, check_dtype=False)
        check("33_month_sql_vs_python_exact", len(sql) == 33)
        check("historical_actual_cutoff", max(file_facts.tables["sales"]["revenue_date"]) <= date(2026,9,30) and max(file_facts.tables["refunds"]["refund_date"]) <= date(2026,9,30))
        report.update(passed=True, row_counts=read_json(ROOT / "data/demo/manifest.json")["row_counts"], seconds=round(time.perf_counter()-started, 3))
        write_json(ROOT / "outputs/stage5/mysql_integration.json", report)
        print(f"MYSQL_INTEGRATION_PASS：{len(report['checks'])}项，{report['seconds']}秒")
    finally:
        engine.dispose()


if __name__ == "__main__":
    run(int(sys.argv[1]))
