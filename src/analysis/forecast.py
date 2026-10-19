"""截至时点的零泄漏基准预测；预算与模拟预设不参与模型拟合。"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
import hashlib
import json

from etl.common import ZERO, encode
from etl.dimensions import MISSING
from .metrics import DIMENSIONS, Filters, filter_dimensions, month_date, month_end, month_range, ratio, shift_month, subtract, sum_decimal
from .pvm import decimal_value

METHODS = ("last_year_same_month", "recent_mean", "driver_based")
METHOD_LABELS = {"last_year_same_month": "上年同月", "recent_mean": "近期均值", "driver_based": "业务驱动"}
DRIVERS = ("sales_quantity", "sales_revenue", "sales_cost", "refund_amount", "cogs_reversal_amount")
FINANCIALS = ("net_revenue", "net_cost", "gross_margin", "expenses", "operating_profit")
FEE_KEYS = ("expense_category", "department", "channel_scope", "region_scope")


def difference(left,right):
    with localcontext() as context:
        context.prec=60
        return subtract(left,right)


def quantity(value):
    return int(decimal_value(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def cents(value):
    return None if value is None else decimal_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def known_sum(values):
    with localcontext() as context:
        context.prec = 60
        return sum_decimal(values)


def scaled(value, multiplier):
    return None if value is None or multiplier is None else decimal_value(Fraction(value)*Fraction(multiplier))


def divide(left, right):
    return None if left is None or right is None or right <= 0 else Fraction(left)/Fraction(right)


class History:
    """按月聚合后按截止日截断；键集合、指纹、费用均仅取当时已知范围。"""
    def __init__(self, engine):
        self.engine = engine
        self.dimensions = tuple(engine.metadata.get("forecast_dimensions", engine.dimension_ids))
        self.cells = {}
        for key, group in engine.events.groupby(["month", *self.dimensions], sort=True):
            row = {field: known_sum(group[field]) for field in DRIVERS[1:]}
            row["sales_quantity"] = int(group["sales_quantity"].sum())
            if not group["cost_complete"].all():
                row["sales_cost"] = None
            if not engine.available["refunds"]:
                row["refund_amount"] = row["cogs_reversal_amount"] = None
            self.cells[key] = row
        self.fees = {key: known_sum(group["amount"]) for key, group in engine.expenses.groupby(["month", *FEE_KEYS], sort=True)}

    def snapshot(self, cutoff):
        return Training(self, cutoff)


class Training:
    def __init__(self, history, cutoff):
        self.cutoff = month_date(cutoff)
        self.engine = history.engine
        self.dimensions = history.dimensions
        if not self.engine.is_complete(self.cutoff):
            raise ValueError("预测截止月必须已有完整实际")
        self.cells = {key: deepcopy(row) for key, row in history.cells.items() if key[0] <= self.cutoff}
        self.fees = {key: value for key, value in history.fees.items() if key[0] <= self.cutoff}
        self.keys = sorted({key[1:] for key in self.cells})
        self.fee_keys = sorted({key[1:] for key in self.fees})
        self.flags = {name: self.engine.available[name] for name in ("sales", "refunds", "expenses")}
        fingerprint = {"entity": self.engine.entity_id, "rule": self.engine.metadata["rule_version"], "start": self.engine.complete_start,
            "cutoff": self.cutoff, "incomplete_months": sorted(month for month in self.engine.incomplete_months if month <= self.cutoff), "available": self.flags,
            "sales": [{"key": key, **row} for key, row in sorted(self.cells.items())], "fees": [{"key": key, "amount": value} for key, value in sorted(self.fees.items())]}
        self.fingerprint = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, default=encode, ensure_ascii=False).encode()).hexdigest()

    def complete(self, months):
        return all(month <= self.cutoff and self.engine.is_complete(month) for month in months)

    def cell(self, month, key):
        return self.cells.get((month, *key), {field: None if field in ("refund_amount", "cogs_reversal_amount") and not self.flags["refunds"] else ZERO for field in DRIVERS})

    def sums(self, months, key):
        return {field: known_sum(self.cell(month, key)[field] for month in months) for field in DRIVERS}

    def fee(self, month, key):
        return self.fees.get((month, *key), ZERO) if self.flags["expenses"] else None

    def actual(self, month):
        rows = [{"month": month, **dict(zip(self.dimensions, key[1:])), **row} for key, row in self.cells.items() if key[0] == month]
        if len(self.engine.dimension_ids) > 3:
            rows = []
            events = self.engine.events[self.engine.events['month'].eq(month)]
            for key, group in events.groupby(list(self.engine.dimension_ids), sort=True):
                values = {field: known_sum(group[field]) for field in DRIVERS}
                if not group['cost_complete'].all():
                    values['sales_cost'] = None
                if not self.flags['refunds']:
                    values['refund_amount'] = values['cogs_reversal_amount'] = None
                rows.append({'month':month, **dict(zip(self.engine.dimension_ids,key)), **values})
        fees = [{"month": month, **dict(zip(FEE_KEYS, key[1:])), "amount": amount} for key, amount in self.fees.items() if key[0] == month]
        return {"month": month, "kind": "actual", "available": self.complete([month]), "reason": None if self.complete([month]) else "actual_history_incomplete", "sales": rows, "expense_rows": fees}


def period_summary(period, flags, filters=Filters(), scope_known=True):
    rows = period["sales"]
    if not filters.is_company:
        rows = [row for row in rows if all(values is None or row.get(field) in values for field, values in filters.items)]
    unsupported = [field for field, values in filters.items if values is not None and field in period.get("unavailable_dimensions", [])]
    available = period["available"] and scope_known and not unsupported
    values = {field: known_sum(row[field] for row in rows) if available else None for field in DRIVERS}
    if values["sales_quantity"] is not None:
        values["sales_quantity"] = int(values["sales_quantity"])
    if not flags["refunds"]:
        values["refund_amount"] = values["cogs_reversal_amount"] = None
    values.update(net_revenue=difference(values["sales_revenue"], values["refund_amount"]), net_cost=difference(values["sales_cost"], values["cogs_reversal_amount"]))
    values["gross_margin"] = difference(values["net_revenue"], values["net_cost"])
    values["expenses"] = known_sum(row["amount"] for row in period["expense_rows"]) if filters.is_company and available and flags["expenses"] else None
    values["operating_profit"] = difference(values["gross_margin"], values["expenses"]) if filters.is_company else None
    values["gross_margin_rate"] = ratio(values["gross_margin"], values["net_revenue"])
    return {"month": period["month"], "kind": period["kind"], "is_available": available, "reason": "dimension_history_incomplete" if unsupported else period["reason"] if scope_known else "scope_not_observed_before_cutoff", **values}


def predict(training, targets, method="recent_mean", window=3):
    if method not in METHODS or window not in (1, 3, 6):
        raise ValueError("预测方法或窗口不支持")
    targets = [month_date(month) for month in targets]
    if any(month <= training.cutoff for month in targets):
        raise ValueError("预测月份必须晚于截止月")
    recent = [shift_month(training.cutoff, -offset) for offset in reversed(range(window))]
    prior = [shift_month(month, -12) for month in recent]
    features = {key: (training.sums(recent,key),training.sums(prior,key)) for key in training.keys}
    recent_company = {field: known_sum(features[key][0][field] for key in training.keys) for field in ("sales_quantity","sales_revenue")}
    periods = []
    for month in targets:
        seasonal = shift_month(month, -12)
        required = [seasonal] if method == "last_year_same_month" else recent if method == "recent_mean" else [*recent, *prior, seasonal]
        available = training.complete(required)
        period = {"month": month, "kind": "forecast", "available": available, "reason": None if available else "model_history_incomplete", "sales": [], "expense_rows": []}
        if len(training.engine.dimension_ids)>3:
            observed = training.engine.events
            observed = observed[observed["month"].isin(required) & (observed["month"]<=training.cutoff)]
            period["unavailable_dimensions"] = [field for field in training.engine.dimension_ids if field not in training.dimensions or (field not in DIMENSIONS and observed[field].eq(MISSING).any())]
        if not available:
            periods.append(period)
            continue
        for key in training.keys:
            current, previous = features[key]
            seasonal_row = training.cell(seasonal,key)
            if method == "last_year_same_month":
                q = quantity(seasonal_row["sales_quantity"])
                revenue, cost = seasonal_row["sales_revenue"], seasonal_row["sales_cost"]
                refund, reversal = seasonal_row["refund_amount"], seasonal_row["cogs_reversal_amount"]
            else:
                raw_q = Fraction(current["sales_quantity"])/window
                if method == "driver_based":
                    growth = divide(current["sales_quantity"], previous["sales_quantity"])
                    if current["sales_quantity"] == 0:
                        raw_q = Fraction(0)
                    elif growth is not None and seasonal_row["sales_quantity"] > 0:
                        raw_q = Fraction(seasonal_row["sales_quantity"])*min(Fraction(18,10),max(Fraction(1,2),growth))
                q = quantity(raw_q)
                source = current
                unit_price = divide(source["sales_revenue"], source["sales_quantity"])
                unit_cost = divide(source["sales_cost"], source["sales_quantity"])
                revenue = ZERO if q == 0 else scaled(q, unit_price)
                cost = ZERO if q == 0 else scaled(q, unit_cost)
                mean_revenue = scaled(current["sales_revenue"], Fraction(1,window))
                exposure = divide(revenue, mean_revenue) if mean_revenue is not None and mean_revenue > 0 else Fraction(1)
                refund = scaled(current["refund_amount"], Fraction(1,window)*exposure) if exposure is not None else None
                reversal = scaled(current["cogs_reversal_amount"], Fraction(1,window)*exposure) if exposure is not None else None
            period["sales"].append({"month": month, **dict(zip(training.dimensions, key)), "sales_quantity": q,
                "net_unit_price": decimal_value(divide(revenue,q)), "unit_cost": decimal_value(divide(cost,q)),
                "sales_revenue": revenue, "sales_cost": cost, "refund_amount": cents(refund), "cogs_reversal_amount": cents(reversal)})
        predicted = period_summary(period, training.flags)
        revenue_scale = divide(predicted["sales_revenue"], scaled(recent_company["sales_revenue"],Fraction(1,window))) if recent_company["sales_revenue"] > 0 else Fraction(1)
        quantity_scale = divide(predicted["sales_quantity"], scaled(recent_company["sales_quantity"],Fraction(1,window))) if recent_company["sales_quantity"] > 0 else Fraction(1)
        for key in training.fee_keys:
            fee = training.fee(seasonal,key) if method == "last_year_same_month" else scaled(known_sum(training.fee(m,key) for m in recent),Fraction(1,window))
            if method == "driver_based" and key[0] in ("platform_commission","logistics"):
                fee = scaled(fee,revenue_scale if key[0] == "platform_commission" else quantity_scale)
            period["expense_rows"].append({"month": month, **dict(zip(FEE_KEYS,key)), "amount": cents(fee)})
        periods.append(period)
    return periods


def accuracy(pairs):
    pairs = [(actual,forecast) for actual,forecast in pairs if actual is not None and forecast is not None]
    absolute = known_sum(abs(difference(forecast,actual)) for actual,forecast in pairs)
    denominator = known_sum(abs(actual) for actual,_ in pairs)
    return {"n": len(pairs), "mae": decimal_value(Fraction(absolute)/len(pairs)) if pairs else None,
        "wape": decimal_value(divide(absolute,denominator)), "bias": decimal_value(Fraction(known_sum(difference(f,a) for a,f in pairs))/len(pairs)) if pairs else None}


def backtest(history, as_of, window=3, primary_metric="net_revenue"):
    as_of = month_date(as_of)
    fields = ("net_revenue","gross_margin","operating_profit")
    if primary_metric not in fields:
        raise ValueError("回测目标仅支持净收入、毛利或经营利润")
    details = []
    origins = []
    evaluation = history.snapshot(as_of)
    for origin in month_range(history.engine.complete_start, as_of):
        if origin.month not in (3,6,9,12) or shift_month(origin,3)>as_of or not history.engine.is_complete(origin):
            continue
        training = history.snapshot(origin)
        targets = [shift_month(origin,h) for h in (1,2,3)]
        recent = [shift_month(origin,-offset) for offset in range(window)]
        required = [*recent, *[shift_month(m,-12) for m in recent], *[shift_month(m,-12) for m in targets]]
        if not training.complete(required) or not all(history.engine.is_complete(m) for m in targets):
            continue
        origins.append(origin)
        for method in METHODS:
            for horizon, period in enumerate(predict(training,targets,method,window),1):
                predicted = period_summary(period,training.flags)
                actual = period_summary(evaluation.actual(period["month"]),evaluation.flags)
                details.append({"origin": origin,"target_month": period["month"],"horizon": horizon,"method": method,"training_fingerprint": training.fingerprint,
                    **{field: {"actual": actual[field],"forecast": predicted[field],"error": difference(predicted[field],actual[field])} for field in fields}})
    scores = []
    for field in fields:
        valid = {(row["origin"],row["target_month"]) for row in details if all(other[field]["actual"] is not None and other[field]["forecast"] is not None for other in details if (other["origin"],other["target_month"])==(row["origin"],row["target_month"]))}
        for method in METHODS:
            rows = [row for row in details if row["method"]==method and (row["origin"],row["target_month"]) in valid]
            scores.append({"method": method,"metric": field,**accuracy((row[field]["actual"],row[field]["forecast"]) for row in rows)})
    choices = [row for row in scores if row["metric"]==primary_metric and row["n"]>=6 and row["wape"] is not None]
    chosen = min(choices,key=lambda row:(row["wape"],METHODS.index(row["method"]))) if choices else None
    return {"origins": origins,"horizons": [1,2,3],"primary_metric": "company_"+primary_metric,"selection_method": chosen["method"] if chosen else "recent_mean",
        "selection_reason": "lowest_paired_wape" if chosen else "insufficient_paired_history_fallback", "scores": scores,"details": details}


def forecast_base(engine, cutoff, method="auto", window=3, version="B2026_V1", primary_metric="net_revenue"):
    if engine.metadata.get("semantics",{}).get("quantity_unit") != "件":
        raise ValueError("预测需要已确认的件数口径")
    if method not in (*METHODS,"auto") or window not in (1,3,6):
        raise ValueError("预测方法或窗口不支持")
    from .comparison import _validate_version
    _validate_version(engine,version)
    history = History(engine)
    training = history.snapshot(cutoff)
    cutoff = training.cutoff
    targets = month_range(shift_month(cutoff,1),date(cutoff.year,12,1)) if cutoff.month<12 else []
    evaluation = backtest(history,cutoff,window,primary_metric)
    chosen = evaluation["selection_method"] if method == "auto" else method
    actual = [training.actual(month) for month in month_range(date(cutoff.year,1,1),cutoff)]
    predicted = predict(training,targets,chosen,window)
    budgets = {}
    for name in ("sales_budget","expense_budget"):
        frame = engine.tables[name]
        budgets[name] = frame[frame["month"].between(date(cutoff.year,1,1),date(cutoff.year,12,1)) & frame["budget_version"].eq(version)].to_dict("records")
    return {"metadata": {"model_version": "forecast_v1", "entity_id": engine.entity_id,"rule_version": engine.metadata["rule_version"],"source_fingerprint": engine.metadata.get("source_fingerprint"),
        "training_fingerprint": training.fingerprint,"cutoff_month": cutoff,"target_year": cutoff.year,"requested_method": method,"method": chosen,"window": window,"budget_version": version,"selection_metric":primary_metric,
        "available_sources": training.flags,"budget_sources_available":{name:engine.available[name] for name in ("sales_budget","expense_budget")},"known_dimensions": {field: sorted({key[index] for key in training.keys}) for index,field in enumerate(training.dimensions)},
        **({"dimension_registry":engine.registry,"model_dimensions":list(training.dimensions),"budget_dimensions":list(engine.budget_dimensions(version)),
            "known_dimensions":{field:sorted(set(engine.events.loc[engine.events['month'].le(cutoff),field])) for field in engine.dimension_ids}} if len(engine.dimension_ids)>3 else {}),
        **({'budget_dimensions':list(engine.budget_dimensions(version)),'expense_budget_dimensions':engine.metadata.get('expense_budget_dimensions',{}).get(version,list(FEE_KEYS))} if engine.metadata.get('local_budgets') else {}),
        "quantity_rounding": "ROUND_HALF_UP_nonnegative_integer", "growth_cap": ["0.5","1.8"],"price_precision": "60 significant digits; output only", "event_amount_precision": "0.01",
        "amount_unit": "CNY excluding tax yuan","quantity_unit": "件", "assumptions_scope": "company_all_business"},
        "actual_periods": actual,"forecast_periods": predicted,"backtest": evaluation,"budgets": budgets}
