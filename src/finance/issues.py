"""Evidence-first exception detection; manual causes and actions remain human records."""
from datetime import date
from decimal import Decimal
from analysis.historical import historical_variance
from analysis.metrics import Filters, ratio
from analysis.comparison import company_budget_comparison, sales_budget_comparison
from analysis.forecast_store import content_digest
from .budgets import number
from .store import WorkspaceError

DEFAULTS={'amount':Decimal('1000'),'rate':Decimal('0.1'),'margin_points':Decimal('0.02')}
STATUSES={'open':'待调查','in_progress':'处理中','monitoring':'观察中','resolved':'已解决','ignored':'已说明忽略'}


def validate_thresholds(payload):
    result={field:number(payload.get(field,value),'amount' if field=='amount' else 'unit_cost') for field,value in DEFAULTS.items()}
    if result['rate']>10 or result['margin_points']>1:
        raise WorkspaceError('变化率需在0—1000%，毛利率百分点需在0—100之间')
    return result


def validate_notes(notes,status):
    if status not in STATUSES or not isinstance(notes,dict):
        raise WorkspaceError('跟进状态无效')
    fields=('owner','cause','evidence','action','due_date','resolution','review_month','review_result','cause_status')
    result={field:str(notes.get(field,'')).strip() for field in fields}
    if any(len(value)>4000 for value in result.values()):
        raise WorkspaceError('单项跟进说明不能超过4000字')
    for field in ('due_date','review_month'):
        if result[field]:
            try:
                date.fromisoformat(result[field]+'-01' if field=='review_month' else result[field])
            except ValueError as error:
                raise WorkspaceError('日期格式应为YYYY-MM-DD，复盘月份为YYYY-MM') from error
    if result['cause_status'] not in ('','pending','confirmed'):
        raise WorkspaceError('原因状态无效')
    if result['cause_status']=='confirmed' and (not result['cause'] or not result['evidence']):
        raise WorkspaceError('确认原因时请同时填写原因和核实依据')
    if status=='in_progress' and any(not result[field] for field in ('owner','action','due_date')):
        raise WorkspaceError('处理中需填写负责人、行动和截止日')
    if status in ('resolved','ignored') and not result['resolution']:
        raise WorkspaceError('解决或忽略异常时必须填写结果或理由')
    if bool(result['review_month'])!=bool(result['review_result']):
        raise WorkspaceError('复盘月份与复盘结论需同时填写')
    return result


def scan_key(filters,group_by,mode):
    return content_digest({'filters':filters.as_dict(),'groups':list(group_by),'mode':mode})[:24]


