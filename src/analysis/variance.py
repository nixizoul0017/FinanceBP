"""固定预算版本的收入、毛利和公司经营利润差异桥。"""
from fractions import Fraction

import pandas as pd

from etl.common import ZERO
from .comparison import company_budget_comparison, sales_budget_comparison
from .metrics import DIMENSIONS, Filters, filter_dimensions, month_date, sum_decimal
from .pvm import bridge, enrich_products, product_effects


def contribution_ranking(comparison, by="product_id", metric="net_revenue"):
    if not isinstance(by, str) or not by:
        raise ValueError("不支持的贡献维度")
    rows = {}
    for item in comparison["details"]:
        if by not in item:
            continue
        name = item[by]
        values = item["metrics"][metric] if "metrics" in item else item
        group = rows.setdefault(name, {"actual": [], "budget": [], "variance": []})
        for field in group:
            group[field].append(values[field])
    result = [{by: key, **{field: sum_decimal(values) for field, values in group.items()}} for key, group in rows.items()]
    higher_is_better = metric != "expenses"
    all_known = all(row["variance"] is not None for row in result)
    negative = sum((abs(row["variance"]) for row in result if row["variance"] is not None and (row["variance"] < 0 if higher_is_better else row["variance"] > 0)), ZERO)
    for row in result:
        amount = row["variance"]
        bad = amount is not None and (amount < 0 if higher_is_better else amount > 0)
        row["direction"] = "unknown" if amount is None else "on_budget" if amount == 0 else "unfavorable" if bad else "favorable"
        row["negative_contribution_share"] = abs(amount)/negative if bad and all_known and negative > 0 else ZERO if amount is not None and all_known and negative > 0 else None
    return sorted(result, key=lambda row: (row["variance"] is None, (row["variance"] or ZERO)*(1 if higher_is_better else -1)))


def _products(engine, month, filters, comparison):
    events = engine.period_events(month, month, filters)
    actual = {key[0] if isinstance(key, tuple) else key: group for key, group in events.groupby(["product_id"], sort=True)}
    budget_frame = filter_dimensions(engine.tables["sales_budget"], filters)
    budget_frame = budget_frame[budget_frame["month"].eq(month) & budget_frame["budget_version"].eq(comparison["version"])]
    budget = {key[0] if isinstance(key, tuple) else key: group for key, group in budget_frame.groupby(["product_id"], sort=True)}
    products = []
    for name in sorted(set(actual) | set(budget)):
        group = actual.get(name, events.iloc[:0])
        values, _ = engine._aggregate(group)
        expected = budget.get(name, budget_frame.iloc[:0]).to_dict("records")
        products.append({"product_id": name, "q_actual": values["sales_quantity"], "q_budget": sum(row["quantity"] for row in expected),
            "revenue_actual": values["sales_revenue"], "revenue_budget": sum_decimal(row["quantity"]*row["net_unit_price"] for row in expected),
            "cost_actual": values["sales_cost"] if group["cost_complete"].all() else None,
            "cost_budget": sum_decimal(None if pd.isna(row["unit_cost"]) else row["quantity"]*row["unit_cost"] for row in expected),
            "refund_actual": values["refund_amount"], "refund_budget": sum_decimal(row["refund_amount"] for row in expected),
            "reversal_actual": values["cogs_reversal_amount"], "reversal_budget": sum_decimal(row["cost_reversal_amount"] for row in expected)})
    return products


