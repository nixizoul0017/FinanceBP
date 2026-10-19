import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.common import write_json
from etl.generate import base_profile, generate_demo
from etl.validation import SCHEMAS


def generate(directory, lines, seed):
    manifest, mappings = generate_demo(directory, lines, seed)
    # 非敏感配置使用项目相对路径，复制到其他电脑后仍可运行。
    relative = directory.resolve().relative_to(ROOT).as_posix()
    first = base_profile("XCYX", manifest["coverage"])
    first.update(adapter="ecommerce_v1", source={"kind": "files"}, tables={table: {"files": [f"{relative}/{table}.csv"]} for table in SCHEMAS})
    second = base_profile("XCYX", manifest["coverage"])
    second.update(adapter="mapped_facts_v1", source={"kind": "files"}, tables={name: {"files": [f"{relative}/alternate/biz_{name}.csv"], "mapping": mapping} for name, mapping in mappings.items()})
    write_json(ROOT / "configs/demo_files.json", first)
    write_json(ROOT / "configs/demo_renamed_files.json", second)
    mysql = {**first, "source": {"kind": "mysql", "connection": {"host": "127.0.0.1", "port": 3306, "user": "root", "database": "finance_bp_demo", "password_env": "FINANCE_DB_PASSWORD"}}, "tables": {table: {"table": table} for table in SCHEMAS}}
    write_json(ROOT / "configs/demo_mysql.example.json", mysql)
    mapped_mysql = {**second, "source": mysql["source"], "tables": {name: {"table": f"biz_{name}", "mapping": mapping} for name, mapping in mappings.items()}}
    write_json(ROOT / "configs/demo_renamed_mysql.example.json", mapped_mysql)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成可复现的33个月模拟业务数据")
    parser.add_argument("--lines", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=20261012)
    args = parser.parse_args()
    manifest = generate(ROOT / "data/demo", args.lines, args.seed)
    print(f"模拟数据已生成：{manifest['row_counts']}；种子{args.seed}")
