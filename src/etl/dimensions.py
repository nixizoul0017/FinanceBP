"""Confirmed classification bindings; joins never multiply financial rows."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import re

import pandas as pd

BUILTINS = {"product_id": "商品", "channel_id": "渠道", "region_id": "地区"}
MISSING = "未归属（缺失值）"
ALIASES = {
    "sales_department_id": ("销售部门", ("sales_department", "sales_dept", "department", "dept", "销售部门", "部门")),
    "salesperson_id": ("销售员", ("salesperson", "salesman", "sales_rep", "seller", "employee", "员工", "销售人员", "销售员", "售货员", "业务员")),
    "store_id": ("门店", ("store", "shop", "branch", "门店", "店铺")),
    "customer_type": ("客户类型", ("customer_type", "customer_segment", "客户类型", "客户类别")),
    "product_category": ("商品类别", ("category", "品类", "商品类别")),
}


def code(value):
    if value is None or (not isinstance(value, (str, list, dict)) and pd.isna(value)) or str(value).strip() == "":
        return MISSING
    if isinstance(value,(int,float,Decimal)) and not isinstance(value,bool) and Decimal(str(value)).is_finite() and Decimal(str(value))==Decimal(str(value)).to_integral_value():
        value=str(int(value))
    value = str(value).strip()
    if "\x00" in value or value == MISSING:
        raise ValueError("分类编码不能包含NUL字符")
    return value


def display(value):
    return "未归属" if value == MISSING else str(value)


def profile_key(profile):
    """Stable across data refresh, dimension renames and credential changes."""
    if profile.get("profile_id"):
        return str(profile["entity_id"]) + ":" + str(profile["profile_id"])
    source = deepcopy(profile["source"])
    source.get("connection", {}).pop("password_env", None)
    identity = {"entity": profile["entity_id"], "adapter": profile["adapter"], "source": source,
                "tables": {name: {k: v for k, v in setting.items() if k in ("files", "table")}
                           for name, setting in profile["tables"].items() if name not in profile.get("lookup_tables", [])}}
    return profile["entity_id"] + ":" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]


def validate_dimensions(profile):
    dimensions = profile.get("dimensions", [])
    if not isinstance(dimensions, list):
        raise ValueError("dimensions必须为列表")
    seen = set(BUILTINS)
    reserved = {"entity_id", "month", "sale_line_id", "order_id", "revenue_date", "quantity", "cogs_amount", "sales_amount_before_refund", "refund_id", "refund_date", "expense_id", "expense_date", "expense_category", "department", "channel_scope", "region_scope", "amount", "budget_version", "net_unit_price", "unit_cost", "returned_quantity", "recoverable_quantity", "refund_amount", "cost_reversal_amount", "sales_revenue", "sales_cost", "net_revenue", "net_cost", "gross_margin", "gross_margin_rate", "sales_quantity", "net_quantity", "confirmed_orders", "confirmed_lines", "expenses", "operating_profit", "cogs_reversal_amount", "kind", "is_available", "period_is_complete"}
    for item in dimensions:
        key = item.get("id", "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) or key in seen or key in reserved:
            raise ValueError("分类编号重复或无效：" + str(key))
        seen.add(key)
        if not isinstance(item.get("label"), str) or not item["label"].strip():
            raise ValueError("分类显示名称不能为空")
        if "sales" not in item.get("bindings", {}):
            raise ValueError("销售分类必须映射到销售记录")
        for target, binding in item["bindings"].items():
            if target not in ("sales", "sales_budget") or binding.get("table") not in profile["tables"] or not binding.get("field"):
                raise ValueError("分类来源映射无效")
            lookup = binding.get("lookup")
            if lookup and (lookup.get("table") not in profile["tables"] or not lookup.get("key")):
                raise ValueError("关联分类表必须指定表与唯一键")
    forecast = profile.get("forecast_dimensions", [*BUILTINS, *(x["id"] for x in dimensions)])
    if len(forecast) != len(set(forecast)) or not set(BUILTINS).issubset(forecast) or not set(forecast).issubset(seen):
        raise ValueError("预测建模维度配置无效")


def canonical_records(profile, raw):
    return {name: [{**row, **{key: row.get(field) for key, field in profile["tables"][name].get("mapping", {}).items()}}
                   for row in rows] for name, rows in raw.items()}


def _index(rows, key):
    result = {}
    for row in rows:
        value = code(row.get(key))
        if value == MISSING or value in result:
            raise ValueError("分类关联键必须唯一且非空：" + key)
        result[value] = row
    return result


def _resolve(profile, raw, standard, binding, target):
    table = binding["table"]
    source_rows=raw.get(table,[])
    if source_rows and not any(binding['field'] in row for row in source_rows):
        raise ValueError('分类来源字段不存在：'+table+'.'+binding['field'])
    if binding.get('name_field') and source_rows and not any(binding['name_field'] in row for row in source_rows):
        raise ValueError('分类名称字段不存在')
    anchors = {"sales": ("sale_line_id", "sale_line_id"), "order_items": ("sale_line_id", "order_item_id"),
               "orders": ("order_id", "order_id"), "products": ("product_id", "product_id"),
               "sales_budget": (None, None), "budget_sales": (None, None)}
    left, right = anchors.get(table, (binding.get("sales_key"), binding.get("source_key")))
    left, right = binding.get("sales_key", left), binding.get("source_key", right)
    if target == "sales_budget" and table in ("sales_budget", "budget_sales"):
        # Raw budget order and normalizer order are identical. Values are never joined on a coarser key.
        selected = raw.get(table, [])
        if len(selected) != len(standard):
            raise ValueError("预算分类映射行数不一致")
    elif table == "customers" and target == "sales":
        orders = _index(raw.get("orders", []), "order_id")
        customers = _index(raw.get(table, []), binding.get("source_key", "customer_id"))
        selected = [customers.get(code(orders.get(code(row["order_id"]), {}).get("customer_id")), {}) for row in standard]
    else:
        if not left or not right or any(left not in row for row in standard):
            raise ValueError("请明确分类表与销售记录的关联键")
        indexed = _index(raw.get(table, []), right)
        selected = [indexed.get(code(row.get(left)), {}) for row in standard]
    lookup = binding.get("lookup")
    indexed_lookup = _index(raw.get(lookup["table"], []), lookup["key"]) if lookup else None
    values, names = [], {}
    for row in selected:
        value = row.get(binding["field"])
        name = row.get(binding.get("name_field", ""))
        if lookup:
            match = indexed_lookup.get(code(value), {})
            if lookup.get("value_field"):
                value = match.get(lookup["value_field"])
            name = match.get(lookup.get("name_field", ""))
        value = code(value)
        if name is not None and str(name).strip() and value != MISSING:
            # Codes stay authoritative; renamed staff never generate extra financial rows.
            names[value] = str(name).strip()
        values.append(value)
    return values, names


def attach_dimensions(profile, raw, tables):
    """One scalar per fact and dimension. Refunds inherit sales later in the engine."""
    before=[(row['sale_line_id'],row['sales_amount_before_refund'],row['cogs_amount']) for row in tables['sales']]
    raw = canonical_records(profile, raw)
    registry = [{"id": key, "label": label, "names": {}} for key, label in BUILTINS.items()]
    versions = sorted({row["budget_version"] for row in tables["sales_budget"]})
    budget_dimensions = {version: list(BUILTINS) for version in versions}
    for spec in profile.get("dimensions", []):
        entry = {"id": spec["id"], "label": spec["label"].strip(), "names": {}, "bindings": deepcopy(spec["bindings"]), "data_grain":{"sales":["sale_line_id"],"sales_budget":"按预算版本已确认的维度组合"}}
        for target, binding in spec["bindings"].items():
            values, names = _resolve(profile, raw, tables[target], binding, target)
            allowed = binding.get("versions", versions)
            for row, value in zip(tables[target], values):
                row[spec["id"]] = value if target != "sales_budget" or row["budget_version"] in allowed else MISSING
            entry["names"].update(names)
            if target == "sales_budget":
                for version in versions:
                    if version in allowed:
                        budget_dimensions[version].append(spec["id"])
        entry["missing_sales"] = sum(row[spec["id"]] == MISSING for row in tables["sales"])
        registry.append(entry)
    after=[(row['sale_line_id'],row['sales_amount_before_refund'],row['cogs_amount']) for row in tables['sales']]
    if before!=after:
        raise ValueError('分类关联改变了销售行数或金额')
    return {"join_validation":{"sales_rows_before":len(before),"sales_rows_after":len(after),"amounts_unchanged":True},"dimension_registry": registry, "budget_dimensions": budget_dimensions,
            "forecast_dimensions": profile.get("forecast_dimensions", [entry["id"] for entry in registry]),
            "profile_id": profile_key(profile), "profile_version": 2}


def recommend(profile, raw, columns=None):
    """Candidates, never silent activation. Numeric identifiers may be valid categories."""
    candidates = []
    eligible = ("sales", "orders", "order_items", "products", "customers")
    used = {item["id"] for item in profile.get("dimensions", [])}
    for table in eligible:
        if table not in raw:
            continue
        fields = sorted({key for row in raw[table][:1000] for key in row})
        mapping = profile["tables"][table].get("mapping", {})
        standard = {value: key for key, value in mapping.items()}
        for field in fields:
            canonical = standard.get(field, field)
            if canonical in BUILTINS or canonical in {"sale_line_id", "order_id", "order_item_id", "customer_id", "line_number"}:
                continue
            if any(word in canonical.lower() for word in ("date", "amount", "cost", "price", "quantity", "discount", "日期", "时间", "金额", "数量", "订单号", "流水号")):
                continue
            preferred = next(((key, label) for key, (label, aliases) in ALIASES.items() if any(alias in field.lower() for alias in aliases)), None)
            samples = [row.get(field) for row in raw[table][:1000] if row.get(field) not in (None, "")]
            if not preferred and samples and not isinstance(samples[0], str):
                continue
            key = preferred[0] if preferred else "dim_" + hashlib.sha256((table+":"+field).encode()).hexdigest()[:12]
            if key in used:
                continue
            candidates.append({"id": key, "label": preferred[1] if preferred else field,
                               "table": table, "field": field, "recommended": preferred is not None,
                               "sample_values": [display(value) for value in dict.fromkeys(code(v) for v in samples)][:5],
                               "missing_rate": sum(row.get(field) in (None, "") for row in raw[table][:1000]) / max(1, len(raw[table][:1000])),
                               "comment": (columns or {}).get(table, {}).get(field, "")})
    return candidates
