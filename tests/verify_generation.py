import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.common import read_json, write_json
from etl.generate import generate_demo
from etl.validation import Catalog, SCHEMAS, process_rows
from etl.ingest import read_rows

directory = ROOT / ".stage5_generation_validation"
if directory.exists():
    raise ValueError("测试目录已存在，停止以免覆盖")
full, _ = generate_demo(directory / "full", 50000, 20261012)
original = read_json(ROOT / "data/demo/manifest.json")
assert full["files"] == original["files"], "同一参数生成的数据哈希不同"
small, _ = generate_demo(directory / "small", 3000, 20261012)
catalog = Catalog()
for table in SCHEMAS:
    accepted, rejected, skipped = process_rows(table, read_rows(directory / "small" / f"{table}.csv"), catalog)
    assert not rejected and skipped == 0, (table, rejected[:3])
    assert len(accepted) == small["row_counts"][table]
write_json(ROOT / "outputs/stage5/generation_validation.json", {"passed": True, "same_seed_file_hashes_identical": True, "small_then_full": [3000, 50000], "small_row_counts": small["row_counts"], "full_row_counts": full["row_counts"]})
print("GENERATION_PASS：3000条试运行全部有效，50000条重新生成的全部来源哈希一致。")
