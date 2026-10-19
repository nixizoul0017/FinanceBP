"""纯展示与下载辅助函数，不依赖Streamlit，不重复计算财务指标。

金额原值和CSV均保留Decimal精度；只有标签格式化与图表副本转为展示值。
明细表示已观察到的事件，period_is_complete说明该月是否完整。
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import io
import json
import re

import pandas as pd

from analysis.metrics import Filters, filter_dimensions, month_date, month_range, sum_decimal, subtract, ratio
from etl.common import encode

_UNITS = {"元": Decimal("1"), "万元": Decimal("10000")}
_VARIANCE_FIELDS = (
    "actual", "budget", "variance", "variance_rate", "completion_rate",
    "direction", "rate_unavailable_reason",
)
_MONEY_COLUMNS = {
    "sales_revenue", "refund_amount", "net_revenue", "sales_cost",
    "cogs_reversal_amount", "net_cost", "gross_margin", "expenses",
    "operating_profit", "average_selling_price", "average_order_value",
    "sales_amount_before_refund", "cogs_amount", "cost_reversal_amount",
    "amount", "observed_amount", "net_unit_price", "unit_cost",
    "actual", "budget", "variance",
}


def _unit_scale(unit):
    if unit not in _UNITS:
        raise ValueError("金额单位只支持元、万元")
    return _UNITS[unit]


def _is_missing(value):
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, (str, dict, list, tuple)):
        return False
    return bool(pd.isna(value))


def _number(value):
    if _is_missing(value):
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    if not number.is_finite():
        return None
    return number


def money_text(value, unit="元"):
    """金额标签，未知显示—；标签四舍五入不影响财务原值。"""
    scale = _unit_scale(unit)
    number = _number(value)
    if number is None:
        return "—"
    rendered = (number / scale).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # 避免很小的负数在标签上变成-0.00。
    if rendered == 0:
        rendered = abs(rendered)
    return f"{rendered:,.2f}"


def percent_text(value):
    """比例小数0.1显示10.00%；未知与无有效分母均显示—。"""
    number = _number(value)
    if number is None:
        return "—"
    rendered = (number * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rendered == 0:
        rendered = abs(rendered)
    return f"{rendered:,.2f}%"


def detail_tables(engine, month, filters=Filters()):
    """本月销售、退款以及独立的公司费用原始明细。

    退款按refund_date归月，通过销售业务键补原商品/渠道/区域；费用始终
    保持公司范围。部分月份仍可审阅已观察明细，但不能当作完整月合计。
    """
    month = month_date(month)
    engine.validate_filters(filters)
    sales_source = engine.tables["sales"]
    sales = filter_dimensions(sales_source, filters)
    sales = sales[sales["revenue_date"].map(lambda day: day.replace(day=1)).eq(month)].copy(deep=True)

    refund_source = engine.tables["refunds"]
    refunds = refund_source[refund_source["refund_date"].map(lambda day: day.replace(day=1)).eq(month)].copy(deep=True)
    origin_fields = ["entity_id", "sale_line_id", "order_id", "revenue_date", *engine.dimension_ids]
    refunds = refunds.merge(sales_source[origin_fields], on=["entity_id", "sale_line_id"], how="left", validate="many_to_one")
    refunds = filter_dimensions(refunds, filters).copy(deep=True)

    expenses = engine.tables["expenses"]
    expenses = expenses[expenses["expense_date"].map(lambda day: day.replace(day=1)).eq(month)].copy(deep=True)
    tables = {"sales": sales, "refunds": refunds, "company_expenses": expenses}
    for name, frame in tables.items():
        scope = "company_expenses" if name == "company_expenses" else "company_sales" if filters.is_company else "sales_dimensions"
        source_available = engine.available["expenses" if name == "company_expenses" else name]
        complete = engine.is_complete(month) and source_available
        frame["month"] = month
        frame["scope"] = scope
        frame["source_available"] = source_available
        frame["period_is_complete"] = complete
        frame.attrs.update(entity_id=engine.entity_id, month=month, scope=scope,
                           filters=Filters().as_dict() if name == "company_expenses" else filters.as_dict(),
                           source_available=source_available,
                           period_is_complete=complete,
                           calendar_is_complete=engine.is_complete(month))
        tables[name] = frame.reset_index(drop=True)
    return tables


def monthly_trend(engine, start, end, filters=Filters()):
    """沿用统一引擎的完整月份和空值；不把未加载月份填零。"""
    return engine.monthly(start, end, filters=filters).copy(deep=True)


def chart_frame(frame, amount_columns=None, unit="元"):
    """为图表建立float副本，保留身份、日期与维度；未知仍为空点。

    默认将Decimal列转为float，已知金额列按单位换算，比例不会按万元
    换算。也可明确指定金额列，仅转换这些列。下载应始终传原表。
    """
    scale = _unit_scale(unit)
    columns = list(amount_columns) if amount_columns is not None else [
        column for column in frame if any(isinstance(value, Decimal) for value in frame[column])]
    if len(columns) != len(set(columns)) or "month" in columns:
        raise ValueError("图表金额列重复或含月份列")
    if not set(columns).issubset(frame.columns):
        raise ValueError("图表金额列不存在")
    result = frame.copy(deep=True)
    for column in columns:
        divisor = scale if amount_columns is not None or column in _MONEY_COLUMNS else Decimal("1")
        result[column] = pd.Series([
            None if _number(value) is None else float(_number(value) / divisor)
            for value in result[column]
        ], index=result.index, dtype=object)
    return result


def budget_rows(comparison):
    """将销售或费用预算比较展开为可显示/下载的逐指标记录表。

    接收sales_budget_comparison或expense_budget_comparison的结果，调用方
    分开显示两个范围；保留缺预算、真实零、方向和空比率原义。
    """
    rows = []
    for detail in comparison.get("details", []):
        base = {key: value for key, value in detail.items() if key != "metrics" and key not in _VARIANCE_FIELDS}
        base.update(budget_version=comparison["version"], scope=comparison["scope"], comparison_status=comparison["status"])
        if "metrics" in detail:
            for metric, values in detail["metrics"].items():
                rows.append({**base, "metric": metric, **values})
        else:
            rows.append({**base, "metric": "expenses", **{field: detail.get(field) for field in _VARIANCE_FIELDS}})
    columns = ["budget_version", "scope", "comparison_status", "month", "product_id", "channel_id", "region_id", "expense_category", "department", "channel_scope", "region_scope", "has_actual_record", "actual_is_complete", "has_budget", "metric", *_VARIANCE_FIELDS]
    return pd.DataFrame(rows, columns=columns, dtype=object)


def _safe_text(text):
    # Excel可能忽略开头的空白/控制字符。只处理文本，不改变Decimal负金额。
    beginning = text.lstrip(" \t\r\n\v\f\x00")
    if beginning.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def _csv_cell(value):
    if _is_missing(value):
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return _safe_text(json.dumps(value, ensure_ascii=False, sort_keys=True, default=encode))
    return _safe_text(str(value)) if isinstance(value, str) else str(value)


def csv_bytes(frame):
    """Excel可直接读的UTF-8 BOM CSV；精确金额、空字段和文本公式保护。"""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([_safe_text(str(column)) for column in frame.columns])
    for row in frame.itertuples(index=False, name=None):
        writer.writerow([_csv_cell(value) for value in row])
    return buffer.getvalue().encode("utf-8-sig")


def _filename_part(value, limit=56):
    text = str(value)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .") or "unknown"
    if re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", cleaned.split(".", 1)[0]):
        cleaned = "_" + cleaned
    if len(cleaned) > limit:
        cleaned = cleaned[:limit-9] + "_" + hashlib.sha256(text.encode()).hexdigest()[:8]
    return cleaned


def safe_export_name(entity, month, kind, filters=Filters(), *, version=None, end=None, fingerprint=None):
    """文件名注明企业、月份/范围、内容、筛选及可选预算版本/快照。

    公司费用/费用预算/公司汇总固定标记公司范围，不继承销售筛选。
    """
    if not isinstance(filters, Filters):
        raise ValueError("筛选需要使用Filters")
    month = month_date(month)
    period = month.strftime("%Y-%m")
    if end is not None:
        months = month_range(month, end)
        period += "_to_" + months[-1].strftime("%Y-%m")
    if kind in {"company_expenses", "expense_budget", "company_summary"}:
        filters = Filters()
    scope = "company" if filters.is_company else "__".join(
        prefix + "-" + ("+".join(values) if values is not None else "ALL")
        for prefix, values in zip(("products", "channels", "regions"), (filters.products, filters.channels, filters.regions)))
    if filters.dimensions:
        scope += '__dims-'+hashlib.sha256(repr(filters.dimensions).encode()).hexdigest()[:12]
    parts = [entity, period, kind, scope]
    if version is not None:
        parts.append("version-" + str(version))
    if fingerprint is not None:
        parts.append("snapshot-" + str(fingerprint)[:12])
    name = "__".join(_filename_part(value) for value in parts)
    if len(name) > 200:
        name = name[:187] + "__" + hashlib.sha256(name.encode()).hexdigest()[:10]
    return name + ".csv"


def forecast_groups(frame,by):
    """Keep missing amounts unknown when combining forecast cells."""
    by=tuple(by)
    if not by or len(set(by))!=len(by) or not set(by).issubset(frame.columns):
        raise ValueError('预测分组字段无效')
    fields=('sales_revenue','sales_cost','refund_amount','cogs_reversal_amount')
    rows=[]
    for key,group in frame.groupby(['month',*by],dropna=False,sort=True):
        values={field:sum_decimal(group[field]) for field in fields}
        values['net_revenue']=subtract(values['sales_revenue'],values['refund_amount'])
        values['net_cost']=subtract(values['sales_cost'],values['cogs_reversal_amount'])
        values['gross_margin']=subtract(values['net_revenue'],values['net_cost'])
        values['gross_margin_rate']=ratio(values['gross_margin'],values['net_revenue'])
        rows.append({**dict(zip(('month',*by),key)),**values})
    return pd.DataFrame(rows,columns=['month',*by,*fields,'net_revenue','net_cost','gross_margin','gross_margin_rate'],dtype=object)
