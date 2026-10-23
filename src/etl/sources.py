from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
from sqlalchemy import text

from .common import ZERO, db_engine, digest, project_path, read_json
from .ingest import read_rows
from .dates import parse_business_date
from .validation import Catalog, SCHEMAS, process_rows, require
from .dimensions import attach_dimensions, validate_dimensions, recommend

CONTRACT = {
    "sales": ["entity_id", "sale_line_id", "order_id", "revenue_date", "product_id", "channel_id", "region_id", "quantity", "sales_amount_before_refund", "cogs_amount"],
    "refunds": ["entity_id", "refund_id", "sale_line_id", "refund_date", "returned_quantity", "recoverable_quantity", "refund_amount", "cost_reversal_amount"],
    "expenses": ["entity_id", "expense_id", "expense_date", "expense_category", "department", "channel_scope", "region_scope", "amount"],
    "sales_budget": ["entity_id", "budget_version", "month", "product_id", "channel_id", "region_id", "quantity", "net_unit_price", "unit_cost", "refund_amount", "cost_reversal_amount"],
    "expense_budget": ["entity_id", "budget_version", "month", "expense_category", "department", "channel_scope", "region_scope", "amount"],
}
DATE_FIELDS = {"revenue_date", "refund_date", "expense_date", "month"}
INTEGER_FIELDS = {"quantity", "returned_quantity", "recoverable_quantity"}
MONEY_FIELDS = {"sales_amount_before_refund", "cogs_amount", "refund_amount", "cost_reversal_amount", "amount", "net_unit_price", "unit_cost"}
FACT_KEYS = {
    "sales": ["entity_id", "sale_line_id"], "refunds": ["entity_id", "refund_id"],
    "expenses": ["entity_id", "expense_id"],
    "sales_budget": ["entity_id", "budget_version", "month", "product_id", "channel_id", "region_id"],
    "expense_budget": ["entity_id", "budget_version", "month", "expense_category", "department", "channel_scope", "region_scope"],
}
SEMANTICS = {"currency": "CNY", "amount_unit": "yuan", "tax_basis": "excluding_tax", "quantity_unit": "件", "sales_basis": "discounted_before_refund", "refund_basis": "separate_positive_events", "cost_basis": "historic_transaction_cost"}


@dataclass
class Facts:
    tables: dict
    metadata: dict


def validate_profile(profile):
    if profile.get('adapter')=='column_catalog_v1':
        from .column_catalog import validate_catalog
        validate_catalog(profile)
        return
    require(profile.get("profile_version") in (1, 2), "unsupported_profile_version")
    if profile.get("profile_version") == 2:
        validate_dimensions(profile)
    connection = profile.get("source", {}).get("connection", {})
    require(not ({"password", "url"} & set(connection)), "password_must_not_be_stored_in_profile")
    for name, expected in SEMANTICS.items():
        require(profile.get("semantics", {}).get(name) == expected, f"unsupported_semantics:{name}")
    require(profile.get("rule_version") == "sales_v1", "unsupported_rule_version")
    require(bool(profile.get("entity_id")), "missing_entity_id")
    start = date.fromisoformat(profile["coverage"]["complete_start"])
    end = date.fromisoformat(profile["coverage"]["complete_end"])
    require(start <= end and start.day == 1, "invalid_coverage_range")
    import calendar
    require(end.day == calendar.monthrange(end.year, end.month)[1], "coverage_must_end_at_month_end")


def identifier(value):
    require(isinstance(value, str) and bool(re.fullmatch(r"[^\W\d]\w*", value)), "invalid_sql_identifier")
    return "`" + value + "`"


