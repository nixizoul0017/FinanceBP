from __future__ import annotations

import calendar
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from etl.common import ZERO
from etl.sources import CONTRACT, FACT_KEYS, Facts
from etl.dimensions import BUILTINS, MISSING, display

DIMENSIONS = ("product_id", "channel_id", "region_id")
AMOUNTS = ("sales_revenue", "refund_amount", "net_revenue", "sales_cost", "cogs_reversal_amount", "net_cost", "gross_margin")
COUNTS = ("sales_quantity", "returned_quantity", "net_quantity", "confirmed_orders", "confirmed_lines")
METRICS = COUNTS + AMOUNTS + ("gross_margin_rate", "average_selling_price", "average_order_value", "expenses", "operating_profit", "expense_rate", "operating_margin_rate")
EVENT_COLUMNS = ("entity_id", "month", *DIMENSIONS, "sale_line_id", "sale_order_id", "event_type", "sales_quantity", "returned_quantity", "sales_revenue", "refund_amount", "sales_cost", "cogs_reversal_amount", "cost_complete")


def month_date(value):
    if isinstance(value, str):
        value = date.fromisoformat(value + "-01" if len(value) == 7 else value)
    if type(value) is not date or value.day != 1:
        raise ValueError("月份使用YYYY-MM或每月1日的date")
    return value


