from __future__ import annotations

import calendar
import csv
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .common import CENT, ZERO, digest, encode, write_json
from .sources import CONTRACT, SEMANTICS, normalize_ecommerce
from .validation import SCHEMAS


def money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: encode(value) if isinstance(value, (date, Decimal)) else value for field, value in row.items()})


def base_profile(entity, coverage):
    return {"profile_version": 1, "entity_id": entity, "rule_version": "sales_v1", "coverage": coverage, "semantics": SEMANTICS.copy()}


def generate_demo(directory, line_count=50000, seed=20261012):
    if line_count < 1000:
        raise ValueError("完整历史至少生成1000条明细；小样本使用stage3文件")
    directory = Path(directory)
    rng = random.Random(seed)
    data = {table: [] for table in SCHEMAS}
    categories = ["STORAGE", "CLEANING", "KITCHEN"]
    labels = {"STORAGE": "收纳", "CLEANING": "清洁", "KITCHEN": "厨房"}
    prices = {}
    for number in range(1, 21):
        category = categories[(number-1) % 3]
        product = f"P{number:03}"
        data["products"].append(dict(product_id=product, product_name=f"{labels[category]}商品{number:02}", category=category, quantity_unit="件", active_flag=1))
        price = Decimal(35 + (number*17) % 145)
        prices[product] = (price, money(price * (Decimal("0.48") + Decimal(number % 5) / 100)), category)
    for number in range(1, 3001):
        data["customers"].append(dict(customer_id=f"U{number:05}", signup_date=date(2024, 1, 1)))
    months = [date(2024+y//12, y % 12+1, 1) for y in range(33)]
    seasonal = {1: .85, 2: .70, 3: .95, 4: 1.0, 5: 1.08, 6: 1.35, 7: 1.02, 8: 1.03, 9: 1.08, 10: 1.12, 11: 1.65, 12: 1.25}
    weights = [seasonal[m.month] * (1 + .10*(m.year-2024)) for m in months]
    allocation = [math.floor(line_count*w/sum(weights)) for w in weights]
    for i in sorted(range(33), key=lambda j: line_count*weights[j]/sum(weights)-allocation[j], reverse=True)[:line_count-sum(allocation)]:
        allocation[i] += 1
    end = date(2026, 9, 30)
    order_number, line_number, refund_number = 0, 0, 0
    monthly_sales = defaultdict(lambda: [0, ZERO, ZERO])
    monthly_channel = defaultdict(lambda: [0, ZERO])
    for month, target in zip(months, allocation):
        remaining = target
        while remaining:
            order_number += 1
            channel_weights = [45, 32, 23] if month < date(2026, 7, 1) else [57, 18, 25]
            channel = rng.choices(["C01", "C02", "C03"], weights=channel_weights)[0]
            region = rng.choices(["R01", "R02", "R03", "R04"], weights=[34, 29, 24, 13])[0]
            day = rng.randint(2, calendar.monthrange(month.year, month.month)[1]-1)
            recognized = month.replace(day=day)
            status = rng.choices(["completed", "cancelled", "pending"], weights=[95, 4, 1])[0]
            order_id = f"O{order_number:07}"
            data["orders"].append(dict(order_id=order_id, customer_id=f"U{rng.randint(1,3000):05}", order_date=recognized-timedelta(days=1), recognized_date=recognized if status == "completed" else None, channel_code=channel, region_code=region, order_status=status))
            lines = min(remaining, rng.choices([1, 2, 3], weights=[65, 28, 7])[0])
            for position in range(1, lines+1):
                line_number += 1
                item_id = f"L{line_number:07}"
                product = f"P{rng.randint(1,20):03}"
                price, cost, category = prices[product]
                price = money(price * (Decimal("1.02") ** (month.year-2024)))
                cost = money(cost * (Decimal("1.025") ** (month.year-2024)))
                if category == "STORAGE" and month >= date(2026, 3, 1):
                    cost = money(cost*Decimal("1.15"))
                quantity = rng.choices([1, 2, 3, 5], weights=[50, 30, 15, 5])[0]
                discount_rate = Decimal(rng.randint(2, 10))/100
                if channel == "C01" and month >= date(2026, 7, 1):
                    discount_rate = Decimal(rng.randint(15, 24))/100
                discount = money(quantity*price*discount_rate)
                revenue, cogs = quantity*price-discount, quantity*cost
                data["order_items"].append(dict(order_item_id=item_id, order_id=order_id, line_number=position, product_id=product, quantity=quantity, unit_list_price=price, discount_amount=discount, unit_cost_snapshot=cost))
                if status != "completed":
                    continue
                key = (month, product, channel, region)
                monthly_sales[key][0] += quantity
                monthly_sales[key][1] += revenue
                monthly_sales[key][2] += cogs
                monthly_channel[(month, channel)][0] += quantity
                monthly_channel[(month, channel)][1] += revenue
                chance = .05
                if category == "KITCHEN" and region == "R04" and month >= date(2026, 8, 1):
                    chance = .16
                if rng.random() >= chance:
                    continue
                refund_date = recognized + timedelta(days=rng.randint(3, 30))
                if refund_date > end:
                    continue  # 截止日后尚未发生的退款不进入实际数据。
                reason = rng.choices(["return_resalable", "return_unsellable", "compensation"], weights=[65, 25, 10])[0]
                returned = quantity if rng.random() < .10 else 1
                if reason == "compensation":
                    returned = 0
                recovered = returned if reason == "return_resalable" else 0
                amount = revenue if returned == quantity else money(revenue/quantity*returned) if returned else money(min(Decimal("10"), revenue*Decimal(".03")))
                refund_number += 1
                data["returns"].append(dict(return_id=f"RF{refund_number:07}", order_item_id=item_id, refund_date=refund_date, returned_quantity=returned, recoverable_quantity=recovered, refund_amount=amount, cogs_reversal_amount=recovered*cost, reason_code=reason))
                if returned == 1 and quantity >= 2 and rng.random() < .10:
                    later = refund_date+timedelta(days=2)
                    if later <= end:
                        refund_number += 1
                        second = min(money(revenue/quantity), revenue-amount)
                        data["returns"].append(dict(return_id=f"RF{refund_number:07}", order_item_id=item_id, refund_date=later, returned_quantity=1, recoverable_quantity=1, refund_amount=second, cogs_reversal_amount=cost, reason_code="return_resalable"))
            remaining -= lines
    expense_number = 0
    size_factor = Decimal(line_count)/50000
    for month in months:
        for channel in ["C01", "C02", "C03"]:
            quantity, revenue = monthly_channel[(month, channel)]
            marketing_rate = Decimal(".11") if channel == "C01" and month >= date(2026, 7, 1) else Decimal(".075")
            values = [("marketing", "D01", money(revenue*marketing_rate)), ("platform_commission", "D02", money(revenue*(Decimal(".06") if channel == "C02" else Decimal(".03")))), ("logistics", "D03", money(quantity*Decimal("3.2")))]
            for category, department, amount in values:
                expense_number += 1
                data["expenses"].append(dict(expense_id=f"E{expense_number:06}", expense_date=month.replace(day=calendar.monthrange(month.year,month.month)[1]), department=department, expense_category=category, channel_code=channel, region_code=None, amount=amount, source_system="demo_ledger", source_reference=f"DOC{expense_number:06}"))
        for category, amount in [("payroll", money(Decimal("12000")*size_factor*(Decimal("1.04")**(month.year-2024)))), ("administration", money(Decimal("2400")*size_factor))]:
            expense_number += 1
            data["expenses"].append(dict(expense_id=f"E{expense_number:06}", expense_date=month.replace(day=calendar.monthrange(month.year,month.month)[1]), department="D04", expense_category=category, channel_code=None, region_code=None, amount=amount, source_system="demo_ledger", source_reference=f"DOC{expense_number:06}"))
    # 2026预算只使用2025同月数据和事先给定假设，不以2026实际乘系数伪造预算。
    for m in range(1, 13):
        month, previous = date(2026,m,1), date(2025,m,1)
        for product in prices:
            for channel in ["C01", "C02", "C03"]:
                for region in ["R01", "R02", "R03", "R04"]:
                    qty, revenue, cogs = monthly_sales[(previous, product, channel, region)]
                    budget_qty = int((Decimal(qty)*Decimal("1.12")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                    price = revenue/qty*Decimal("1.03") if qty else prices[product][0]*Decimal(".94")
                    cost = cogs/qty*Decimal("1.03") if qty else prices[product][1]*Decimal("1.03")
                    price, cost = price.quantize(Decimal(".0001"), rounding=ROUND_HALF_UP), cost.quantize(Decimal(".0001"), rounding=ROUND_HALF_UP)
                    data["budget_sales"].append(dict(budget_version="B2026_V1", month=month, product_id=product, channel_code=channel, region_code=region, budget_quantity=budget_qty, budget_net_unit_price=price, budget_unit_cost=cost, budget_refund_amount=money(budget_qty*price*Decimal(".04")), budget_cogs_reversal_amount=money(budget_qty*cost*Decimal(".03"))))
        for expense in data["expenses"]:
            if expense["expense_date"].replace(day=1) == previous:
                data["budget_expenses"].append(dict(budget_version="B2026_V1", month=month, expense_category=expense["expense_category"], department=expense["department"], channel_scope=expense["channel_code"] or "ALL", region_scope="ALL", budget_amount=money(expense["amount"]*Decimal("1.10"))))
    data["returns"].sort(key=lambda row: (row["refund_date"], row["return_id"]))
    files = {}
    for table, rows in data.items():
        path = directory / f"{table}.csv"
        write_csv(path, rows, list(SCHEMAS[table]))
        files[table] = [{"file": path.name, "sha256": digest(path), "rows": len(rows)}]
    coverage = {"complete_start": "2024-01-01", "complete_end": "2026-09-30"}
    profile = base_profile("XCYX", coverage)
    profile.update(adapter="ecommerce_v1", source={"kind": "files"}, tables={table: {"files": [str((directory/f"{table}.csv").resolve())]} for table in SCHEMAS})
    normalized = normalize_ecommerce(data, "XCYX")
    renamed_mapping = {}
    for name, rows in normalized.items():
        mapping = {field: f"b_{field}" for field in CONTRACT[name] if field != "entity_id"}
        renamed_mapping[name] = mapping
        renamed_rows = [{mapping[field]: value for field, value in row.items() if field != "entity_id"} for row in rows]
        write_csv(directory / "alternate" / f"biz_{name}.csv", renamed_rows, list(mapping.values()))
    manifest = {"dataset": "demo_v1", "seed": seed, "requested_order_lines": line_count, "coverage": coverage, "files": files, "row_counts": {table: len(rows) for table, rows in data.items()}, "canonical_row_counts": {table: len(rows) for table, rows in normalized.items()}, "budget_basis": "2025 same month actual; quantity +12%, net price +3%, unit cost +3%, refunds 4%, cost reversal 3%; expenses +10%; frozen B2026_V1", "money_storage": "decimal text, CNY excluding tax"}
    write_json(directory / "manifest.json", manifest)
    write_json(directory / "scenario_truth.json", {"seed": seed, "use": "仅用于验收和学习；分析模块不得读取此文件作为业务结论或预测输入", "scenarios": [
        {"start": "2024-01", "scope": "company", "change": "6月和11月旺季；年度基础订单量权重2025+10%、2026+20%", "parameter": seasonal},
        {"start": "2026-03", "scope": "STORAGE", "change": "历史单位成本在常规年度变化之外再乘1.15"},
        {"start": "2026-07", "scope": "C01", "change": "折扣率从2%-10%提高至15%-24%；营销费用率从7.5%升至11%"},
        {"start": "2026-07", "scope": "channel_mix", "change": "渠道抽样权重C01/C02/C03从45/32/23改为57/18/25，模拟C02份额下降"},
        {"start": "2026-08", "scope": "KITCHEN×R04", "change": "触发退款事件的概率从5%提高至16%；9月底之后未发生事件被排除"}
    ], "limits": "概率控制的样本结果会波动；预设变化是模拟事实，数学分解不能证明真实企业因果"})
    return manifest, renamed_mapping
