"""Header-first datasets: classification never invents financial meanings."""
from copy import deepcopy
from decimal import Decimal
import hashlib
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect, text

from .file_tables import MAX_CELLS, MAX_ROWS, read_table, scalar

ADAPTER='column_catalog_v1'


def table_id(reference):
    identity=Path(reference['name']).stem+'\0'+str(reference.get('sheet_name') or '')
    return 'table_'+hashlib.sha256(identity.encode()).hexdigest()[:16]


def column_id(table,field):
    return 'col_'+hashlib.sha256((table+'\0'+field).encode()).hexdigest()[:20]


def validate_catalog(profile):
    if profile.get('profile_version')!=2 or not profile.get('entity_id') or not profile.get('profile_id'):
        raise ValueError('分类接入缺少企业或稳定编号。')
    if profile.get('source',{}).get('kind') not in ('files','mysql') or not profile.get('tables'):
        raise ValueError('请选择至少一张数据表。')
    if {'password','url'} & set(profile['source'].get('connection',{})):
        raise ValueError('连接配置不能保存密码。')
    for name,setting in profile['tables'].items():
        seen=set();labels=set();fields=set()
        for item in setting.get('columns',[]):
            if item.get('id')!=column_id(name,item.get('field','')) or item['field'] in fields:
                raise ValueError('分类字段编号或来源重复，请重新识别。')
            fields.add(item['field'])
            if item.get('enabled'):
                label=item.get('label','').strip()
                if not label or len(label)>100 or label.casefold() in labels:
                    raise ValueError('同一张表内，启用的分类名称不能为空、超过100字或重复。')
                labels.add(label.casefold());seen.add(item['id'])
        if not fields:
            raise ValueError('数据表没有可识别的表头。')
        if not isinstance(setting.get('header_row',1),int) or not 1<=setting.get('header_row',1)<=100:
            raise ValueError('表头行应在1至100之间。')


def build_catalog(entity,name,specs,*,source=None):
    entity,name=entity.strip(),name.strip()
    if not entity or not name or len(entity)>80 or len(name)>100:
        raise ValueError('请填写企业/分析主体和接入名称（分别不超过80及100字）。')
    profile={'profile_version':2,'profile_id':'business-'+hashlib.sha256((entity+'\0'+name).encode()).hexdigest()[:24],
             'entity_id':entity,'display_name':name,'adapter':ADAPTER,'source':deepcopy(source or {'kind':'files'}),'tables':{}}
    for spec in specs:
        reference=spec['reference'];key=spec.get('table_id') or table_id(reference)
        if key in profile['tables']:
            raise ValueError('存在同名数据表，请分别命名文件或工作表。')
        setting={'display_name':reference['label'],'header_row':int(spec.get('header_row',1)),
                 'columns':[{'id':column_id(key,item['field']),'field':item['field'],
                             'label':str(item.get('label') or item['field']).strip() if not item.get('enabled') else str(item.get('label','')).strip(),
                             'enabled':bool(item.get('enabled'))} for item in spec['columns']]}
        if profile['source']['kind']=='files':
            setting.update(files=[reference['path']],original_name=reference['name'])
            if reference.get('sheet_name') is not None:setting['sheet_name']=reference['sheet_name']
        else:
            setting['table']=reference['name']
        profile['tables'][key]=setting
    validate_catalog(profile)
    return profile


def file_tables(profile):
    validate_catalog(profile)
    result={}
    for name,setting in profile['tables'].items():
        table=read_table(setting['files'][0],sheet_name=setting.get('sheet_name'),header_row=setting.get('header_row',1))
        validate_columns(setting,table.columns)
        result[name]=pd.DataFrame(table.rows,columns=table.columns,dtype=object)
    return result


def validate_columns(setting,columns):
    missing={item['field'] for item in setting['columns']}-set(columns)
    if missing:
        raise ValueError('原表头已失效，请重新识别并确认：'+'、'.join(sorted(missing)))
    if set(columns)-{item['field'] for item in setting['columns']}:
        raise ValueError('来源增加了新表头，请重新识别并确认，原分类暂不替换。')


def database_tables(engine,names):
    """A single read-only snapshot; UI edits never reconnect to the database."""
    result={};comments={}
    with engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        schema=inspect(connection)
        for name in names:
            columns=schema.get_columns(name)
            keys=[item['name'] for item in columns]
            if not keys:raise ValueError('数据表没有字段：'+name)
            maximum=min(MAX_ROWS,MAX_CELLS//len(keys))
            quoted=connection.dialect.identifier_preparer.quote(name)
            frame=pd.read_sql_query(text('SELECT * FROM '+quoted+f' LIMIT {maximum+1}'),connection,coerce_float=False)
            if len(frame)>maximum:raise ValueError('数据表过大，请先按期间或业务范围拆分：'+name)
            result[name]=frame.astype(object).where(pd.notna(frame),None)
            comments[name]={item['name']:item.get('comment') or '' for item in columns}
        connection.rollback()
    return result,comments


def category_value(value):
    value=scalar(value)
    return '未归属（缺失值）' if value is None or (isinstance(value,str) and not value.strip()) else str(value)


def summarize(frame,setting,groups,filters=None):
    enabled={item['id']:item for item in setting['columns'] if item['enabled']}
    if len(set(groups))!=len(groups) or not set(groups)<=set(enabled):
        raise ValueError('请选择已启用且不重复的分类。')
    selected=frame
    for key,values in (filters or {}).items():
        if key not in enabled:raise ValueError('原筛选分类已失效，请重新应用。')
        if values:
            column=frame[enabled[key]['field']].map(category_value)
            if not set(values)<=set(column):raise ValueError('原筛选对象已失效，请重新选择。')
            selected=selected.loc[column.loc[selected.index].isin(values)]
    if not groups:
        return selected,pd.DataFrame([{'记录数':len(selected)}])
    normalized=pd.DataFrame({key:selected[enabled[key]['field']].map(category_value) for key in groups})
    count_label='记录数'
    while count_label in {enabled[key]['label'] for key in groups}:count_label+='（统计）'
    result=normalized.groupby(groups,dropna=False,sort=False).size().reset_index(name=count_label)
    return selected,result.rename(columns={key:enabled[key]['label'] for key in groups})