def read_source_tables(profile, engine=None, *, raw_records=None, sample_limit=None, column_comments=None, column_types=None):
    records, fingerprints = {}, []
    source = profile["source"]
    if source["kind"] == "files":
        for name, setting in profile["tables"].items():
            paths = setting["files"]
            records[name] = []
            for path_value in paths:
                path = project_path(path_value)
                from .file_tables import read_table
                options={key:setting[key] for key in ('sheet_name','header_row','encoding') if key in setting}
                table=read_table(path,limit=sample_limit,**options)
                if column_comments is not None:
                    column_comments.setdefault(name,{}).update({field:table.comments.get(field,'') for field in table.columns})
                records[name].extend(table.rows)
                fingerprints.append({"dataset": name, "file": path.name, "sha256": digest(path)})
    elif source["kind"] == "mysql":
        own_engine = engine is None
        engine = engine or db_engine(source["connection"])
        try:
            with engine.connect() as connection:
                # 源库只执行SELECT；一致性快照避免读取期间订单与退款发生变化。
                connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                for name, setting in profile["tables"].items():
                    table = identifier(setting["table"])
                    columns = setting.get("mapping", {field: field for field in SCHEMAS.get(name, {})})
                    fields = sorted(set(columns.values()))
                    all_columns = profile.get("profile_version") == 2 or sample_limit is not None
                    require(bool(fields) or all_columns, f"missing_mapping:{name}")
                    select = "*" if all_columns else ",".join(identifier(field) for field in fields)
                    limit = f" LIMIT {int(sample_limit)}" if sample_limit else ""
                    frame = pd.read_sql_query(text(f"SELECT {select} FROM {table}{limit}"), connection, coerce_float=False)
                    if column_comments is not None:
                        from sqlalchemy import inspect
                        schema = inspect(connection).get_columns(setting['table'])
                        column_comments[name] = {col['name']: col.get('comment') or '' for col in schema}
                        if column_types is not None:
                            column_types[name] = {col['name']: str(col['type']) for col in schema}
                    # Pandas的字符串列会把SQL NULL转换为NaN；在边界恢复为None。
                    records[name] = frame.astype(object).where(pd.notna(frame), None).to_dict("records")
                connection.rollback()
        finally:
            if own_engine:
                engine.dispose()
        fingerprints.append({"database": source["connection"]["database"], "host": source["connection"]["host"], "port": source["connection"]["port"]})
    else:
        raise ValueError("unsupported_source_kind")
    if raw_records is not None:
        raw_records.update(records)
    for name, setting in profile["tables"].items():
        if setting.get("mapping"):
            mapping = setting["mapping"]
            records[name] = [{field: row.get(original) for field, original in mapping.items()} for row in records[name]]
        for row in records[name]:
            for field,value in setting.get('defaults',{}).items():
                if row.get(field) in (None,''):
                    row[field]=value
            for field in DATE_FIELDS:
                value=row.get(field)
                if value not in (None,''):
                    row[field]=parse_business_date(value,field=field,allow_month=field=='month').isoformat()
            if setting.get('money_rounding')=='half_up':
                for field in MONEY_FIELDS:
                    if row.get(field) not in (None,''):
                        scale=4 if field in ('net_unit_price','unit_cost') else 2
                        value=Decimal(str(row[field]))
                        require(value.is_finite(),f'invalid_amount:{field}')
                        row[field]=value.quantize(Decimal(10)**-scale,rounding=ROUND_HALF_UP)
        for field, values in setting.get("value_maps", {}).items():
            for row in records[name]:
                if row.get(field) is not None:
                    require(str(row[field]) in values, f"unmapped_dimension_value:{name}.{field}")
                    row[field] = values[str(row[field])]
    return records, fingerprints


def normalize_ecommerce(records, entity):
    catalog, raw, quality = Catalog(), {}, []
    for table in SCHEMAS:
        accepted, rejected, skipped = process_rows(table, records.get(table, []), catalog)
        if rejected or skipped:
            quality.append({"table": table, "rejected": rejected[:20], "duplicate_rows": skipped})
        raw[table] = accepted
    require(not quality, "source_quality_failed:" + json.dumps(quality, ensure_ascii=False, default=str))
    orders = {row["order_id"]: row for row in raw["orders"]}
    tables = {name: [] for name in CONTRACT}
    for item in raw["order_items"]:
        order = orders[item["order_id"]]
        if order["order_status"] != "completed":
            continue
        tables["sales"].append(dict(entity_id=entity, sale_line_id=item["order_item_id"], order_id=item["order_id"], revenue_date=order["recognized_date"], product_id=item["product_id"], channel_id=order["channel_code"], region_id=order["region_code"], quantity=item["quantity"], sales_amount_before_refund=item["quantity"]*item["unit_list_price"]-item["discount_amount"], cogs_amount=item["quantity"]*item["unit_cost_snapshot"]))
    for row in raw["returns"]:
        tables["refunds"].append(dict(entity_id=entity, refund_id=row["return_id"], sale_line_id=row["order_item_id"], refund_date=row["refund_date"], returned_quantity=row["returned_quantity"], recoverable_quantity=row["recoverable_quantity"], refund_amount=row["refund_amount"], cost_reversal_amount=row["cogs_reversal_amount"]))
    for row in raw["expenses"]:
        tables["expenses"].append(dict(entity_id=entity, expense_id=row["expense_id"], expense_date=row["expense_date"], expense_category=row["expense_category"], department=row["department"], channel_scope=row["channel_code"] or "ALL", region_scope=row["region_code"] or "ALL", amount=row["amount"]))
    for row in raw["budget_sales"]:
        tables["sales_budget"].append(dict(entity_id=entity, budget_version=row["budget_version"], month=row["month"], product_id=row["product_id"], channel_id=row["channel_code"], region_id=row["region_code"], quantity=row["budget_quantity"], net_unit_price=row["budget_net_unit_price"], unit_cost=row["budget_unit_cost"], refund_amount=row["budget_refund_amount"], cost_reversal_amount=row["budget_cogs_reversal_amount"]))
    for row in raw["budget_expenses"]:
        tables["expense_budget"].append(dict(entity_id=entity, budget_version=row["budget_version"], month=row["month"], expense_category=row["expense_category"], department=row["department"], channel_scope=row["channel_scope"], region_scope=row["region_scope"], amount=row["budget_amount"]))
    return tables


