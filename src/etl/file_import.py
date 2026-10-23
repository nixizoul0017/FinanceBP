"""User-confirmed business file imports produce the existing v2 source contract."""
from copy import deepcopy
from datetime import date
import calendar
import hashlib
import json
from pathlib import Path
import re

from desktop.paths import AppPaths
from desktop.events import atomic_json
from .file_tables import FILE_TYPES, MAX_FILE_BYTES, list_sheets, read_table
from .sources import CONTRACT, SEMANTICS, validate_profile
from .dimensions import BUILTINS, recommend
from .dates import parse_business_date

ROLE_LABELS={'sales':'销售明细','refunds':'退款明细','expenses':'公司费用','sales_budget':'销售预算','expense_budget':'费用预算'}
FIELDS={
 'sale_line_id':('销售明细唯一编号',('销售明细ID','明细ID','明细编号','订单明细号','order_item_id','line_id')),
 'order_id':('订单编号（唯一明细编号）',('订单编号','订单ID','订单号','销售订单号','订单编码','order_no')),
 'revenue_date':('销售确认日期',('确认日期','确认日','销售日期','交易日期','销售确认日','支付时间','支付日期','付款时间','付款日期','交易时间','成交时间','recognized_date','sale_date','payment_time','payment_date','paid_at','pay_time')),
 'product_id':('商品分类/编码',('商品','商品编码','商品编号','商品名称','产品','产品编码','product_code')),
 'channel_id':('渠道分类/编码',('渠道','销售渠道','渠道编码','channel_code')),
 'region_id':('地区分类/编码',('地区','区域','地区编码','区域编码','region_code')),
 'quantity':('成交数量（件）',('数量','销量','销售数量','成交数量','销售件数','qty','预算数量','budget_quantity')),
 'sales_amount_before_refund':('折后、退款前销售金额（元）',('退款前销售','退款前收入','退款前销售额','退款前销售金额','销售金额','销售收入','成交金额','订单金额','sales_amount','sales_revenue')),
 'cogs_amount':('历史成交成本（元，可缺失）',('成交成本','销售成本','历史成本','成本金额','成本','sales_cost','cost_amount')),
 'refund_id':('退款唯一编号',('退款ID','退款编号','退款单号','return_id')),
 'refund_date':('退款发生日期',('退款日期','退款确认日','退款日','退货日期')),
 'returned_quantity':('退货数量',('退货数量','退款数量','return_quantity')),
 'recoverable_quantity':('可回库数量',('可回库数量','可冲回数量','可恢复数量')),
 'refund_amount':('退款金额（元）',('退款金额','退货金额','预算退款金额')),
 'cost_reversal_amount':('可冲回成本（元）',('成本转回','成本冲回','可冲回成本','冲回成本','cogs_reversal_amount','预算成本冲回')),
 'expense_id':('费用唯一编号',('费用ID','费用编号','费用单号')),
 'expense_date':('费用发生日期',('费用日期','费用确认日','发生日期')),
 'expense_category':('费用类别',('费用类别','费用类型','费用科目','科目')),
 'department':('费用归属部门',('费用部门','部门','部门编码')),
 'channel_scope':('费用渠道范围',('渠道归属','费用渠道归属','费用渠道')),
 'region_scope':('费用地区范围',('区域归属','费用区域归属','费用地区')),
 'amount':('公司费用金额（元）',('费用金额','费用','预算费用金额','预算金额','budget_amount')),
 'budget_version':('预算版本',('预算版本','预算方案','版本','version')),
 'month':('预算月份',('月份','预算月份','期间','month_start')),
 'net_unit_price':('预算折后、退款前单价（元/件）',('预算均价','预算单价','净单价','budget_net_unit_price')),
 'unit_cost':('预算单位成本（元/件，可缺失）',('单位成本','预算单位成本','budget_unit_cost')),
}
OPTIONAL={
 'sales':{'quantity':1,'product_id':'未归属','channel_id':'未归属','region_id':'未归属','cogs_amount':None},
 'refunds':{},
 'expenses':{'department':'公司','channel_scope':'ALL','region_scope':'ALL'},
 'sales_budget':{'product_id':'未归属','channel_id':'未归属','region_id':'未归属','unit_cost':None},
 'expense_budget':{'department':'公司','channel_scope':'ALL','region_scope':'ALL'},
}


