"""Independent source-control totals, computed before normalization and dimension joins."""
from datetime import date, datetime
from decimal import Decimal


def source_controls(records,adapter):
    months={}
    def add(day,field,value,count):
        if not day:
            return
        period=str(day)[:7]
        row=months.setdefault(period,{'sales_revenue':Decimal(0),'sales_cost':Decimal(0),'refund_amount':Decimal(0),'cogs_reversal_amount':Decimal(0),'expenses':Decimal(0),'sales_rows':0,'refund_rows':0,'expense_rows':0})
        row[count]=row.get(count,0)+1
        if value in (None,'') or row[field] is None:
            row[field]=None
        else:
            row[field]+=Decimal(str(value))
    if adapter=='mapped_facts_v1':
        for row in records.get('sales',[]):
            add(row.get('revenue_date'),'sales_revenue',row.get('sales_amount_before_refund'),'sales_rows')
            add(row.get('revenue_date'),'sales_cost',row.get('cogs_amount'),'_cost_rows')
        for row in records.get('refunds',[]):
            add(row.get('refund_date'),'refund_amount',row.get('refund_amount'),'refund_rows')
            add(row.get('refund_date'),'cogs_reversal_amount',row.get('cost_reversal_amount'),'_reversal_rows')
    else:
        orders={str(row['order_id']):row for row in records.get('orders',[])}
        for row in records.get('order_items',[]):
            order=orders.get(str(row['order_id']),{})
            if order.get('order_status')!='completed':
                continue
            quantity=Decimal(str(row['quantity']))
            add(order.get('recognized_date'),'sales_revenue',quantity*Decimal(str(row['unit_list_price']))-Decimal(str(row['discount_amount'])),'sales_rows')
            add(order.get('recognized_date'),'sales_cost',quantity*Decimal(str(row['unit_cost_snapshot'])),'_cost_rows')
        for row in records.get('returns',[]):
            add(row.get('refund_date'),'refund_amount',row.get('refund_amount'),'refund_rows')
            add(row.get('refund_date'),'cogs_reversal_amount',row.get('cogs_reversal_amount'),'_reversal_rows')
    for row in records.get('expenses',[]):
        add(row.get('expense_date'),'expenses',row.get('amount'),'expense_rows')
    return {'basis':'读取字段在标准化及分类关联前独立汇总；不是总账审计','months':months}
