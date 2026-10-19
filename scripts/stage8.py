"""阶段8文件/MySQL来源的差异拆解与调查案例输出。"""
import argparse
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analysis import FinancialEngine, Filters
from analysis.variance import variance_pack
from dashboard.view_model import csv_bytes, money_text, safe_export_name
from etl.common import write_json
from etl.sources import load_facts
import pandas as pd


def case_text(result):
    selected = result["selected"]
    revenue = selected["revenue_bridge"]
    lines = ["# 预算差异调查案例", "", f"企业：{result['metadata']['entity_id']}；月份：{selected['month']:%Y-%m}；固定预算版本：{selected['version']}。",
             f"销售范围：{selected['filters']}；金额人民币不含税元；公司费用与利润采用公司全口径。", ""]
    if revenue["status"] != "complete":
        lines += [f"收入桥暂不可用：{revenue['reason']}。先补齐覆盖范围、来源或预算，不用部分数据代替完整实际。"]
    else:
        lines += [f"净收入实际{money_text(revenue['actual'])}元，预算{money_text(revenue['budget'])}元，实际减预算差额{money_text(revenue['variance'])}元。", "", "金额组成："]
        lines += [f"- {row['factor_label']}：{money_text(row['amount'])}元。" for row in revenue["components"]]
        display_total = sum((Decimal(money_text(row["amount"]).replace(",", "")) for row in revenue["components"]), Decimal(0))
        display_difference = Decimal(money_text(revenue["variance"]).replace(",", ""))
        if display_total != display_difference:
            lines += [f"- 显示舍入尾差（非经营因素）：{money_text(display_difference-display_total)}元。"]
        ranking = selected["rankings"]["product_id"]
        adverse = [row for row in ranking if row["variance"] is not None and row["variance"] < 0]
        if adverse:
            row = adverse[0]
            lines += ["", f"优先核查商品{row['product_id']}，收入差额{money_text(row['variance'])}元。该排序按商品净收入差额，不能把商品差额再加到因素桥。"]
        lines += ["", "建议核实：", "", "1. 核对均价变化是否来自促销折扣、渠道或区域成交占比、标价调整。", "2. 核对销量与结构变化是否涉及活动、供货、渠道流量或预算假设。", "3. 按退款确认日追查退款事件，区分本月销售退回与历史销售跨月退款。", "4. 对单位成本和费用不利项核对采购/物流/投放记录及归期。", "", "以上是待调查假设。数学拆解能说明金额贡献，不能单独证明业务原因或价格对销量的因果影响。"]
    return "\n".join(lines)+"\n"


def run(profile, month, products=None, channels=None, regions=None, version="B2026_V1", output=None):
    engine = FinancialEngine(load_facts(profile))
    filters = Filters(products, channels, regions)
    result = variance_pack(engine, month, filters, version)
    output = Path(output) if output else ROOT / "outputs/stage8"
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "variance_result.json", result)
    (output / "预算差异调查案例.md").write_text(case_text(result), encoding="utf-8")
    for kind, item, scope in (("收入预算差异桥", result["selected"]["revenue_bridge"], filters), ("毛利预算差异桥", result["selected"]["gross_margin_bridge"], filters), ("公司利润预算差异桥", result["company_operating_bridge"], Filters())):
        frame = pd.DataFrame(item["details"], columns=["product_id", "expense_category", "department", "channel_scope", "region_scope", "factor", "factor_label", "amount"])
        export_kind = kind if item["status"] == "complete" else kind+"_不可拆解_"+item["reason"]
        name = safe_export_name(engine.entity_id, month, export_kind, scope, version=version, fingerprint=engine.metadata.get("source_fingerprint"))
        (output / name).write_bytes(csv_bytes(frame))
        print(f"{kind}：{item['status']}；差额{money_text(item['variance'])}元；勾稽{item['reconciled']}。")
    print("STAGE8_COMPLETED：差异结果与调查案例已保存到"+str(output))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="固定预算版本的PVM与毛利/利润桥")
    parser.add_argument("--profile", default="configs/demo_files.json")
    parser.add_argument("--month", default="2026-09")
    parser.add_argument("--version", default="B2026_V1")
    parser.add_argument("--products", nargs="+")
    parser.add_argument("--channels", nargs="+")
    parser.add_argument("--regions", nargs="+")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        profile = Path(args.profile)
        run(profile if profile.is_absolute() else ROOT/profile, args.month, args.products, args.channels, args.regions, args.version, args.output)
    except Exception as error:
        print("阶段8处理已停止："+type(error).__name__+"，请核对来源配置、完整期间、筛选和预算版本。", file=sys.stderr)
        sys.exit(1)
