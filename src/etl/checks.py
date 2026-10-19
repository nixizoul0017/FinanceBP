from __future__ import annotations

from datetime import date

import pandas as pd

from .common import ZERO, read_json
from .sources import CONTRACT


def financial_events(facts):
    """阶段5核对用事件表；正式指标和期间计算在阶段6扩展。"""
    sales = facts.tables["sales"].copy()
    if not facts.metadata["capabilities"]["margin"]:
        raise ValueError("missing_cost:毛利核对需要完整成本，不能填0")
    sales["month"] = sales["revenue_date"].map(lambda day: day.replace(day=1))
    sales["net_revenue"] = sales["sales_amount_before_refund"]
    sales["net_cost"] = sales["cogs_amount"]
    refunds = facts.tables["refunds"].merge(sales[["entity_id", "sale_line_id", "product_id", "channel_id", "region_id"]], on=["entity_id", "sale_line_id"], how="left", validate="many_to_one")
    refunds["month"] = refunds["refund_date"].map(lambda day: day.replace(day=1))
    refunds["net_revenue"] = refunds["refund_amount"].map(lambda value: -value)
    refunds["net_cost"] = refunds["cost_reversal_amount"].map(lambda value: -value)
    columns = ["entity_id", "month", "product_id", "channel_id", "region_id", "net_revenue", "net_cost"]
    events = pd.concat([sales[columns], refunds[columns]], ignore_index=True)
    events["gross_margin"] = events["net_revenue"] - events["net_cost"]
    return events


def totals(frame, fields):
    return {field: sum(frame[field].tolist(), ZERO) for field in fields}


def monthly_company(facts):
    events = financial_events(facts)
    actual = events.groupby(["entity_id", "month"], as_index=False)[["net_revenue", "net_cost", "gross_margin"]].sum()
    fees = facts.tables["expenses"].copy()
    fees["month"] = fees["expense_date"].map(lambda day: day.replace(day=1))
    fees = fees.groupby(["entity_id", "month"], as_index=False)["amount"].sum().rename(columns={"amount": "expenses"})
    result = actual.merge(fees, on=["entity_id", "month"], how="outer", validate="one_to_one")
    for field in ["net_revenue", "net_cost", "gross_margin", "expenses"]:
        result[field] = result[field].map(lambda value: ZERO if pd.isna(value) else value)
    result["operating_profit"] = result["gross_margin"]-result["expenses"]
    return result.sort_values(["entity_id", "month"]).reset_index(drop=True)


def verify_reference(facts, path):
    reference = read_json(path)
    month = date.fromisoformat(reference["analysis_month"])
    events = financial_events(facts)
    current = events[events["month"] == month]
    fees = facts.tables["expenses"]
    fees = fees[fees["expense_date"].map(lambda day: day.replace(day=1)) == month]
    sales = facts.tables["sales"]
    current_sales = sales[sales["revenue_date"].map(lambda day: day.replace(day=1)) == month]
    company = totals(current, ["net_revenue", "net_cost", "gross_margin"])
    company["expenses"] = sum(fees["amount"], ZERO)
    company["operating_profit"] = company["gross_margin"]-company["expenses"]
    company["confirmed_orders"] = current_sales["order_id"].nunique()
    checks = []
    for field, expected in reference["company"].items():
        checks.append({"check": f"company.{field}", "expected": expected, "actual": company[field], "passed": company[field] == expected})
    for group, dimension, source_key in [("products", "product_id", "product_id"), ("channels", "channel_id", "channel_code"), ("regions", "region_id", "region_code")]:
        actual_keys = set(current[dimension])
        expected_keys = {row[source_key] for row in reference[group]}
        checks.append({"check": f"{group}.key_set", "passed": actual_keys == expected_keys})
        for expected in reference[group]:
            aggregate = totals(current[current[dimension] == expected[source_key]], ["net_revenue", "net_cost", "gross_margin"])
            for field in ["net_revenue", "net_cost", "gross_margin"]:
                if field in expected:
                    checks.append({"check": f"{group}.{expected[source_key]}.{field}", "expected": expected[field], "actual": aggregate[field], "passed": aggregate[field] == expected[field]})
    budget = facts.tables["sales_budget"]
    budget = budget[(budget["month"] == month) & (budget["budget_version"] == reference["sales_budget"]["version"])]
    revenue = sum((r.quantity*r.net_unit_price-r.refund_amount for r in budget.itertuples()), ZERO)
    cost = sum((r.quantity*r.unit_cost-r.cost_reversal_amount for r in budget.itertuples()), ZERO)
    for field, actual in {"net_revenue": revenue, "net_cost": cost, "gross_margin": revenue-cost}.items():
        checks.append({"check": f"sales_budget.{field}", "expected": reference["sales_budget"][field], "actual": actual, "passed": actual == reference["sales_budget"][field]})
    budget_fees = facts.tables["expense_budget"]
    budget_fees = budget_fees[(budget_fees["month"] == month) & (budget_fees["budget_version"] == reference["sales_budget"]["version"])]
    amount = sum(budget_fees["amount"], ZERO)
    checks.append({"check": "expense_budget", "expected": reference["expenses_budget"], "actual": amount, "passed": amount == reference["expenses_budget"]})
    return {"passed": all(row["passed"] for row in checks), "company": company, "checks": checks}


def assert_equivalent(first, second):
    for name in CONTRACT:
        columns = CONTRACT[name]
        left = first.tables[name].sort_values(columns, na_position="last").reset_index(drop=True)
        right = second.tables[name].sort_values(columns, na_position="last").reset_index(drop=True)
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
    return {"passed": True, "tables": list(CONTRACT), "method": "全量标准字段逐行比较，包含身份、日期、维度、数量及精确金额"}
