from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.service import analysis_pack
from etl.common import read_json, write_json
from etl.sources import load_facts


def run(profile, month, products=None, channels=None, regions=None, version="B2026_V1"):
    started = time.perf_counter()
    engine = FinancialEngine(load_facts(profile))
    filters = Filters(products, channels, regions)
    pack = analysis_pack(engine, month, filters, version)
    output = ROOT / "outputs/stage6"
    write_json(output / "analysis_result.json", pack)
    coverage = engine.metadata["coverage"]
    monthly = engine.monthly(coverage["complete_start"], coverage["complete_end"][:7], filters)
    write_json(output / "monthly_results.json", monthly.to_dict("records"))
    selected, company = pack["selected_scope"], pack["company_scope"]
    print(f"分析月份：{month}；企业：{engine.entity_id}；筛选：{filters.as_dict()}")
    print(f"当前范围净收入{selected['net_revenue']}、净成本{selected['net_cost']}、毛利{selected['gross_margin']}元；状态{selected['actual_status']}")
    print(f"公司全口径费用{company['expenses']}、管理口径经营利润{company['operating_profit']}元。")
    print(f"STAGE6_COMPLETED：结果已保存到outputs/stage6；处理耗时{time.perf_counter()-started:.3f}秒。")
    return pack


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="统一财务计算：文件或MySQL标准数据")
    parser.add_argument("--profile", default="configs/demo_files.json")
    parser.add_argument("--month", default="2026-09")
    parser.add_argument("--products", nargs="+")
    parser.add_argument("--channels", nargs="+")
    parser.add_argument("--regions", nargs="+")
    parser.add_argument("--version", default="B2026_V1")
    args = parser.parse_args()
    try:
        profile = Path(args.profile)
        profile = profile if profile.is_absolute() else ROOT / profile
        run(profile, args.month, args.products, args.channels, args.regions, args.version)
    except Exception as error:
        print("处理已停止：" + (str(error)[:1200] if isinstance(error, ValueError) else type(error).__name__), file=sys.stderr)
        sys.exit(1)
