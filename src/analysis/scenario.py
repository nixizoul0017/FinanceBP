"""情景仅调整未来预测，不改实际与原预算；参数适用于公司全部业务。"""
from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import pandas as pd

from etl.common import ZERO
from .comparison import budget_variance, _sales_budget_values
from .forecast import DIMENSIONS, FEE_KEYS, FINANCIALS, DRIVERS, cents, difference, divide, known_sum, period_summary, quantity, scaled
from .metrics import Filters, month_range, subtract
from .pvm import decimal_value


@dataclass(frozen=True)
class Assumptions:
    quantity_change: Decimal = ZERO
    price_change: Decimal = ZERO
    unit_cost_change: Decimal = ZERO
    refund_rate_change: Decimal = ZERO
    cost_reversal_change: Decimal = ZERO
    marketing_change: Decimal = ZERO
    expense_change: Decimal = ZERO

    def __post_init__(self):
        for name,value in asdict(self).items():
            try:
                number = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError("情景调整需为有效数字") from error
            if not number.is_finite() or not Decimal(-1) <= number <= Decimal(10):
                raise ValueError("情景调整需为−100%至1000%的有限比例")
            # 页面0.00与脚本0保存同一零假设，避免文本小数位生成不同版本。
            object.__setattr__(self,name,ZERO if number == 0 else number)


PRESETS = {"base": Assumptions(),
    "optimistic": Assumptions(quantity_change=Decimal("0.05"),price_change=Decimal("0.02"),unit_cost_change=Decimal("-0.01"),refund_rate_change=Decimal("-0.05")),
    "cautious": Assumptions(quantity_change=Decimal("-0.08"),price_change=Decimal("-0.02"),unit_cost_change=Decimal("0.02"),refund_rate_change=Decimal("0.10"),marketing_change=Decimal("0.05"),expense_change=Decimal("0.01"))}


def apply_scenario(periods, flags, assumptions=Assumptions()):
    if not isinstance(assumptions,Assumptions):
        raise ValueError("情景参数需使用Assumptions")
    if all(value == 0 for value in asdict(assumptions).values()):
        return deepcopy(periods)
    result = []
    for base in periods:
        period = deepcopy(base)
        if not period["available"]:
            result.append(period)
            continue
        for before,row in zip(base["sales"],period["sales"]):
            q = quantity(Fraction(before["sales_quantity"])*(1+Fraction(assumptions.quantity_change)))
            q_scale = Fraction(q,before["sales_quantity"]) if before["sales_quantity"] else Fraction(1)
            row["sales_quantity"] = q
            row["net_unit_price"] = scaled(before["net_unit_price"],1+assumptions.price_change)
            row["unit_cost"] = scaled(before["unit_cost"],1+assumptions.unit_cost_change)
            row["sales_revenue"] = ZERO if q == 0 else scaled(before["sales_revenue"],q_scale*(1+Fraction(assumptions.price_change)))
            row["sales_cost"] = ZERO if q == 0 else scaled(before["sales_cost"],q_scale*(1+Fraction(assumptions.unit_cost_change)))
            exposure = divide(row["sales_revenue"],before["sales_revenue"]) if before["sales_revenue"] is not None and before["sales_revenue"] > 0 else Fraction(1)
            refund_scale = exposure*(1+Fraction(assumptions.refund_rate_change)) if exposure is not None else None
            row["refund_amount"] = cents(scaled(before["refund_amount"],refund_scale))
            row["cogs_reversal_amount"] = cents(scaled(before["cogs_reversal_amount"],refund_scale*(1+Fraction(assumptions.cost_reversal_change)) if refund_scale is not None else None))
        old, new = period_summary(base,flags),period_summary(period,flags)
        revenue_scale = divide(new["sales_revenue"],old["sales_revenue"]) if old["sales_revenue"] is not None and old["sales_revenue"] > 0 else Fraction(1)
        quantity_scale = divide(new["sales_quantity"],old["sales_quantity"]) if old["sales_quantity"] is not None and old["sales_quantity"] > 0 else Fraction(1)
        for before,row in zip(base["expense_rows"],period["expense_rows"]):
            scale = revenue_scale if row["expense_category"]=="platform_commission" else quantity_scale if row["expense_category"]=="logistics" else Fraction(1)
            if row["expense_category"]=="marketing":
                scale *= 1+Fraction(assumptions.marketing_change)
            scale = None if scale is None else scale*(1+Fraction(assumptions.expense_change))
            row["amount"] = cents(scaled(before["amount"],scale))
        result.append(period)
    return result


def _selected(row,filters):
    return all(values is None or row.get(field) in values for field,values in filters.items)