def normalize_mapped(records, entity):
    tables = {name: [] for name in CONTRACT}
    for name, columns in CONTRACT.items():
        for raw in records.get(name, []):
            row = {"entity_id": entity}
            for field in columns[1:]:
                value = raw.get(field)
                if value is None or value == "":
                    require(field in {"cogs_amount", "unit_cost"}, f"missing_standard_field:{name}.{field}")
                    row[field] = None
                elif field in DATE_FIELDS:
                    row[field] = parse_business_date(value,field=field,allow_month=field=='month')
                elif field in INTEGER_FIELDS:
                    number = Decimal(str(value))
                    require(number.is_finite() and number == number.to_integral_value(), f"invalid_integer:{field}")
                    row[field] = int(number)
                elif field in MONEY_FIELDS:
                    number = Decimal(str(value))
                    scale = 4 if field in {"net_unit_price", "unit_cost"} else 2
                    require(number.is_finite() and number >= ZERO and number == number.quantize(Decimal(10)**-scale), f"invalid_amount:{field}")
                    row[field] = number
                else:
                    row[field] = str(value).strip()
                    require(bool(row[field]), f"empty_standard_field:{field}")
            tables[name].append(row)
    return tables


def validate_facts(tables, budget_dimensions=None):
    for name, rows in tables.items():
        keys = set()
        for row in rows:
            fields = FACT_KEYS[name]
            if name == "sales_budget" and budget_dimensions is not None:
                fields = ["entity_id", "budget_version", "month", *budget_dimensions[row['budget_version']]]
            row_key = tuple(row[field] for field in fields)
            require(row_key not in keys, f"duplicate_standard_key:{name}")
            keys.add(row_key)
            if "quantity" in row:
                require(row["quantity"] > 0 if name == "sales" else row["quantity"] >= 0, "invalid_standard_quantity")
            if "month" in row:
                require(row["month"].day == 1, "invalid_standard_budget_month")
    sales = {(r["entity_id"], r["sale_line_id"]): r for r in tables["sales"]}
    totals = {}
    for row in tables["refunds"]:
        sale = sales.get((row["entity_id"], row["sale_line_id"]))
        require(sale is not None, "standard_refund_unknown_sale")
        require(row["refund_date"] >= sale["revenue_date"], "standard_refund_before_sale")
        require(0 <= row["recoverable_quantity"] <= row["returned_quantity"], "invalid_standard_return_quantity")
        total = totals.setdefault((row["entity_id"], row["sale_line_id"]), [0, ZERO, ZERO])
        total[0] += row["returned_quantity"]
        total[1] += row["refund_amount"]
        total[2] += row["cost_reversal_amount"]
        require(total[0] <= sale["quantity"] and total[1] <= sale["sales_amount_before_refund"], "standard_cumulative_refund_exceeds_sale")
        if sale["cogs_amount"] is not None:
            expected = sale["cogs_amount"] * row["recoverable_quantity"] / sale["quantity"]
            require(row["cost_reversal_amount"] == expected and total[2] <= sale["cogs_amount"], "standard_reversal_mismatch")
        else:
            require(row["recoverable_quantity"] > 0 or row["cost_reversal_amount"] == ZERO, "standard_reversal_without_recovery")


