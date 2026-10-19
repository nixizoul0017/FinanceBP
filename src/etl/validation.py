from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from .common import ZERO

# 字符串类型带最大长度；金额带小数位数。必须先解析，再执行跨表业务校验。
SCHEMAS = {
    "products": {"product_id": "s32", "product_name": "s100", "category": "s20", "quantity_unit": "s8", "active_flag": "i"},
    "customers": {"customer_id": "s32", "signup_date": "d"},
    "orders": {"order_id": "s32", "customer_id": "s32", "order_date": "d", "recognized_date": "d?", "channel_code": "s8", "region_code": "s8", "order_status": "s16"},
    "order_items": {"order_item_id": "s32", "order_id": "s32", "line_number": "i", "product_id": "s32", "quantity": "i", "unit_list_price": "m2", "discount_amount": "m2", "unit_cost_snapshot": "m2"},
    "returns": {"return_id": "s32", "order_item_id": "s32", "refund_date": "d", "returned_quantity": "i", "recoverable_quantity": "i", "refund_amount": "m2", "cogs_reversal_amount": "m2", "reason_code": "s24"},
    "expenses": {"expense_id": "s32", "expense_date": "d", "department": "s8", "expense_category": "s24", "channel_code": "s8?", "region_code": "s8?", "amount": "m2", "source_system": "s32", "source_reference": "s64"},
    "budget_sales": {"budget_version": "s32", "month": "d", "product_id": "s32", "channel_code": "s8", "region_code": "s8", "budget_quantity": "i", "budget_net_unit_price": "m4", "budget_unit_cost": "m4", "budget_refund_amount": "m2", "budget_cogs_reversal_amount": "m2"},
    "budget_expenses": {"budget_version": "s32", "month": "d", "expense_category": "s24", "department": "s8", "channel_scope": "s8", "region_scope": "s8", "budget_amount": "m2"},
}
KEYS = {
    "products": ("product_id",), "customers": ("customer_id",), "orders": ("order_id",),
    "order_items": ("order_item_id",), "returns": ("return_id",), "expenses": ("expense_id",),
    "budget_sales": ("budget_version", "month", "product_id", "channel_code", "region_code"),
    "budget_expenses": ("budget_version", "month", "expense_category", "department", "channel_scope", "region_scope"),
}
SECONDARY = {"order_items": ("order_id", "line_number"), "expenses": ("source_system", "source_reference")}
CHANNELS = {"C01", "C02", "C03"}
REGIONS = {"R01", "R02", "R03", "R04"}
EXPENSES = {"marketing", "platform_commission", "logistics", "payroll", "administration"}
DEPARTMENTS = {"D01", "D02", "D03", "D04"}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def parse_row(table, raw):
    result = {}
    for field, kind in SCHEMAS[table].items():
        value = raw.get(field)
        nullable = kind.endswith("?")
        kind = kind.rstrip("?")
        if value is None or value == "":
            require(nullable, f"missing:{field}")
            result[field] = None
            continue
        try:
            if kind == "d":
                value = value if type(value) is date else date.fromisoformat(str(value))
            elif kind == "i":
                number = Decimal(str(value))
                require(number.is_finite() and number == number.to_integral_value() and abs(number) <= 2147483647, f"invalid_integer:{field}")
                value = int(number)
            elif kind.startswith("m"):
                value = Decimal(str(value))
                scale = int(kind[1:])
                require(value.is_finite() and value >= ZERO and value < Decimal(10) ** (18-scale), f"invalid_amount:{field}")
                require(value == value.quantize(Decimal(10) ** -scale), f"excess_precision:{field}")
            else:
                value = str(value).strip()
                require(bool(value) and len(value) <= int(kind[1:]), f"invalid_text:{field}")
        except (InvalidOperation, OverflowError, TypeError):
            raise ValueError(f"invalid_type:{field}") from None
        except ValueError as error:
            if ":" not in str(error):
                raise ValueError(f"invalid_type:{field}") from None
            raise
        result[field] = value
    return result


def key(table, row):
    return tuple(row[field] for field in KEYS[table])


def same_business_row(table, left, right):
    return all(left[field] == right[field] for field in SCHEMAS[table])