def _key(value):
    return re.sub(r'[\s_\-（）()\[\]·/]+','',str(value)).casefold()


def suggest_mapping(role, columns, comments=None):
    result={}
    comments=comments or {}
    for field in CONTRACT[role][1:]:
        aliases=[field,FIELDS[field][0],*FIELDS[field][1]]
        keys={_key(value) for value in aliases}
        matches=[column for column in columns if _key(column) in keys or _key(comments.get(column,'')) in keys]
        if len(matches)==1:
            result[field]=matches[0]
    return result


def recommended_classifications(columns):
    """Suggest a few business categories, leaving identifiers/private fields opt-in."""
    terms=('点位名称','门店名称','商户类型','销售部门','部门','销售员','渠道','地区','区域','商品名称','产品名称','客户类型','订单类型')
    private=('手机','电话','邮箱','身份证','账户','密码')
    return [column for column in columns if any(term in column for term in terms)
            and not any(term in column for term in private)][:3]


def financial_file_hint(path, *, sheet_name=None, header_row=1):
    """Recommend mappings/range from the whole file, never infer monthly completeness."""
    preview=read_table(path,sheet_name=sheet_name,header_row=header_row,limit=20)
    mapping=suggest_mapping('sales',preview.columns,preview.comments)
    if not mapping.get('order_id') and mapping.get('sale_line_id'):
        mapping['order_id']=mapping['sale_line_id']
    if not {'order_id','revenue_date','sales_amount_before_refund'}<=set(mapping):
        return {'detected':False}
    table=read_table(path,sheet_name=sheet_name,header_row=header_row)
    days=[];invalid_dates=0
    for row in table.rows:
        try:days.append(parse_business_date(row.get(mapping['revenue_date']),field='revenue_date'))
        except ValueError:invalid_dates+=1
    refund_mapping=suggest_mapping('refunds',table.columns,table.comments)
    refund_column=refund_mapping.get('refund_amount')
    refunds_zero=bool(table.rows and refund_column)
    if refunds_zero:
        from decimal import Decimal, InvalidOperation
        for row in table.rows:
            try:
                value=Decimal(str(row.get(refund_column)))
                if not value.is_finite() or value!=0:refunds_zero=False;break
            except (InvalidOperation,TypeError,ValueError):refunds_zero=False;break
    return {'detected':True,'mapping':mapping,'row_count':len(table.rows),
            'start_month':min(days).strftime('%Y-%m') if days else '',
            'end_month':max(days).strftime('%Y-%m') if days else '',
            'first_date':min(days).isoformat() if days else None,
            'last_date':max(days).isoformat() if days else None,
            'invalid_dates':invalid_dates,'refund_column':refund_column,'refunds_zero':refunds_zero}


def stage_uploads(files, *, paths=None):
    paths=paths or AppPaths.current()
    folder=paths.data/'imports'
    folder.mkdir(parents=True,exist_ok=True)
    if len(files)>20:
        raise ValueError('一次最多选择20个业务文件。')
    result=[]
    total=0
    seen=set()
    for uploaded in files:
        name=Path(uploaded.name.replace('\\','/')).name
        suffix=Path(name).suffix.lower()
        if suffix.lstrip('.') not in FILE_TYPES:
            raise ValueError('不支持的业务文件：'+name)
        data=uploaded.getvalue()
        total+=len(data)
        if len(data)>MAX_FILE_BYTES or total>200*1024*1024:
            raise ValueError('单文件最多100MB，一次上传总量最多200MB。')
        fingerprint=hashlib.sha256(data).hexdigest()
        target=folder/(fingerprint+suffix)
        if not target.exists():
            temporary=target.with_suffix(suffix+'.part')
            temporary.write_bytes(data)
            temporary.replace(target)
        if (fingerprint,suffix) not in seen:
            result.append({'path':str(target),'name':name,'sha256':fingerprint,'bytes':len(data)})
            seen.add((fingerprint,suffix))
    return result