def shift_month(month, offset):
    month = month_date(month)
    serial = month.year*12 + month.month-1 + offset
    return date(serial//12, serial % 12+1, 1)


def month_end(month):
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def month_range(start, end):
    start, end = month_date(start), month_date(end)
    if start > end:
        raise ValueError("开始月份不能晚于结束月份")
    months = []
    while start <= end:
        months.append(start)
        start = shift_month(start, 1)
    return months


def ratio(numerator, denominator):
    # 返回比例小数，0.1表示10%；仅在正分母下显示常规比率。
    if numerator is None or denominator is None or denominator <= ZERO:
        return None
    return Decimal(str(numerator)) / Decimal(str(denominator))


def subtract(left, right):
    return None if left is None or right is None else left-right


def sum_decimal(values):
    values = list(values)
    return None if any(pd.isna(value) for value in values) else sum(values, ZERO)


def selection(values):
    if values is None:
        return None
    if isinstance(values, str):
        values = (values,)
    values = tuple(sorted(set(values)))
    if not values or any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("筛选为空或包含非法编码；全部使用None")
    return values


@dataclass(frozen=True)
class Filters:
    products: tuple[str, ...] | None = None
    channels: tuple[str, ...] | None = None
    regions: tuple[str, ...] | None = None
    dimensions: tuple | dict = ()

    def __post_init__(self):
        for field in ("products", "channels", "regions"):
            object.__setattr__(self, field, selection(getattr(self, field)))
        values = dict(self.dimensions)
        for field, alias in zip(DIMENSIONS, ('products','channels','regions')):
            if field in values:
                chosen = selection(values.pop(field))
                if getattr(self, alias) is not None and getattr(self, alias) != chosen:
                    raise ValueError('标准分类筛选冲突')
                object.__setattr__(self, alias, chosen)
        if any(not isinstance(field,str) or not field for field in values):
            raise ValueError('分类编号无效')
        object.__setattr__(self, 'dimensions', tuple(sorted((field, selection(value)) for field,value in values.items() if value is not None)))

    @property
    def items(self):
        return (*zip(DIMENSIONS, (self.products,self.channels,self.regions)), *self.dimensions)

    @classmethod
    def from_dict(cls, value):
        return cls(value.get('products'), value.get('channels'), value.get('regions'), value.get('dimensions', {}))

    @property
    def is_company(self):
        return self.products is self.channels is self.regions is None and not self.dimensions

    def as_dict(self):
        return {"products": self.products, "channels": self.channels, "regions": self.regions, **({'dimensions':dict(self.dimensions)} if self.dimensions else {})}


def filter_dimensions(frame, filters):
    result = frame
    for field, values in filters.items:
        if values is not None:
            if field not in result:
                raise ValueError('当前数据不支持分类筛选：'+field)
            result = result[result[field].isin(values)]
    return result


class FinancialEngine:
    """已校验标准事实的只读快照。所有金额用Decimal，中间值不四舍五入。"""

    def __init__(self, facts: Facts):
        self.metadata = deepcopy(facts.metadata)
        self.entity_id = self.metadata["entity_id"]
        self.registry = deepcopy(self.metadata.get('dimension_registry', [{'id':field,'label':label,'names':{}} for field,label in BUILTINS.items()]))
        self.dimension_ids = tuple(entry['id'] for entry in self.registry)
        self.selectable_dimension_ids = tuple(self.metadata.get('visible_dimensions',self.dimension_ids))
        self.dimension_labels = {entry['id']:entry['label'] for entry in self.registry}
        if self.metadata.get("rule_version") != "sales_v1":
            raise ValueError("财务模块只支持已验证的sales_v1口径")
        self.tables = {name: frame.copy(deep=True) for name, frame in facts.tables.items()}
        for name, columns in CONTRACT.items():
            frame = self.tables.get(name)
            if frame is None or not set(columns).issubset(frame.columns):
                raise ValueError(f"标准字段不完整:{name}")
            if not frame.empty and not frame["entity_id"].eq(self.entity_id).all():
                raise ValueError("一次计算只允许一个企业，请分别建立财务快照")
            if name == 'sales_budget' and self.metadata.get('budget_dimensions'):
                duplicate = any(group.duplicated(['entity_id','budget_version','month',*self.budget_dimensions(version)]).any() for version,group in frame.groupby('budget_version'))
            else:
                duplicate = frame.duplicated(FACT_KEYS[name]).any()
            if duplicate:
                raise ValueError(f"重复标准业务键:{name}")
        availability = self.metadata.get("data_availability", {})
        self.available = {name: bool(availability.get(name, True)) for name in CONTRACT}
        if not self.available["sales"]:
            raise ValueError("缺少销售数据来源，不能确认完整实际")
        coverage = self.metadata["coverage"]
        self.complete_start = month_date(coverage["complete_start"])
        self.complete_end = date.fromisoformat(coverage["complete_end"])
        if self.complete_end < self.complete_start or self.complete_end != month_end(self.complete_end.replace(day=1)):
            raise ValueError("完整覆盖范围必须按完整月声明")
        self.incomplete_months = {month_date(value) for value in coverage.get("incomplete_months", [])}
        self._selected = {}
        self.events = self._build_events()
        self.expenses = self.tables["expenses"].copy()
        self.expenses["month"] = self.expenses["expense_date"].map(lambda day: day.replace(day=1))

    def budget_dimensions(self, version):
        return tuple(self.metadata.get('budget_dimensions', {}).get(version, DIMENSIONS))

    def dimension_text(self, field, value):
        entry = next((x for x in self.registry if x['id']==field), {})
        name = entry.get('names', {}).get(value)
        return f'{name} · {value}' if name and name != value else display(value)

    def dimension_values(self,field):
        values=set(self.tables['sales'][field])
        budget=self.tables['sales_budget']
        if field in budget:
            for version,rows in budget.groupby('budget_version'):
                if field in self.budget_dimensions(version):
                    values.update(rows[field])
        return sorted(values)

    def _build_events(self):
        records, sale_lookup = [], {}
        for row in self.tables["sales"].to_dict("records"):
            sale_lookup[(row["entity_id"], row["sale_line_id"])] = row
            cost = None if pd.isna(row["cogs_amount"]) else row["cogs_amount"]
            records.append({"entity_id": row["entity_id"], "month": row["revenue_date"].replace(day=1), **{field: row[field] for field in self.dimension_ids}, "sale_line_id": row["sale_line_id"], "sale_order_id": row["order_id"], "event_type": "sale", "sales_quantity": row["quantity"], "returned_quantity": 0, "sales_revenue": row["sales_amount_before_refund"], "refund_amount": ZERO, "sales_cost": cost, "cogs_reversal_amount": ZERO, "cost_complete": cost is not None})
        for row in self.tables["refunds"].to_dict("records"):
            sale = sale_lookup.get((row["entity_id"], row["sale_line_id"]))
            if sale is None:
                raise ValueError("退款引用未知销售明细")
            records.append({"entity_id": row["entity_id"], "month": row["refund_date"].replace(day=1), **{field: sale[field] for field in self.dimension_ids}, "sale_line_id": row["sale_line_id"], "sale_order_id": None, "event_type": "refund", "sales_quantity": 0, "returned_quantity": row["returned_quantity"], "sales_revenue": ZERO, "refund_amount": row["refund_amount"], "sales_cost": ZERO, "cogs_reversal_amount": row["cost_reversal_amount"], "cost_complete": not pd.isna(sale["cogs_amount"])})
        return pd.DataFrame(records, columns=[*EVENT_COLUMNS, *[field for field in self.dimension_ids if field not in DIMENSIONS]])

    def validate_filters(self, filters):
        if not isinstance(filters, Filters):
            raise ValueError("筛选需要使用Filters")
        for field, values in filters.items:
            if values is not None:
                if field not in self.dimension_ids:
                    raise ValueError("未知分类："+field)
                known = set(self.dimension_values(field))
                if not set(values).issubset(known):
                    raise ValueError(f"未知筛选编码:{field}")

    def selected_events(self, filters=Filters()):
        self.validate_filters(filters)
        if filters not in self._selected:
            self._selected[filters] = filter_dimensions(self.events, filters)
        return self._selected[filters].copy()

    def is_complete(self, month):
        month = month_date(month)
        return self.complete_start <= month and month_end(month) <= self.complete_end and month not in self.incomplete_months

    def period_events(self, start, end, filters=Filters()):
        months = month_range(start, end)
        events = self.selected_events(filters)
        return events[events["month"].between(months[0], months[-1])].copy()

    def _aggregate(self, events):
        result = {field: sum_decimal(events[field]) for field in ("sales_revenue", "refund_amount", "sales_cost", "cogs_reversal_amount")}
        result["sales_quantity"] = int(events["sales_quantity"].sum())
        result["returned_quantity"] = int(events["returned_quantity"].sum()) if self.available["refunds"] else None
        result["net_quantity"] = subtract(result["sales_quantity"], result["returned_quantity"])
        result["confirmed_orders"] = int(events.loc[events["event_type"] == "sale", "sale_order_id"].nunique())
        result["confirmed_lines"] = int(events["event_type"].eq("sale").sum())
        result["average_selling_price"] = ratio(result["sales_revenue"], result["sales_quantity"])
        result["average_order_value"] = ratio(result["sales_revenue"], result["confirmed_orders"])
        issues = []
        if not self.available["refunds"]:
            result["refund_amount"] = result["cogs_reversal_amount"] = None
            issues.append("refund_source_missing")
        result["net_revenue"] = subtract(result["sales_revenue"], result["refund_amount"])
        result["net_cost"] = subtract(result["sales_cost"], result["cogs_reversal_amount"])
        if not events["cost_complete"].all():
            result["net_cost"] = None
            issues.append("historic_cost_missing")
        result["gross_margin"] = subtract(result["net_revenue"], result["net_cost"])
        result["gross_margin_rate"] = ratio(result["gross_margin"], result["net_revenue"])
        return result, issues

    def _summary(self, events, start, end, filters, company=False):
        months = month_range(start, end)
        observed, issues = self._aggregate(events)
        fees = self.expenses[self.expenses["month"].between(months[0], months[-1])]
        observed.update(expenses=None, operating_profit=None, expense_rate=None, operating_margin_rate=None)
        if company:
            if self.available["expenses"]:
                observed["expenses"] = sum_decimal(fees["amount"])
                observed["operating_profit"] = subtract(observed["gross_margin"], observed["expenses"])
                observed["expense_rate"] = ratio(observed["expenses"], observed["net_revenue"])
                observed["operating_margin_rate"] = ratio(observed["operating_profit"], observed["net_revenue"])
            else:
                issues.append("expense_source_missing")
        missing = [month for month in months if not self.is_complete(month)]
        complete = not missing
        return {"entity_id": self.entity_id, "start_month": months[0], "end_month": months[-1], "scope": "company" if company else "sales_dimensions", "filters": filters.as_dict(), "is_complete": complete, "actual_status": "complete" if complete else "partial" if not events.empty or (company and not fees.empty) else "not_loaded", "missing_months": missing, "data_issues": issues, "has_activity": bool(not events.empty or (company and not fees.empty)), **(observed if complete else {field: None for field in METRICS}), "observed_metrics": observed if not complete else None}

    def summary(self, start, end=None, filters=Filters()):
        end = start if end is None else end
        events = self.period_events(start, end, filters)
        return self._summary(events, start, end, filters, company=filters.is_company)

    def monthly(self, start, end, filters=Filters()):
        events = self.period_events(start, end, filters)
        groups = {month: group for month, group in events.groupby("month", sort=False)}
        empty = events.iloc[:0]
        return pd.DataFrame([{"month": month, **self._summary(groups.get(month, empty), month, month, filters, company=filters.is_company)} for month in month_range(start, end)], dtype=object)

    def dimensions(self, start, end=None, by="product_id", filters=Filters()):
        end = start if end is None else end
        fields = (by,) if isinstance(by, str) else tuple(by)
        if not fields or len(set(fields)) != len(fields) or not set(fields).issubset(self.dimension_ids):
            raise ValueError("分组只能使用已确认且不重复的分类")
        events = self.period_events(start, end, filters)
        result = []
        for key, group in events.groupby(list(fields), sort=True):
            key = key if isinstance(key, tuple) else (key,)
            result.append({**dict(zip(fields, key)), **self._summary(group, start, end, filters, company=False)})
        return pd.DataFrame(result, columns=[*fields, "entity_id", "start_month", "end_month", "scope", "filters", "is_complete", "actual_status", "missing_months", "data_issues", "has_activity", *METRICS, "observed_metrics"], dtype=object)

    def expense_details(self, start, end=None):
        months = month_range(start, start if end is None else end)
        fees = self.expenses[self.expenses["month"].between(months[0], months[-1])]
        fields = ["expense_category", "department", "channel_scope", "region_scope"]
        result = []
        complete = all(self.is_complete(month) for month in months) and self.available["expenses"]
        for key, group in fees.groupby(fields, sort=True):
            observed = sum_decimal(group["amount"])
            result.append({**dict(zip(fields, key)), "scope": "company_expenses", "amount": observed if complete else None, "observed_amount": None if complete else observed})
        return pd.DataFrame(result, columns=[*fields, "scope", "amount", "observed_amount"], dtype=object)
