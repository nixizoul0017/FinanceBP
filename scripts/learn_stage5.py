"""可以直接运行的Python学习例子；不写数据库，不改变样本。"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from etl.common import read_json
from etl.validation import parse_row

orders = pd.DataFrame([parse_row("orders", row) for row in read_json(ROOT / "data/sample/stage3/orders.json")])
items = pd.DataFrame([parse_row("order_items", row) for row in read_json(ROOT / "data/sample/stage3/order_items.json")])
completed = orders[orders["order_status"] == "completed"]
detail = items.merge(completed, on="order_id", how="inner", validate="many_to_one")
detail["sales_revenue"] = detail["quantity"]*detail["unit_list_price"]-detail["discount_amount"]
detail["sales_cost"] = detail["quantity"]*detail["unit_cost_snapshot"]
detail["gross_margin_before_returns"] = detail["sales_revenue"]-detail["sales_cost"]
print("全部订单 / 确认订单 / 确认明细：", len(orders), len(completed), len(detail))
print("退款前销售：", detail.groupby("product_id")[["sales_revenue", "sales_cost", "gross_margin_before_returns"]].sum().to_string())
print("注意：本练习还没有扣退款，因此公司退款前收入为4150元，阶段4的净收入为3240元。")
