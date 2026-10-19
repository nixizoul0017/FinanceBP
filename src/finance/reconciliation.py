"""Source → canonical → analysis tie-out, independent references and durable month snapshots."""
from datetime import date
from decimal import Decimal
from copy import deepcopy
import pandas as pd

from analysis.metrics import month_date, sum_decimal
from analysis.forecast_store import content_digest
from etl.common import ZERO, encode
from etl.dimensions import MISSING
from .budgets import number
from .store import WorkspaceError, dumps
import json

CONTROL_FIELDS={'sales_revenue':'退款前销售收入','refund_amount':'退款额','sales_cost':'成交成本','cogs_reversal_amount':'成本转回','expenses':'公司费用'}
TOLERANCE=Decimal('0.01')


def control_amount(value):
    return number(value,'amount',optional=True)


def month_rows(engine,month):
    month=month_date(month)
    result={}
    lookup={row['sale_line_id']:row for row in engine.tables['sales'].to_dict('records')}
    for name,day,key in [('sales','revenue_date','sale_line_id'),('refunds','refund_date','refund_id'),('expenses','expense_date','expense_id')]:
        rows=[]
        for row in engine.tables[name].to_dict('records'):
            if row[day].replace(day=1)!=month:
                continue
            value=deepcopy(row)
            if name=='refunds':
                value.update({field:lookup[row['sale_line_id']][field] for field in engine.dimension_ids})
                value['original_cost_known']=not pd.isna(lookup[row['sale_line_id']]['cogs_amount'])
            # Pandas optional values may be NaN; normalize before versioning JSON.
            value={field:None if isinstance(item,float) and pd.isna(item) else item for field,item in value.items()}
            rows.append(value)
        result[name]=sorted(rows,key=lambda row:str(row[key]))
    return result


def month_snapshot(engine,month):
    month=month_date(month)
    payload={'entity_id':engine.entity_id,'rule_version':engine.metadata['rule_version'],'month':str(month)[:7],
             'is_complete':engine.is_complete(month),'availability':{k:engine.available[k] for k in ('sales','refunds','expenses')},
             'rows':month_rows(engine,month),'summary':engine.summary(month)}
    payload=json.loads(dumps(payload))
    payload['actual_hash']=content_digest(payload)
    return payload


def compare_snapshot(snapshot,engine,month):
    current=month_snapshot(engine,month)
    changes=[]
    for name,key in [('sales','sale_line_id'),('refunds','refund_id'),('expenses','expense_id')]:
        before={row[key]:row for row in snapshot['rows'][name]}
        after={row[key]:row for row in current['rows'][name]}
        for identity in sorted(set(before)|set(after)):
            old,new=before.get(identity),after.get(identity)
            if old!=new:
                fields=[field for field in sorted(set(old or {})|set(new or {})) if (old or {}).get(field)!=(new or {}).get(field)]
                changes.append({'object':name,'id':identity,'kind':'新增' if old is None else '删除' if new is None else '修改','fields':fields,'before':old,'after':new})
    return {'changed':snapshot['actual_hash']!=current['actual_hash'],'rows':changes,'confirmed_hash':snapshot['actual_hash'],'current_hash':current['actual_hash'],
            'summary_before':snapshot['summary'],'summary_now':current['summary']}


def reconciliation(engine,month,controls=None):
    month=month_date(month)
    summary=engine.summary(month)
    rows=month_rows(engine,month)
    canonical={'sales_revenue':sum_decimal(r['sales_amount_before_refund'] for r in rows['sales']),
               'sales_cost':sum_decimal(r['cogs_amount'] for r in rows['sales']),
               'refund_amount':sum_decimal(r['refund_amount'] for r in rows['refunds']),
               'cogs_reversal_amount':sum_decimal(r['cost_reversal_amount'] for r in rows['refunds']),
               'expenses':sum_decimal(r['amount'] for r in rows['expenses'])}
    raw_meta=engine.metadata.get('source_controls')
    source=(raw_meta or {}).get('months',{}).get(str(month)[:7],{})
    detail=[]
    blockers=[]
    if not summary['is_complete']:
        blockers.append('实际月份未完整载入')
    for key in ('sales','refunds','expenses'):
        if not engine.available[key]:
            blockers.append(key+'来源尚未提供')
    if summary['gross_margin'] is None:
        blockers.append('历史成本或退款数据不足，毛利无法确认')
    for field,label in CONTROL_FIELDS.items():
        raw=source.get(field,ZERO) if raw_meta else None
        raw=Decimal(str(raw)) if raw is not None else None
        standard=canonical[field]
        value=summary[field]
        internal='一致' if raw is not None and standard is not None and value is not None and raw==standard==value else '不可核对' if raw is None or standard is None or value is None else '不一致'
        reference=control_amount((controls or {}).get('amounts',{}).get(field))
        difference=value-reference if value is not None and reference is not None else None
        status='已核对' if difference is not None and abs(difference)<=TOLERANCE else '未填写' if reference is None else '存在差异' if difference is not None else '实际不可用'
        detail.append({'field':field,'指标':label,'来源读取合计（元）':raw,'标准明细合计（元）':standard,'分析结果（元）':value,'内部勾稽':internal,'独立参考（元）':reference,'实际减参考（元）':difference,'外部核对':status})
        if internal!='一致':
            blockers.append(label+'内部勾稽'+internal)
        if status!='已核对':
            blockers.append(label+status)
    for name,count_field in [('sales','sales_rows'),('refunds','refund_rows'),('expenses','expense_rows')]:
        if raw_meta and source.get(count_field,0)!=len(rows[name]):
            blockers.append(name+'来源与标准明细行数不一致')
    missing=[]
    for entry in engine.registry:
        selected=[r for r in rows['sales'] if r.get(entry['id'])==MISSING]
        missing.append({'维度':entry['label'],'缺失销售行':len(selected),'涉及退款前收入（元）':sum_decimal(r['sales_amount_before_refund'] for r in selected)})
    return {'entity_id':engine.entity_id,'month':str(month)[:7],'scope':'company','tolerance':TOLERANCE,'rows':detail,'missing_dimensions':missing,
            'source_basis':(raw_meta or {}).get('basis','未保存独立来源控制数，内部勾稽不可确认'),
            'reference_source':(controls or {}).get('source'),'reference_actor':(controls or {}).get('actor'),
            'can_confirm':not blockers,'blockers':list(dict.fromkeys(blockers))}
