"""Actual-vs-actual PVM. Base periods are actuals and are never budgets."""
from fractions import Fraction
from .metrics import Filters, month_date, shift_month, subtract, ratio, sum_decimal
from .comparison import change
from .pvm import bridge, product_effects, enrich_products

LABELS={'new_product':'基期未成交商品的本期成交','no_sales_product':'基期成交商品的本期未成交',
        'volume':'共同商品总销量','mix':'共同商品结构','price':'共同商品均价','product_volume':'共同商品销量（含结构）',
        'unit_cost':'共同商品单位成本','refund':'退款变化','cost_reversal':'成本转回变化','expense':'公司费用变化'}
REASONS={'actual_incomplete':'本期实际未完整载入','base_incomplete':'基期实际未完整载入','quantity_unit_unconfirmed':'未确认统一件数口径',
         'refund_source_missing':'退款来源未提供','historic_cost_missing':'本期或基期缺历史成本','expense_source_missing':'公司费用来源未提供'}


def public_bridge(base,actual,effects,reason=None):
    value=bridge(base,actual,effects,reason)
    value['base']=value.pop('budget')
    for row in value['components']+value['details']:
        row['factor_label']=LABELS[row['factor']]
    return value


def historical_variance(engine,month,filters=Filters(),mode='mom',group_by=()):
    if mode not in ('mom','yoy'):
        raise ValueError('比较方式需为mom或yoy')
    month=month_date(month)
    base_month=shift_month(month,-1 if mode=='mom' else -12)
    current=engine.summary(month,filters=filters)
    previous=engine.summary(base_month,filters=filters)
    reason='actual_incomplete' if not current['is_complete'] else 'base_incomplete' if not previous['is_complete'] else 'quantity_unit_unconfirmed' if engine.metadata.get('semantics',{}).get('quantity_unit')!='件' else None
    products=[]
    if reason is None:
        now=engine.period_events(month,month,filters)
        before=engine.period_events(base_month,base_month,filters)
        keys=sorted(set(now.product_id)|set(before.product_id))
        for key in keys:
            row={'product_id':key}
            for suffix,frame in [('actual',now),('budget',before)]:
                group=frame[frame.product_id.eq(key)]
                values,_=engine._aggregate(group)
                row.update({f'q_{suffix}':values['sales_quantity'],f'revenue_{suffix}':values['sales_revenue'],f'cost_{suffix}':values['sales_cost'] if group.cost_complete.all() else None,
                            f'refund_{suffix}':values['refund_amount'],f'reversal_{suffix}':values['cogs_reversal_amount']})
            products.append(row)
    sales_effects=product_effects(products) if reason is None else []
    sales=public_bridge(previous['sales_revenue'],current['sales_revenue'],sales_effects,reason)
    revenue_reason=reason or ('refund_source_missing' if not engine.available['refunds'] else None)
    refunds=[{'product_id':r['product_id'],'factor':'refund','amount':Fraction(r['refund_budget'])-Fraction(r['refund_actual'])} for r in products] if revenue_reason is None else []
    revenue=public_bridge(previous['net_revenue'],current['net_revenue'],sales_effects+refunds,revenue_reason)
    margin_reason=revenue_reason or ('historic_cost_missing' if previous['gross_margin'] is None or current['gross_margin'] is None else None)
    margin_effects=product_effects(products,True)+refunds+[{'product_id':r['product_id'],'factor':'cost_reversal','amount':Fraction(r['reversal_actual'])-Fraction(r['reversal_budget'])} for r in products] if margin_reason is None else []
    margin=public_bridge(previous['gross_margin'],current['gross_margin'],margin_effects,margin_reason)
    profit_reason=margin_reason or ('expense_source_missing' if not engine.available['expenses'] else None) or ('sales_scope_unallocated' if not filters.is_company else None)
    profit_effects=margin_effects+[{'factor':'expense','amount':Fraction(previous['expenses'])-Fraction(current['expenses'])}] if profit_reason is None else []
    profit=public_bridge(previous['operating_profit'],current['operating_profit'],profit_effects,profit_reason)
    ranking=[]
    groups=tuple(group_by)
    if groups:
        now=engine.dimensions(month,by=groups,filters=filters).to_dict('records')
        before=engine.dimensions(base_month,by=groups,filters=filters).to_dict('records')
        a={tuple(row[field] for field in groups):row for row in now}
        b={tuple(row[field] for field in groups):row for row in before}
        for key in sorted(set(a)|set(b)):
            row=dict(zip(groups,key))
            for field in ('net_revenue','net_cost','gross_margin'):
                actual=a[key][field] if key in a else 0 if current['is_complete'] and not current['data_issues'] else None
                base=b[key][field] if key in b else 0 if previous['is_complete'] and not previous['data_issues'] else None
                row[field]=change(actual,base)
            ranking.append(row)
        ranking.sort(key=lambda row:(row['net_revenue']['change_amount'] is None,row['net_revenue']['change_amount'] or 0))
    public_products=[{key.replace('_budget','_base'):value for key,value in row.items()} for row in enrich_products(products)]
    return {'metadata':{'entity_id':engine.entity_id,'rule_version':engine.metadata['rule_version'],'source_fingerprint':engine.metadata.get('source_fingerprint'),
                        'month':month,'base_month':base_month,'mode':mode,'sales_filters':filters.as_dict(),'group_by':list(groups),'base_kind':'historical_actual','decomposition_order':'volume_then_mix_then_price;entry_exit_separate'},
            'current':current,'base':previous,'comparisons':{field:change(current[field],previous[field]) for field in ('net_revenue','net_cost','gross_margin','expenses','operating_profit')},
            'sales_bridge':sales,'revenue_bridge':revenue,'gross_margin_bridge':margin,'operating_bridge':profit,'products':public_products,'rankings':ranking}