def detect_issues(engine,month,filters=Filters(),version='B2026_V1',group_by=(),mode='mom',thresholds=None):
    t=validate_thresholds(thresholds or {})
    history=historical_variance(engine,month,filters,mode,group_by)
    current,base=history['current'],history['base']
    scope={'filters':filters.as_dict(),'group_by':list(group_by),'mode':mode}
    identity=scan_key(filters,group_by,mode)
    candidates=[]
    gaps=[]
    def add(rule,title,actual,reference,amount,rate,groups=None,company=False):
        candidates.append({'key':content_digest({'scan':identity,'rule':rule,'groups':groups}),'month':str(month)[:7],
                           'rule':rule,'title':title,'actual':actual,'reference':reference,'impact_amount':amount,'change_rate':rate,
                           'scope':scope,'group_values':groups,'company_scope':company,'base_month':history['metadata']['base_month'],
                           'budget_version':version,
                           'source_fingerprint':engine.metadata.get('source_fingerprint'),'thresholds':t,'classification':'系统事实，原因待核实'})
    revenue=history['comparisons']['net_revenue']
    if revenue['change_amount'] is not None and revenue['change_rate'] is not None:
        if revenue['change_amount']<0 and -revenue['change_amount']>=t['amount'] and -revenue['change_rate']>=t['rate']:
            add('revenue_decline','净收入较历史基期下降',revenue['current'],revenue['base'],-revenue['change_amount'],-revenue['change_rate'])
    else:
        gaps.append('历史收入变化：基期缺失或非正，未生成比例异常')
    if current['gross_margin_rate'] is not None and base['gross_margin_rate'] is not None:
        drop=base['gross_margin_rate']-current['gross_margin_rate']
        impact=base['gross_margin_rate']*current['net_revenue']-current['gross_margin']
        if drop>0 and impact>0 and drop>=t['margin_points'] and impact>=t['amount']:
            add('margin_decline','毛利率低于历史基期',current['gross_margin_rate'],base['gross_margin_rate'],impact,drop)
    else:
        gaps.append('毛利率变化：必要收入或成本不足')
    r1,r0=ratio(current['refund_amount'],current['sales_revenue']),ratio(base['refund_amount'],base['sales_revenue'])
    if r1 is not None and r0 is not None:
        amount=current['refund_amount']-base['refund_amount']
        rate=ratio(amount,base['refund_amount'])
        if amount>0 and amount>=t['amount'] and (rate is not None and rate>=t['rate']):
            add('refund_increase','当月退款额上升（含跨月退款，非退货批次率）',current['refund_amount'],base['refund_amount'],amount,rate)
    else:
        gaps.append('退款变化：历史或来源不足')
    budget=sales_budget_comparison(engine,month,version=version,filters=filters)['totals']['net_revenue']
    if budget['variance'] is not None and budget['variance_rate'] is not None:
        if budget['variance']<0 and -budget['variance']>=t['amount'] and -budget['variance_rate']>=t['rate']:
            add('revenue_budget_shortfall','净收入低于所选预算',budget['actual'],budget['budget'],-budget['variance'],-budget['variance_rate'])
    else:
        gaps.append('收入预算比较：当前范围没有完整可比预算')
    if filters.is_company:
        fee=company_budget_comparison(engine,month,version=version)['expenses']['total']
        if fee['variance'] is not None and fee['variance_rate'] is not None:
            if fee['variance']>0 and fee['variance']>=t['amount'] and fee['variance_rate']>=t['rate']:
                add('expense_over_budget','公司费用超预算',fee['actual'],fee['budget'],fee['variance'],fee['variance_rate'],company=True)
        else:
            gaps.append('公司费用预算比较：缺少完整可比费用预算')
    for row in history['rankings']:
        change=row['net_revenue']
        if change['change_amount'] is not None and change['change_rate'] is not None and change['change_amount']<0 and -change['change_amount']>=t['amount'] and -change['change_rate']>=t['rate']:
            values={field:row[field] for field in group_by}
            add('group_revenue_decline','分类净收入较历史基期下降',change['current'],change['base'],-change['change_amount'],-change['change_rate'],values)
    return {'scan_key':identity,'candidates':candidates,'coverage_gaps':gaps,'history':history}


def workflow_snapshot(store,context,engine,month):
    from .reconciliation import reconciliation, compare_snapshot
    closes=store.closes(context,month)
    active=next((r for r in reversed(closes) if not r['released_at']),None)
    confirmed=None
    if active:
        checked=compare_snapshot(active['snapshot'],engine,month)
        confirmed={key:active[key] for key in ('id','revision','actor','note','created_at','digest')}
        confirmed['actual_changed']=checked['changed']
    issues=store.issues(context,month)
    from reporting.service import scope_label
    for issue in issues:
        selected=Filters.from_dict(issue['facts']['scope']['filters'])
        label=scope_label(selected,engine.registry)
        groups=issue['facts'].get('group_values') or {}
        if groups:
            label+='；分组：'+' / '.join(engine.dimension_labels.get(field,field)+':'+engine.dimension_text(field,value) for field,value in groups.items())
        issue['scope_label']='公司费用全口径' if issue['facts'].get('company_scope') else label
    return {'entity_id':engine.entity_id,'month':str(month)[:7],'context':context,'reconciliation':reconciliation(engine,month,store.controls(context,month)),
            'month_confirmation':confirmed,'issues':issues,'local_budgets':engine.metadata.get('local_budgets',[])}
