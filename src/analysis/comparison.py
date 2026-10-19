from __future__ import annotations

from datetime import date

from .metrics import DIMENSIONS, Filters, filter_dimensions, month_date, month_range, ratio, shift_month, subtract, sum_decimal


def change(current, previous):
    amount = subtract(current, previous)
    reason = "current_unknown" if current is None else "base_unknown" if previous is None else "nonpositive_base" if previous <= 0 else None
    return {"current": current, "base": previous, "change_amount": amount, "change_rate": ratio(amount, previous), "rate_unavailable_reason": reason}


def trend_comparison(engine, month, filters=Filters()):
    month = month_date(month)
    current = engine.summary(month, filters=filters)
    previous_month = engine.summary(shift_month(month, -1), filters=filters)
    previous_year = engine.summary(shift_month(month, -12), filters=filters)
    fields = ["net_revenue", "net_cost", "gross_margin", "sales_quantity"]
    if filters.is_company:
        fields += ["expenses", "operating_profit"]
    return {"month": month, "previous_month": shift_month(month, -1), "previous_year_month": shift_month(month, -12), "mom": {field: change(current[field], previous_month[field]) for field in fields}, "yoy": {field: change(current[field], previous_year[field]) for field in fields}}


def year_to_date(engine, month, filters=Filters()):
    month = month_date(month)
    current = engine.summary(date(month.year, 1, 1), month, filters)
    previous = engine.summary(date(month.year-1, 1, 1), shift_month(month, -12), filters)
    fields = ["net_revenue", "net_cost", "gross_margin"]
    if filters.is_company:
        fields += ["expenses", "operating_profit"]
    return {"current": current, "previous_year": previous, "comparison": {field: change(current[field], previous[field]) for field in fields}}


def budget_variance(actual, budget, higher_is_better=True):
    amount = subtract(actual, budget)
    direction = "unknown" if amount is None else "on_budget" if amount == 0 else "favorable" if (amount > 0) == higher_is_better else "unfavorable"
    reason = "actual_unknown" if actual is None else "budget_missing" if budget is None else "nonpositive_budget" if budget <= 0 else None
    return {"actual": actual, "budget": budget, "variance": amount, "variance_rate": ratio(amount, budget), "completion_rate": ratio(actual, budget), "direction": direction, "rate_unavailable_reason": reason}


def _validate_version(engine, version):
    if not isinstance(version, str) or not version.strip():
        raise ValueError("必须指定预算版本")
    versions = set(engine.tables["sales_budget"]["budget_version"]) | set(engine.tables["expense_budget"]["budget_version"])
    if versions and version not in versions:
        raise ValueError("未知预算版本:" + version)
    return sorted(versions)


def _sales_budget_values(row):
    if row.get('budget_input_kind')=='amounts':
        import pandas as pd
        revenue=row['budget_net_revenue']
        cost=None if pd.isna(row.get('budget_net_cost')) else row['budget_net_cost']
        return {'net_revenue':revenue,'net_cost':cost,'gross_margin':subtract(revenue,cost)}
    revenue = row["quantity"]*row["net_unit_price"]-row["refund_amount"]
    # Pandas可能用NaN表示缺成本；保持未知，不让聚合跳过。
    import pandas as pd
    cost = None if pd.isna(row["unit_cost"]) else row["quantity"]*row["unit_cost"]-row["cost_reversal_amount"]
    return {"net_revenue": revenue, "net_cost": cost, "gross_margin": subtract(revenue, cost)}