def sales_variance(engine, month, filters=Filters(), version="B2026_V1", comparison=None):
    month = month_date(month)
    comparison = comparison if comparison is not None else sales_budget_comparison(engine, month, version=version, filters=filters)
    actual = engine.summary(month, filters=filters)
    reason = "actual_incomplete" if not actual["is_complete"] else "budget_incomplete" if comparison["status"] != "complete" else "quantity_unit_unconfirmed" if engine.metadata.get("semantics", {}).get("quantity_unit") != "件" else None
    reason=reason or ('budget_drivers_missing' if engine.metadata.get('budget_input_modes',{}).get(version)=='amounts' else 'product_grain_unavailable' if 'product_id' not in engine.budget_dimensions(version) else None)
    products = _products(engine, month, filters, comparison) if reason is None else []
    totals = comparison["totals"]
    sales0 = sum_decimal(row["revenue_budget"] for row in products) if reason is None else None
    pvm_effects = product_effects(products) if reason is None else []
    sales = bridge(sales0, actual["sales_revenue"], pvm_effects, reason)
    revenue_reason = reason or ("refund_source_missing" if actual["net_revenue"] is None else None)
    refund_effects = [{"product_id": row["product_id"], "factor": "refund", "amount": -(Fraction(row["refund_actual"])-Fraction(row["refund_budget"]))} for row in products] if revenue_reason is None else []
    revenue = bridge(totals["net_revenue"]["budget"], totals["net_revenue"]["actual"], pvm_effects+refund_effects, revenue_reason)
    margin_reason = reason or ("refund_source_missing" if not engine.available["refunds"] else "historic_cost_missing" if actual["gross_margin"] is None else "budget_cost_missing" if totals["gross_margin"]["budget"] is None else None)
    margin_effects = []
    if margin_reason is None:
        margin_effects = product_effects(products, gross_margin=True)+refund_effects+[{"product_id": row["product_id"], "factor": "cost_reversal", "amount": Fraction(row["reversal_actual"])-Fraction(row["reversal_budget"])} for row in products]
    margin = bridge(totals["gross_margin"]["budget"], totals["gross_margin"]["actual"], margin_effects, margin_reason)
    return {"month": month, "version": version, "scope": comparison["scope"], "filters": filters.as_dict(),
            "sales_bridge": sales, "revenue_bridge": revenue, "gross_margin_bridge": margin,
            "products": enrich_products(products),
            "common_product_count": sum(row["q_actual"] > 0 and row["q_budget"] > 0 for row in products),
            "rankings": {dimension: (contribution_ranking(comparison, dimension) if dimension in engine.budget_dimensions(version) else
                [{dimension: row[dimension], "actual": row["net_revenue"], "budget": None, "variance": None, "direction": "unknown", "negative_contribution_share":None} for row in engine.dimensions(month,by=dimension,filters=filters).to_dict("records")]) for dimension in engine.dimension_ids}}


def variance_pack(engine, month, filters=Filters(), version="B2026_V1"):
    month = month_date(month)
    company_budget = company_budget_comparison(engine, month, version=version)
    company = sales_variance(engine, month, version=version, comparison=company_budget["sales"])
    selected = company if filters.is_company else sales_variance(engine, month, filters, version)
    expenses = company_budget["expenses"]
    profit = company_budget["operating_profit"]
    margin = company["gross_margin_bridge"]
    reason = margin["reason"] or ("expense_source_missing" if expenses["total"]["actual"] is None else "expense_budget_incomplete" if expenses["status"] != "complete" else None)
    effects = []
    if reason is None:
        # 从精确产品输入重新求值，避免把高精度Decimal的表示尾差带回公式。
        effects = product_effects(company["products"], gross_margin=True)
        for row in company["products"]:
            effects.extend([{"product_id": row["product_id"], "factor": "refund", "amount": -(Fraction(row["refund_actual"])-Fraction(row["refund_budget"]))},
                            {"product_id": row["product_id"], "factor": "cost_reversal", "amount": Fraction(row["reversal_actual"])-Fraction(row["reversal_budget"])}])
        effects.extend({**{field: row.get(field,'ALL') for field in ("expense_category", "department", "channel_scope", "region_scope")}, "factor": "expense", "amount": -Fraction(row["variance"])} for row in expenses["details"])
    operating = bridge(profit["budget"], profit["actual"], effects, reason)
    return {"metadata": {"entity_id": engine.entity_id, "rule_version": engine.metadata["rule_version"], "source_fingerprint": engine.metadata.get("source_fingerprint"), "coverage": engine.metadata["coverage"], "month": month, "budget_version": version, "sales_filters": filters.as_dict(), "quantity_unit": engine.metadata.get("semantics", {}).get("quantity_unit"), "amount_unit": "CNY excluding tax yuan", "decomposition_order": "common_total_volume_then_product_mix_then_average_price; entry_exit_separate"},
            "selected": selected, "company_operating_bridge": operating,
            "company_expense_details": expenses["details"], "expense_ranking": contribution_ranking(expenses, "expense_category", "expenses")}