def annual_budget(base,filters=Filters()):
    from datetime import date
    year=base["metadata"]["target_year"]
    months=month_range(date(year,1,1),date(year,12,1))
    sales=[row for row in base["budgets"]["sales_budget"] if _selected(row,filters)]
    fees=base["budgets"]["expense_budget"]
    grain=base["metadata"].get("budget_dimensions", DIMENSIONS)
    unsupported=any(values is not None and field not in grain for field,values in filters.items)
    budget_keys={(row["month"],*(row[field] for field in grain)) for row in sales}
    required_keys={(row["month"],*(row.get(field) for field in grain)) for period in base["actual_periods"]+base["forecast_periods"] for row in period["sales"] if all(field in row for field in grain) and _selected(row,filters) and (row["sales_quantity"]>0 or row["refund_amount"] not in (None,ZERO) or row["cogs_reversal_amount"] not in (None,ZERO))}
    missing_keys=sorted(required_keys-budget_keys)
    # Coarser models may omit a finer budget axis. Check future coverage on the
    # shared grain instead of inventing that classification or discarding totals.
    for period in base['forecast_periods']:
        future=[row for row in period['sales'] if _selected(row,filters)]
        shared=[field for field in grain if all(field in row for row in future)]
        required={(row['month'],*(row[field] for field in shared)) for row in future if row['sales_quantity']>0 or row['refund_amount'] not in (None,ZERO)}
        covered={(row['month'],*(row[field] for field in shared)) for row in sales}
        missing_keys.extend(sorted(required-covered))
    missing_months=sorted(set(months)-{row["month"] for row in sales})
    valid=not unsupported and base["metadata"]["budget_sources_available"]["sales_budget"] and bool(sales) and not missing_keys and not missing_months
    revenue=known_sum(_sales_budget_values(row)['net_revenue'] for row in sales) if valid else None
    cost=known_sum(_sales_budget_values(row)['net_cost'] for row in sales) if valid else None
    # NULL费用预算键或缺月保持未知；不把部分费用预算当全年。
    fee_grain=base['metadata'].get('expense_budget_dimensions',FEE_KEYS)
    fee_keys={(row["month"],*(row[field] for field in fee_grain)) for row in fees}
    required_fees={(row["month"],*(row[field] for field in fee_grain)) for period in base["actual_periods"]+base["forecast_periods"] for row in period["expense_rows"] if row["amount"] not in (None,ZERO)}
    fee_missing=sorted(required_fees-fee_keys)
    fee_missing_months=sorted(set(months)-{row["month"] for row in fees})
    fee=known_sum(row["amount"] for row in fees) if base["metadata"]["budget_sources_available"]["expense_budget"] and fees and not fee_missing and not fee_missing_months and filters.is_company else None
    margin=difference(revenue,cost)
    return {"net_revenue":revenue,"net_cost":cost,"gross_margin":margin,"expenses":fee,"operating_profit":difference(margin,fee) if filters.is_company else None,
        "missing_sales_months":missing_months,"missing_sales_keys":missing_keys,"missing_expense_months":fee_missing_months,"missing_expense_keys":fee_missing}


def totals(rows,fields):
    return {field:known_sum(row[field] for row in rows) for field in fields}


def comparison(actual,budget,field):
    with localcontext() as context:
        context.prec=60
        return budget_variance(actual,budget,higher_is_better=field not in ("net_cost","expenses"))


def forecast_pack(base,filters=Filters(),custom=Assumptions()):
    if not isinstance(filters,Filters):
        raise ValueError("筛选需使用Filters")
    flags=base["metadata"]["available_sources"]
    scope_known=all(values is None or set(values).issubset(base["metadata"]["known_dimensions"].get(field, [])) for field,values in filters.items)
    scenarios={}
    budgets={"selected":annual_budget(base,filters),"company":annual_budget(base)}
    actual_selected=[period_summary(period,flags,filters,scope_known) for period in base["actual_periods"]]
    actual_company=[period_summary(period,flags) for period in base["actual_periods"]]
    for name,assumptions in {**PRESETS,"custom":custom}.items():
        future=apply_scenario(base["forecast_periods"],flags,assumptions)
        selected=[period_summary(period,flags,filters,scope_known) for period in future]
        company=[period_summary(period,flags) for period in future]
        selected_annual=totals(actual_selected+selected,FINANCIALS)
        company_annual=totals(actual_company+company,FINANCIALS)
        selected_remaining=totals(selected,FINANCIALS)
        if not filters.is_company:
            selected_remaining["expenses"]=selected_remaining["operating_profit"]=None
        scenarios[name]={"assumptions":asdict(assumptions),"future_periods":future,"selected_monthly":selected,"company_monthly":company,
            "selected_ytd":totals(actual_selected,FINANCIALS),"selected_remaining":selected_remaining,"selected_annual":selected_annual,
            "company_ytd":totals(actual_company,FINANCIALS),"company_remaining":totals(company,FINANCIALS),"company_annual":company_annual,
            "selected_budget_comparison":{field:comparison(selected_annual[field],budgets["selected"][field],field) for field in FINANCIALS},
            "company_budget_comparison":{field:comparison(company_annual[field],budgets["company"][field],field) for field in FINANCIALS}}
    return {"metadata":{**deepcopy(base["metadata"]),"sales_filters":filters.as_dict(),"selected_scope_known":scope_known},
        "actual_selected_monthly":actual_selected,"actual_company_monthly":actual_company,"backtest":deepcopy(base["backtest"]),"budget_reference":budgets,"scenarios":scenarios}