def sales_budget_comparison(engine, start, end=None, version="B2026_V1", filters=Filters()):
    months = month_range(start, start if end is None else end)
    versions = _validate_version(engine, version)
    events = engine.period_events(months[0], months[-1], filters)
    grain = engine.budget_dimensions(version)
    unsupported = [field for field, values in filters.items if values is not None and field not in grain]
    fields = ["month", *(engine.dimension_ids if unsupported else grain)]
    actual = {key: group for key, group in events.groupby(fields, sort=False)}
    budget_frame = engine.tables["sales_budget"].iloc[:0] if unsupported else filter_dimensions(engine.tables["sales_budget"], filters)
    budget_frame = budget_frame[budget_frame["month"].between(months[0], months[-1]) & budget_frame["budget_version"].eq(version)]
    budget = {tuple(row[field] for field in fields): row for row in budget_frame.to_dict("records")}
    details, missing_keys = [], []
    empty = events.iloc[:0]
    for key in sorted(set(actual) | set(budget)):
        has_budget = key in budget
        values, _ = engine._aggregate(actual.get(key, empty))
        actual_complete = engine.is_complete(key[0])
        expected = _sales_budget_values(budget[key]) if has_budget else {field: None for field in ("net_revenue", "net_cost", "gross_margin")}
        identifier = dict(zip(fields, key))
        if not has_budget:
            missing_keys.append(identifier)
        details.append({**identifier, "has_actual_record": key in actual, "actual_is_complete": actual_complete, "has_budget": has_budget, "metrics": {field: budget_variance(values[field] if actual_complete else None, expected[field], higher_is_better=field != "net_cost") for field in expected}})
    budget_months = set(budget_frame["month"])
    missing_months = [month for month in months if month not in budget_months]
    has_budget = bool(budget) and not missing_keys and not missing_months
    # 存在某个实际维度无预算时，公司/筛选合计预算保持未知，不能只加有预算部分。
    budget_values = {field: sum_decimal(_sales_budget_values(row)[field] for row in budget.values()) if has_budget else None for field in ("net_revenue", "net_cost", "gross_margin")}
    actual_values = engine.summary(months[0], months[-1], filters)
    status = "unsupported_dimensions" if unsupported else "complete" if has_budget else "no_budget" if not versions or not engine.available["sales_budget"] else "missing_budget"
    return {**({"unsupported_dimensions":unsupported,"dimensions":list(grain)} if len(engine.dimension_ids)>3 else {}), "version": version, "available_versions": versions, "scope": "company_sales" if filters.is_company else "sales_dimensions", "status": status, "cost_status": "known" if budget_values["net_cost"] is not None else "missing_unit_cost" if has_budget else "budget_incomplete", "actual_is_complete": actual_values["is_complete"], "missing_keys": missing_keys, "missing_months": missing_months, "totals": {field: budget_variance(actual_values[field], budget_values[field], higher_is_better=field != "net_cost") for field in budget_values}, "gross_margin_rate": {"actual": actual_values["gross_margin_rate"], "budget": ratio(budget_values["gross_margin"], budget_values["net_revenue"])}, "details": details}


def expense_budget_comparison(engine, start, end=None, version="B2026_V1"):
    months = month_range(start, start if end is None else end)
    versions = _validate_version(engine, version)
    actual_frame = engine.expenses[engine.expenses["month"].between(months[0], months[-1])]
    fields = ["month", *engine.metadata.get('expense_budget_dimensions',{}).get(version, ['expense_category','department','channel_scope','region_scope'])]
    actual = {key: sum_decimal(group["amount"]) for key, group in actual_frame.groupby(fields, sort=False)}
    budget_frame = engine.tables["expense_budget"]
    budget_frame = budget_frame[budget_frame["month"].between(months[0], months[-1]) & budget_frame["budget_version"].eq(version)]
    budget = {tuple(row[field] for field in fields): row["amount"] for row in budget_frame.to_dict("records")}
    details, missing_keys = [], []
    from etl.common import ZERO
    for key in sorted(set(actual) | set(budget)):
        identifier = dict(zip(fields, key))
        if key not in budget:
            missing_keys.append(identifier)
        actual_amount = actual.get(key, ZERO) if engine.is_complete(key[0]) and engine.available["expenses"] else None
        details.append({**identifier, "has_actual_record": key in actual, "has_budget": key in budget, **budget_variance(actual_amount, budget.get(key), higher_is_better=False)})
    missing_months = [month for month in months if month not in set(budget_frame["month"])]
    has_budget = bool(budget) and not missing_keys and not missing_months
    actual_summary = engine.summary(months[0], months[-1])
    return {"version": version, "scope": "company_expenses", "status": "complete" if has_budget else "no_budget" if not versions or not engine.available["expense_budget"] else "missing_budget", "missing_keys": missing_keys, "missing_months": missing_months, "total": budget_variance(actual_summary["expenses"], sum_decimal(budget.values()) if has_budget else None, higher_is_better=False), "details": details}


def company_budget_comparison(engine, start, end=None, version="B2026_V1"):
    sales = sales_budget_comparison(engine, start, end, version)
    expenses = expense_budget_comparison(engine, start, end, version)
    actual = engine.summary(start, end)
    budget_profit = subtract(sales["totals"]["gross_margin"]["budget"], expenses["total"]["budget"])
    return {"scope": "company", "version": version, "sales": sales, "expenses": expenses, "operating_profit": budget_variance(actual["operating_profit"], budget_profit)}