def table_references(files):
    refs=[]
    for file in files:
        for sheet in list_sheets(file['path']):
            refs.append({**file,'sheet_name':sheet,'id':file['sha256']+':'+str(sheet),
                         'label':file['name']+(' · '+sheet if sheet is not None else '')})
    return refs


def coverage(start, end, *, partial_period=False):
    if not re.fullmatch(r'\d{4}-\d{2}',start or '') or not re.fullmatch(r'\d{4}-\d{2}',end or ''):
        raise ValueError('完整实际期间请填写YYYY-MM，例如2026-09。')
    first=date.fromisoformat(start+'-01')
    last=date.fromisoformat(end+'-01')
    if first>last:
        raise ValueError('完整实际开始月份不能晚于截止月份。')
    result={'complete_start':first.isoformat(),'complete_end':last.replace(day=calendar.monthrange(last.year,last.month)[1]).isoformat()}
    if partial_period:
        months=[]
        current=first
        while current<=last:
            months.append(current.isoformat())
            current=date(current.year+current.month//12,current.month%12+1,1)
        result['incomplete_months']=months
    return result


def build_profile(entity, name, start, end, selections, *, dimension_fields=(), comments=None,selected_headers=False,partial_period=False):
    entity,name=entity.strip(),name.strip()
    if not entity or not name or len(entity)>80 or len(name)>100:
        raise ValueError('请填写企业/分析主体和接入名称（分别不超过80及100字）。')
    profile={'profile_version':2,'profile_id':'business-'+hashlib.sha256((entity+'\0'+name).encode()).hexdigest()[:24],
             'entity_id':entity,'display_name':name,'rule_version':'sales_v1','coverage':coverage(start,end,partial_period=partial_period),
             'semantics':dict(SEMANTICS),'adapter':'mapped_facts_v1','source':{'kind':'files'},'tables':{},'dimensions':[]}
    used=[]
    for role,selection in selections.items():
        if role not in CONTRACT or selection is None:
            continue
        if selection.get('empty'):
            if role=='sales':
                raise ValueError('必须提供销售明细。')
            profile['tables'][role]={'files':[]}
            continue
        reference=selection['reference']
        identity=(reference['path'],reference.get('sheet_name'),int(selection.get('header_row',1)))
        if identity in used:
            raise ValueError('同一个工作表不能同时作为两种业务表，避免重复计入收入或费用。')
        used.append(identity)
        mapping={field:column for field,column in selection.get('mapping',{}).items() if column}
        if role=='sales':
            # One source ID is sufficient for the ordinary one-row-per-order import.
            # Keep distinct internal IDs when an advanced mapping already supplies both.
            if not selection.get('separate_line_id'):
                if mapping.get('order_id'):
                    mapping.setdefault('sale_line_id',mapping['order_id'])
                elif mapping.get('sale_line_id'):
                    mapping['order_id']=mapping['sale_line_id']
        defaults=deepcopy(OPTIONAL[role])
        if role=='sales' and 'quantity' in mapping:
            # A selected quantity column remains authoritative, including errors/blanks.
            defaults.pop('quantity',None)
        required=set(CONTRACT[role][1:])-set(defaults)
        missing=required-set(mapping)
        if missing:
            raise ValueError(ROLE_LABELS[role]+'缺少字段映射：'+'、'.join(FIELDS[field][0] for field in CONTRACT[role][1:] if field in missing))
        for column in set(mapping.values()):
            fields={field for field,original in mapping.items() if original==column}
            if len(fields)>1 and not (role=='sales' and fields=={'sale_line_id','order_id'}):
                raise ValueError(ROLE_LABELS[role]+'把同一原始列映射给了多个业务字段，请分别确认。')
        table=read_table(reference['path'],sheet_name=reference.get('sheet_name'),header_row=identity[2],limit=20)
        if set(mapping.values())-set(table.columns):
            raise ValueError('文件列名已变化，请重新确认字段映射。')
        setting={'files':[reference['path']],'mapping':mapping,'defaults':defaults,'header_row':identity[2],
                 'original_name':reference['name']}
        if role=='sales':
            setting['quantity_basis']='source_column' if 'quantity' in mapping else 'one_per_row'
        if reference.get('sheet_name') is not None:
            setting['sheet_name']=reference['sheet_name']
        if selection.get('round_money'):
            setting['money_rounding']='half_up'
        profile['tables'][role]=setting
    if 'sales' not in profile['tables']:
        raise ValueError('请选择销售明细工作表，并确认必需字段。')
    sales_selection=selections['sales']
    reference=sales_selection['reference']
    raw=read_table(reference['path'],sheet_name=reference.get('sheet_name'),header_row=int(sales_selection.get('header_row',1)),limit=20)
    candidates=recommend(profile,{'sales':raw.rows},{'sales':comments or raw.comments})
    available={row['field']:row for row in candidates}
    used_ids=set(BUILTINS)
    chosen=[];forecast=[];labels={}
    explicit=selected_headers or any(isinstance(value,dict) for value in dimension_fields)
    seen_fields=set();seen_labels=set()
    for selection in dimension_fields:
        field=selection['field'] if isinstance(selection,dict) else selection
        if field not in raw.columns:
            raise ValueError('分类来源表头不存在，请重新识别。')
        label=selection.get('label','').strip() if isinstance(selection,dict) else None
        if isinstance(selection,dict) and not label:raise ValueError('启用的分类名称不能为空。')
        if field in seen_fields or (label and label.casefold() in seen_labels):raise ValueError('分类字段或显示名称重复。')
        seen_fields.add(field)
        if label:seen_labels.add(label.casefold())
        builtin=next((key for key in BUILTINS if profile['tables']['sales']['mapping'].get(key)==field),None)
        if builtin:
            chosen.append(builtin)
            if label:labels[builtin]=label
            continue
        item=available.get(field,{})
        identifier=item.get('id','dim_'+hashlib.sha256(field.encode()).hexdigest()[:12])
        if identifier in used_ids:
            identifier='dim_'+hashlib.sha256(field.encode()).hexdigest()[:12]
        used_ids.add(identifier)
        profile['dimensions'].append({'id':identifier,'label':label or item.get('label') or (comments or raw.comments).get(field) or field,
                                      'bindings':{'sales':{'table':'sales','field':field,'raw_fields':True}}})
        chosen.append(identifier)
        if not isinstance(selection,dict):forecast.append(identifier)
    if explicit:
        profile['visible_dimensions']=chosen
        profile['dimension_labels']=labels
    profile['forecast_dimensions']=[*BUILTINS,*forecast]
    validate_profile(profile)
    return profile


def save_profile(profile, *, paths=None):
    paths=paths or AppPaths.current()
    folder=paths.profiles/'business_imports'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(hashlib.sha256((profile['entity_id']+':'+profile['profile_id']).encode()).hexdigest()+'.local.json')
    atomic_json(target,profile)
    return target


def saved_profiles(*, paths=None):
    paths=paths or AppPaths.current()
    result=[]
    for path in sorted((paths.profiles/'business_imports').glob('*.local.json')):
        try:
            profile=json.loads(path.read_text(encoding='utf-8'))
            validate_profile(profile)
            result.append(profile)
        except (ValueError,KeyError,TypeError,OSError):
            continue
    return result
