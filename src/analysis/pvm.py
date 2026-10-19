"""金额贡献的数学分解；内部用有理数保持恒等式，输出高精度Decimal。"""
from decimal import Decimal, localcontext
from fractions import Fraction

from etl.common import ZERO

FACTOR_LABELS = {
    "volume": "共同商品总销量", "mix": "共同商品结构", "price": "共同商品均价",
    "new_product": "预算无销量商品的本期成交", "no_sales_product": "预算有销量商品的本期未成交",
    "product_volume": "共同商品销量（含结构）", "unit_cost": "共同商品单位成本",
    "refund": "退款差异", "cost_reversal": "成本转回差异", "expense": "公司费用差异",
}


def decimal_value(value):
    if value is None:
        return None
    value = Fraction(value)
    with localcontext() as context:
        context.prec = 60
        return Decimal(value.numerator) / Decimal(value.denominator)


def bridge(base, actual, effects, reason=None):
    """effects的有理数金额必须精确勾稽；尾差仅来自Decimal表示。"""
    difference = None if base is None or actual is None else actual-base
    if reason:
        return {"status": "unavailable", "reason": reason, "budget": base, "actual": actual,
                "variance": difference, "components": [], "details": [], "reconciled": False,
                "representation_residual": None}
    total = sum((Fraction(row["amount"]) for row in effects), Fraction(0))
    if total != Fraction(actual)-Fraction(base):
        raise ValueError("差异桥无法勾稽，请检查输入与分解范围")
    keys = list(dict.fromkeys(row["factor"] for row in effects))
    components = [{"factor": key, "factor_label": FACTOR_LABELS[key],
                   "amount": decimal_value(sum((Fraction(row["amount"]) for row in effects if row["factor"] == key), Fraction(0)))} for key in keys]
    with localcontext() as context:
        context.prec = 60
        residual = difference-sum((row["amount"] for row in components), ZERO)
    return {"status": "complete", "reason": None, "budget": base, "actual": actual,
            "variance": difference, "components": components,
            "details": [{**row, "factor_label": FACTOR_LABELS[row["factor"]], "amount": decimal_value(row["amount"])} for row in effects],
            "reconciled": True, "representation_residual": residual}


def product_effects(products, gross_margin=False):
    """新增/本期未成交单列；PVM仅对双方q>0的共同商品集合。"""
    common = [row for row in products if row["q_budget"] > 0 and row["q_actual"] > 0]
    q0 = sum(row["q_budget"] for row in common)
    q1 = sum(row["q_actual"] for row in common)
    keys = ("product_volume", "price", "unit_cost", "new_product", "no_sales_product") if gross_margin else ("volume", "mix", "price", "new_product", "no_sales_product")
    effects = []
    for row in products:
        amounts = {key: Fraction(0) for key in keys}
        r0, r1 = Fraction(row["revenue_budget"]), Fraction(row["revenue_actual"])
        if row["q_budget"] > 0 and row["q_actual"] > 0:
            quantity0, quantity1 = row["q_budget"], row["q_actual"]
            if gross_margin:
                c0, c1 = Fraction(row["cost_budget"]), Fraction(row["cost_actual"])
                amounts["product_volume"] = (quantity1-quantity0)*(r0-c0)/quantity0
                amounts["price"] = r1-quantity1*r0/quantity0
                amounts["unit_cost"] = quantity1*c0/quantity0-c1
            else:
                amounts["volume"] = (q1-q0)*r0/q0
                amounts["mix"] = quantity1*r0/quantity0-q1*r0/q0
                amounts["price"] = r1-quantity1*r0/quantity0
        elif row["q_actual"] > 0:
            amounts["new_product"] = r1-Fraction(row["cost_actual"]) if gross_margin else r1
        elif row["q_budget"] > 0:
            amounts["no_sales_product"] = -(r0-Fraction(row["cost_budget"])) if gross_margin else -r0
        # 预算q=0并不等于缺预算；无成交商品的均价保持None。
        for key in keys:
            effects.append({"product_id": row["product_id"], "factor": key, "amount": amounts[key]})
    if not effects:
        effects = [{"product_id": None, "factor": key, "amount": Fraction(0)} for key in keys]
    return effects


def enrich_products(products):
    result = []
    for row in products:
        result.append({**row,
            "product_state": "common" if row["q_budget"] > 0 and row["q_actual"] > 0 else "actual_only" if row["q_actual"] > 0 else "budget_only" if row["q_budget"] > 0 else "no_sales",
            "price_budget": decimal_value(Fraction(row["revenue_budget"])/row["q_budget"]) if row["q_budget"] else None,
            "price_actual": decimal_value(Fraction(row["revenue_actual"])/row["q_actual"]) if row["q_actual"] else None,
            "unit_cost_budget": decimal_value(Fraction(row["cost_budget"])/row["q_budget"]) if row["q_budget"] and row["cost_budget"] is not None else None,
            "unit_cost_actual": decimal_value(Fraction(row["cost_actual"])/row["q_actual"]) if row["q_actual"] and row["cost_actual"] is not None else None})
    return result