class Catalog:
    """父表索引与退款累计；只纳入已经接受的行。"""
    def __init__(self, records=None):
        self.rows = {table: {} for table in SCHEMAS}
        self.secondary = {table: {} for table in SECONDARY}
        self.refund_totals = {}
        for table in SCHEMAS:
            for row in (records or {}).get(table, []):
                self.add(table, row)

    def add(self, table, row):
        self.rows[table][key(table, row)] = row
        if table in SECONDARY:
            self.secondary[table][tuple(row[f] for f in SECONDARY[table])] = key(table, row)
        if table == "returns":
            total = self.refund_totals.setdefault(row["order_item_id"], [0, ZERO, ZERO])
            total[0] += row["returned_quantity"]
            total[1] += row["refund_amount"]
            total[2] += row["cogs_reversal_amount"]

    def validate(self, table, r):
        if table == "products":
            require(r["category"] in {"STORAGE", "CLEANING", "KITCHEN"} and r["quantity_unit"] == "件" and r["active_flag"] in {0, 1}, "invalid_product_codes")
        if table in {"orders", "budget_sales"}:
            require(r["channel_code"] in CHANNELS and r["region_code"] in REGIONS, "invalid_dimension_codes")
        if table == "orders":
            require((r["customer_id"],) in self.rows["customers"], "unknown_customer")
            require(r["order_status"] in {"completed", "pending", "cancelled"}, "invalid_status")
            if r["order_status"] == "completed":
                require(r["recognized_date"] is not None and r["recognized_date"] >= r["order_date"], "invalid_recognition_date")
            else:
                require(r["recognized_date"] is None, "unconfirmed_has_recognition_date")
            require(r["order_date"] >= self.rows["customers"][(r["customer_id"],)]["signup_date"], "order_before_signup")
        if table in {"order_items", "budget_sales"}:
            require((r["product_id"],) in self.rows["products"], "unknown_product")
        if table == "order_items":
            require((r["order_id"],) in self.rows["orders"], "unknown_order")
            require(r["quantity"] > 0 and r["line_number"] > 0, "nonpositive_quantity_or_line")
            require(r["discount_amount"] <= r["quantity"] * r["unit_list_price"], "discount_exceeds_sales")
        if table == "returns":
            item = self.rows["order_items"].get((r["order_item_id"],))
            require(item is not None, "unknown_sale_line")
            order = self.rows["orders"][(item["order_id"],)]
            require(order["order_status"] == "completed", "refund_on_unconfirmed_order")
            require(r["refund_date"] >= order["recognized_date"], "refund_before_sale")
            returned, recovered = r["returned_quantity"], r["recoverable_quantity"]
            require(0 <= recovered <= returned, "invalid_return_quantity")
            require(r["cogs_reversal_amount"] == recovered * item["unit_cost_snapshot"], "cost_reversal_mismatch")
            valid_reason = ((r["reason_code"] == "compensation" and returned == recovered == 0)
                            or (r["reason_code"] == "return_resalable" and returned > 0 and recovered > 0)
                            or (r["reason_code"] == "return_unsellable" and returned > 0 and recovered == 0))
            require(valid_reason, "invalid_return_reason")
            total = self.refund_totals.get(r["order_item_id"], [0, ZERO, ZERO])
            require(total[0] + returned <= item["quantity"], "cumulative_return_exceeds_quantity")
            require(total[1] + r["refund_amount"] <= item["quantity"] * item["unit_list_price"] - item["discount_amount"], "cumulative_refund_exceeds_sales")
            require(total[2] + r["cogs_reversal_amount"] <= item["quantity"] * item["unit_cost_snapshot"], "cumulative_reversal_exceeds_cost")
        if table in {"expenses", "budget_expenses"}:
            require(r["expense_category"] in EXPENSES and r["department"] in DEPARTMENTS, "invalid_expense_codes")
            if table == "expenses":
                require(r["channel_code"] in CHANNELS | {None} and r["region_code"] in REGIONS | {None}, "invalid_expense_scope")
            else:
                require(r["channel_scope"] in CHANNELS | {"ALL"} and r["region_scope"] in REGIONS | {"ALL"}, "invalid_expense_scope")
        if table.startswith("budget_"):
            require(r["month"].day == 1, "budget_month_not_first_day")
        if table == "budget_sales":
            require(r["budget_quantity"] >= 0, "negative_budget_quantity")
        if table in SECONDARY:
            secondary_key = tuple(r[f] for f in SECONDARY[table])
            existing = self.secondary[table].get(secondary_key)
            require(existing is None or existing == key(table, r), "business_unique_key_conflict")


def process_rows(table, raw_rows, catalog):
    accepted, rejected, skipped = [], [], 0
    for number, raw in enumerate(raw_rows, 1):
        try:
            row = parse_row(table, raw)
            old = catalog.rows[table].get(key(table, row))
            if old is not None:
                require(same_business_row(table, row, old), "business_id_conflict")
                skipped += 1
                continue
            catalog.validate(table, row)
            catalog.add(table, row)
            accepted.append(row)
        except ValueError as error:
            rejected.append({"row_number": number, "reason": str(error), "row": raw})
    return accepted, rejected, skipped
