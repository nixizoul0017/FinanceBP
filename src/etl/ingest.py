from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from .common import ROOT, digest, read_json, write_json
from .validation import Catalog, KEYS, SCHEMAS, parse_row, process_rows


def read_rows(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        rows = read_json(path)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("expected_list_of_records")
        return rows
    if path.suffix.lower() == ".csv":
        # 先读取文本，防止商品编码前导零、空字符串或金额被提前转成浮点。
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig").to_dict("records")
    raise ValueError("unsupported_file_format")


def load_catalog(connection):
    records = {}
    for table in SCHEMAS:
        columns = ",".join(f"`{name}`" for name in SCHEMAS[table])
        records[table] = [dict(row) for row in connection.execute(text(f"SELECT {columns} FROM `{table}`")).mappings()]
    return Catalog(records)


def initialize_demo(engine, database):
    """仅创建项目演示库；不允许覆盖已有或企业业务数据库。"""
    if not re.fullmatch(r"finance_bp_demo(?:_[a-z0-9]+)*", database):
        raise ValueError("目标库必须为finance_bp_demo或finance_bp_demo_英文数字后缀")
    if engine.url.database is not None:
        raise ValueError("初始化连接不能预先指定数据库")
    with engine.connect() as connection:
        exists = connection.execute(text("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=:db"), {"db": database}).scalar_one()
        if exists:
            marker = connection.execute(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=:db AND table_name='stage5_project_metadata'"), {"db": database}).scalar_one()
            if not marker:
                raise ValueError("已有同名库不含本项目标记，已停止；请选择另一个演示库名称")
            value = connection.exec_driver_sql(f"SELECT project_id FROM `{database}`.stage5_project_metadata").scalar_one()
            if value != "finance_bp_stage5_v1":
                raise ValueError("已有库项目标记不匹配")
            return "existing_project_database"
        connection.exec_driver_sql(f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs")
        connection.exec_driver_sql(f"USE `{database}`")
        connection.exec_driver_sql("SET SESSION time_zone='+08:00'")
        script = (ROOT / "sql/01_create_tables.sql").read_text(encoding="utf-8-sig").replace("finance_bp_stage3", database)
        for statement in script.split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement)
        connection.exec_driver_sql("CREATE TABLE stage5_project_metadata (project_id VARCHAR(64) PRIMARY KEY, created_at DATETIME NOT NULL)")
        connection.exec_driver_sql("INSERT INTO stage5_project_metadata VALUES ('finance_bp_stage5_v1',NOW())")
        dates, day = [], date(2024, 1, 1)
        while day <= date(2026, 12, 31):
            dates.append({"id": int(day.strftime("%Y%m%d")), "day": day, "year": day.year, "month": day.month, "start": day.replace(day=1), "quarter": (day.month-1)//3+1})
            day += timedelta(days=1)
        connection.execute(text("INSERT INTO dim_date VALUES (:id,:day,:year,:month,:start,:quarter)"), dates)
        connection.commit()
    return "created_project_database"


class Importer:
    def __init__(self, engine, report_dir):
        self.engine = engine
        self.report_dir = Path(report_dir)
        self.connection = None
        self.catalog = None
        self.lock_name = "finance_bp_stage5:" + str(engine.url.database)

    def __enter__(self):
        if not re.fullmatch(r"finance_bp_demo(?:_[a-z0-9]+)*", self.engine.url.database or ""):
            raise ValueError("导入只允许项目finance_bp_demo演示库")
        self.connection = self.engine.connect()
        try:
            marker = self.connection.execute(text("SELECT project_id FROM stage5_project_metadata")).scalar_one()
            if marker != "finance_bp_stage5_v1":
                raise ValueError("项目标记不匹配")
            if self.connection.execute(text("SELECT GET_LOCK(:name,5)"), {"name": self.lock_name}).scalar_one() != 1:
                raise ValueError("另一个项目导入任务正在运行")
            self.catalog = load_catalog(self.connection)
            self.connection.commit()
            return self
        except Exception:
            self.connection.close()
            raise

    def __exit__(self, *args):
        try:
            self.connection.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": self.lock_name})
            self.connection.commit()
        finally:
            self.connection.close()

    def import_file(self, table, path, fail_after_insert=False):
        if table not in SCHEMAS:
            raise ValueError("unknown_dataset_type")
        path, started = Path(path), time.perf_counter()
        fingerprint = digest(path)
        with self.connection.begin():
            previous = self.connection.execute(text("SELECT * FROM import_batches WHERE dataset_type=:table AND file_hash=:hash FOR UPDATE"), {"table": table, "hash": fingerprint}).mappings().first()
            if previous and previous["status"] in {"completed", "completed_with_errors"}:
                return {"table": table, "file": path.name, "batch_id": previous["batch_id"], "status": "same_file_skipped", "source_rows": previous["source_rows"], "accepted_rows": 0, "rejected_rows": 0, "skipped_rows": previous["source_rows"], "previous_rejected_rows": previous["rejected_rows"]}
            if previous:
                batch_id = previous["batch_id"]
                attempt = previous["attempt_count"] + 1
                self.connection.execute(text("UPDATE import_batches SET status='running',attempt_count=:attempt,started_at=NOW(),finished_at=NULL,error_summary=NULL,accepted_rows=0,rejected_rows=0,skipped_rows=0 WHERE batch_id=:id"), {"attempt": attempt, "id": batch_id})
            else:
                result = self.connection.execute(text("INSERT INTO import_batches(dataset_type,file_name,file_hash,started_at,status,attempt_count) VALUES (:table,:name,:hash,NOW(),'running',1)"), {"table": table, "name": path.name[:255], "hash": fingerprint})
                batch_id, attempt = result.lastrowid, 1
        count = 0
        try:
            rows = read_rows(path)
            if digest(path) != fingerprint:
                raise ValueError("source_file_changed_during_read")
            count = len(rows)
            with self.connection.begin():
                accepted, rejected, skipped = process_rows(table, rows, self.catalog)
                if accepted:
                    columns = list(SCHEMAS[table]) + ["import_batch_id"]
                    statement = text(f"INSERT INTO `{table}` ({','.join('`'+c+'`' for c in columns)}) VALUES ({','.join(':'+c for c in columns)})")
                    payload = [dict(row, import_batch_id=batch_id) for row in accepted]
                    for offset in range(0, len(payload), 1000):
                        self.connection.execute(statement, payload[offset:offset+1000])
                if fail_after_insert:
                    raise RuntimeError("intentional_transaction_failure")
                status = "completed_with_errors" if rejected else "completed"
                report = {"table": table, "file": path.name, "file_hash": fingerprint, "batch_id": batch_id, "attempt": attempt, "status": status, "source_rows": count, "accepted_rows": len(accepted), "rejected_rows": len(rejected), "skipped_rows": skipped, "seconds": round(time.perf_counter()-started, 3), "rejected": rejected}
                write_json(self.report_dir / f"batch_{batch_id}_attempt_{attempt}.json", report)
                self.connection.execute(text("UPDATE import_batches SET finished_at=NOW(),status=:status,source_rows=:source,accepted_rows=:accepted,rejected_rows=:rejected,skipped_rows=:skipped,error_summary=:error WHERE batch_id=:id"), {"id": batch_id, "status": status, "source": count, "accepted": len(accepted), "rejected": len(rejected), "skipped": skipped, "error": f"{len(rejected)} row(s) rejected; see local batch report" if rejected else None})
            return {field: value for field, value in report.items() if field != "rejected"}
        except Exception as error:
            # 失败时撤销业务行，再用独立事务记录失败；重新载入索引，避免残留内存状态。
            reason = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
            with self.connection.begin():
                self.connection.execute(text("UPDATE import_batches SET finished_at=NOW(),status='failed',source_rows=:count,accepted_rows=0,rejected_rows=0,skipped_rows=0,error_summary=:error WHERE batch_id=:id"), {"id": batch_id, "count": count, "error": reason[:500]})
            self.catalog = load_catalog(self.connection)
            self.connection.commit()
            write_json(self.report_dir / f"batch_{batch_id}_attempt_{attempt}_failed.json", {"table": table, "batch_id": batch_id, "attempt": attempt, "status": "failed", "reason": reason, "accepted_rows": 0})
            raise

    def import_manifest(self, directory):
        directory = Path(directory)
        manifest = read_json(directory / "manifest.json")
        results = []
        for table in SCHEMAS:
            for entry in manifest["files"][table]:
                path = directory / entry["file"]
                if not path.resolve().is_relative_to(directory.resolve()):
                    raise ValueError("manifest_file_outside_dataset_directory")
                if digest(path) != entry["sha256"]:
                    raise ValueError(f"manifest_hash_mismatch:{entry['file']}")
                results.append(self.import_file(table, path))
        return results