def load_facts(profile_or_path, engine=None):
    profile = read_json(profile_or_path) if not isinstance(profile_or_path, dict) else profile_or_path
    validate_profile(profile)
    raw = {}
    records, fingerprints = read_source_tables(profile, engine, raw_records=raw)
    adapter = profile["adapter"]
    if adapter == "ecommerce_v1":
        tables = normalize_ecommerce(records, profile["entity_id"])
    elif adapter == "mapped_facts_v1":
        tables = normalize_mapped(records, profile["entity_id"])
    else:
        raise ValueError("unsupported_adapter")
    dimension_metadata = attach_dimensions(profile, raw, tables) if profile.get("profile_version") == 2 else {}
    validate_facts(tables, dimension_metadata.get('budget_dimensions'))
    actual_end = date.fromisoformat(profile["coverage"].get("boundary_event_end", profile["coverage"]["complete_end"]))
    for name, field in [("sales", "revenue_date"), ("refunds", "refund_date"), ("expenses", "expense_date")]:
        require(all(row[field] <= actual_end for row in tables[name]), f"actual_beyond_declared_cutoff:{name}")
    frames = {name: pd.DataFrame(rows, columns=[*CONTRACT[name], *[entry['id'] for entry in dimension_metadata.get('dimension_registry', []) if entry['id'] not in CONTRACT[name] and name in ('sales','sales_budget') and (name=='sales' or name in entry.get('bindings',{}))]]) for name, rows in tables.items()}
    costs_available = bool(tables["sales"]) and all(row["cogs_amount"] is not None for row in tables["sales"])
    source_names = {"sales": "sales", "refunds": "refunds", "expenses": "expenses", "sales_budget": "sales_budget", "expense_budget": "expense_budget"} if adapter == "mapped_facts_v1" else {"sales": "order_items", "refunds": "returns", "expenses": "expenses", "sales_budget": "budget_sales", "expense_budget": "budget_expenses"}
    availability = {name: original in records for name, original in source_names.items()}
    if adapter == "ecommerce_v1":
        availability["sales"] = all(name in records for name in ("orders", "order_items", "products"))
    # 数据库地址不变时，内容更新也必须产生新的缓存身份。
    snapshot = {name: sorted(rows, key=lambda row: tuple(str(row[field]) for field in FACT_KEYS[name])) for name, rows in tables.items()}
    snapshot_hash = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode()).hexdigest()
    identity = hashlib.sha256(json.dumps({"profile": profile, "sources": fingerprints, "snapshot_hash": snapshot_hash}, sort_keys=True, default=str).encode()).hexdigest()
    from .controls import source_controls
    dimension_metadata['source_controls'] = source_controls(records, adapter)
    days=[row[field] for name,field in (('sales','revenue_date'),('refunds','refund_date'),('expenses','expense_date')) for row in tables[name]]
    dimension_metadata['observed_date_range']={'start':min(days).isoformat(),'end':max(days).isoformat()} if days else None
    dimension_metadata['quantity_basis']=profile.get('tables',{}).get('sales',{}).get('quantity_basis','source_column')
    return Facts(frames, {**dimension_metadata, "entity_id": profile["entity_id"], "rule_version": profile["rule_version"], "coverage": profile["coverage"], "semantics": profile["semantics"], "source_fingerprint": identity, "snapshot_hash": snapshot_hash, "sources": fingerprints, "row_counts": {name: len(rows) for name, rows in tables.items()}, "data_availability": availability, "capabilities": {"revenue": availability["sales"] and availability["refunds"], "margin": costs_available and availability["refunds"], "budget": bool(tables["sales_budget"]), "company_profit": costs_available and availability["refunds"] and availability["expenses"]}})


def inspect_profile(profile, engine=None):
    """Only configured source tables, bounded samples, no credentials in results."""
    validate_profile(profile)
    raw, comments, types = {}, {}, {}
    read_source_tables(profile, engine, raw_records=raw, sample_limit=1000, column_comments=comments,column_types=types)
    fields={name:sorted({key for row in rows for key in row} | set(comments.get(name,{})) | set(profile['tables'][name].get('mapping',{}).values())) for name,rows in raw.items()}
    for name, rows in raw.items():
        types.setdefault(name,{field:next((type(row[field]).__name__ for row in rows if row.get(field) not in (None,'')), 'unknown') for field in fields[name]})
    candidates=recommend(profile, raw, comments,all_fields=True)
    for item in candidates:
        item['type']=types.get(item['table'],{}).get(item['field'],'unknown')
    versions=sorted({str(row.get(profile['tables'][name].get('mapping',{}).get('budget_version','budget_version'))) for name in ('sales_budget','budget_sales') for row in raw.get(name,[]) if row.get(profile['tables'][name].get('mapping',{}).get('budget_version','budget_version'))})
    return {"candidates":candidates,"fields":fields,"comments":comments,"types":types,"budget_versions":versions}
