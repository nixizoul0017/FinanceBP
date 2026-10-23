"""Select headers directly, then optionally define financial meanings later."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import inspect

from desktop.artifacts import safe_name
from etl.column_catalog import ADAPTER, build_catalog, column_id, database_tables, file_tables, summarize, table_id, validate_columns
from etl.common import db_engine
from etl.file_import import save_profile, table_references, suggest_mapping, recommended_classifications
from etl.file_tables import read_table
from dashboard.exports import export_artifact
from dashboard.profiles import file_identity
from dashboard.view_model import csv_bytes


def edit_columns(columns,key,existing=(),rows=(),default_fields=()):
    previous={item['field']:item for item in existing}
    data=[]
    for field in columns:
        prior=previous.get(field,{})
        samples=[str(row[field]) for row in rows if row.get(field) is not None][:3]
        data.append({'启用':bool(prior.get('enabled',field in default_fields)),'原表头':field,
                     '分类名称':prior.get('label',field),'样例':'、'.join(samples)[:160]})
    st.caption(f'识别到{len(columns)}个表头，全部可作为候选分类。勾选后启用，可直接修改分类名称；原表头保留。')
    edited=st.data_editor(pd.DataFrame(data),hide_index=True,width='stretch',height=min(480,75+35*len(data)),
                          disabled=['原表头','样例'],key=key,
                          column_config={'启用':st.column_config.CheckboxColumn('启用',width='small'),
                                         '分类名称':st.column_config.TextColumn('分类名称',required=True)})
    return [{'field':row['原表头'],'enabled':bool(row['启用']),'label':str(row.get('分类名称') or '')} for row in edited.to_dict('records')]


@st.cache_data(show_spinner=False,max_entries=48)
def preview_table(path,sheet,header,modified):
    return read_table(path,sheet_name=sheet,header_row=header,limit=20)


def file_catalog_inputs(staged,active=None):
    refs=table_references(staged)
    existing=(active or {}).get('tables',{}) if (active or {}).get('adapter')==ADAPTER else (active or {}).get('header_catalog',{})
    result=[]
    for ref in refs:
        identifier=table_id(ref);prior=existing.get(identifier,{})
        with st.expander(ref['label'],expanded=len(refs)==1):
            if not st.checkbox('导入这张表',value=True,key='catalog_include_'+ref['id']):continue
            header=1
            if Path(ref['path']).suffix.lower() in ('.xlsx','.xls','.xlsm','.csv','.tsv'):
                header=int(st.number_input('第几行作为表头 / 分类名称',min_value=1,max_value=100,
                                          value=prior.get('header_row',1),key='catalog_header_'+ref['id']))
            try:table=preview_table(ref['path'],ref.get('sheet_name'),header,Path(ref['path']).stat().st_mtime_ns)
            except (ValueError,OSError) as error:
                st.error(str(error));st.caption('请调整上方表头行，或取消导入这张表。');return None
            if not table.columns:
                st.warning('这张表没有表头，请调整表头行或取消导入。');continue
            st.dataframe(pd.DataFrame(table.rows,columns=table.columns),hide_index=True,width='stretch')
            key='catalog_columns_'+ref['id']+'_'+str(header)
            mapping=suggest_mapping('sales',table.columns,table.comments)
            financial={'order_id','revenue_date','sales_amount_before_refund'}<=set(mapping)
            defaults=recommended_classifications(table.columns) if financial and not active else ()
            if defaults:st.caption('建议分类：'+'、'.join(defaults)+'；可取消勾选、增加其他字段或改名。')
            columns=edit_columns(table.columns,key,prior.get('columns',[]),table.rows,default_fields=defaults)
            result.append({'reference':ref,'header_row':header,'columns':columns,'table_id':identifier})
    return result


def apply_catalog(candidate,on_apply,frames=None):
    frames=file_tables(candidate) if frames is None else frames
    for key,setting in candidate['tables'].items():validate_columns(setting,list(frames[key]))
    on_apply()
    st.session_state['_business_profile']=candidate
    st.session_state['_business_edit']=False
    st.session_state['_catalog_prepared']={'identity':file_identity(candidate),'tables':frames}
    try:save_profile(candidate)
    except OSError:st.session_state['_catalog_notice']='本次已生效，但接入配置暂时无法保存，请检查个人目录权限。'
    st.rerun()


def edit_catalog(financial=False):
    st.session_state['_business_edit']=True
    st.session_state['business_financial_mode']=financial
    st.rerun()


def render_database_importer(on_apply):
    active=st.session_state.get('_business_profile')
    if active and active.get('source',{}).get('kind')=='mysql' and not st.session_state.get('_business_edit'):
        st.sidebar.caption('当前接入：'+active.get('display_name',active['entity_id']))
        return deepcopy(active)
    st.title('连接数据库 · 按表头选择分类')
    st.caption('选择需要的表后读取一次；编辑分类不会重复连接。表头使用数据库列名，不需要指定第几行。仅执行读取。')
    settings=(active or {}).get('source',{}).get('connection',{})
    with st.form('catalog_connection'):
        cols=st.columns(2)
        host=cols[0].text_input('主机地址',value=settings.get('host','127.0.0.1'),key='catalog_db_host')
        port=cols[1].number_input('端口',min_value=1,max_value=65535,value=int(settings.get('port',3306)),key='catalog_db_port')
        database=cols[0].text_input('数据库名称',value=settings.get('database',''),key='catalog_db_database')
        user=cols[1].text_input('用户名',value=settings.get('user','root'),key='catalog_db_user')
        password=st.text_input('密码（仅本次连接，不写入配置）',type='password',key='catalog_db_password')
        scan=st.form_submit_button('连接并列出数据表')
    connection={'host':host,'port':int(port),'database':database,'user':user}
    token=hashlib.sha256(json.dumps(connection,sort_keys=True).encode()).hexdigest()
    loaded=st.session_state.get('_catalog_loaded',{})
    if active and active.get('adapter')==ADAPTER and active['source']['kind']=='mysql' and loaded.get('identity')==file_identity(active) and '_catalog_database_frames' not in st.session_state:
        raw={setting['table']:loaded['tables'][key] for key,setting in active['tables'].items()}
        st.session_state['_catalog_database_schema']={'token':token,'tables':list(raw)}
        st.session_state['_catalog_database_frames']={'token':token,'tables':raw,'comments':{}}
    if scan:
        engine=None
        try:
            engine=db_engine(connection,password=password)
            st.session_state['_catalog_database_schema']={'token':token,'tables':inspect(engine).get_table_names()}
        except Exception:st.error('连接失败，请核对数据库地址、账号和读取权限。')
        finally:
            if engine is not None:engine.dispose()
    schema=st.session_state.get('_catalog_database_schema',{})
    if schema.get('token')!=token:
        if active and st.button('取消修改',key='catalog_db_cancel'):
            st.session_state['_business_edit']=False;st.rerun()
        return None
    prior_names=[setting['table'] for setting in (active or {}).get('tables',{}).values() if 'table' in setting]
    names=st.multiselect('选择需要导入的数据表',schema['tables'],default=[name for name in prior_names if name in schema['tables']] or schema['tables'][:1],key='catalog_db_selected_'+token)
    if st.button('读取所选表并识别表头',key='catalog_db_read',disabled=not names):
        engine=None
        try:
            engine=db_engine(connection,password=password)
            with st.spinner('正在读取所选表…'):frames,comments=database_tables(engine,names)
            st.session_state['_catalog_database_frames']={'token':token,'tables':frames,'comments':comments}
        except Exception:st.error('无法读取所选表，请核对权限、数据类型或拆分过大的表。')
        finally:
            if engine is not None:engine.dispose()
    snapshot=st.session_state.get('_catalog_database_frames',{})
    if snapshot.get('token')!=token or set(snapshot.get('tables',{}))!=set(names):return None
    entity=st.text_input('企业 / 分析主体',value=(active or {}).get('entity_id','自定义企业'),key='catalog_db_entity')
    name=st.text_input('接入名称',value=(active or {}).get('display_name','数据库分类接入'),key='catalog_db_name')
    specs=[];frames={}
    for table,frame in snapshot['tables'].items():
        ref={'name':table,'sheet_name':None,'label':table}
        identifier=table_id(ref);prior=(active or {}).get('tables',{}).get(identifier,{})
        with st.expander(table,expanded=len(names)==1):
            st.dataframe(frame.head(20),hide_index=True,width='stretch')
            columns=edit_columns(list(frame),'catalog_db_columns_'+token+identifier,prior.get('columns',[]),frame.head(20).to_dict('records'))
        specs.append({'reference':ref,'table_id':identifier,'columns':columns});frames[identifier]=frame
    confirmed=st.checkbox('已核对所选表头、分类勾选及显示名称，确认导入。',key='catalog_db_confirm')
    if st.button('确认分类并导入',key='catalog_db_apply',type='primary',disabled=not confirmed):
        try:
            candidate=build_catalog(entity,name,specs,source={'kind':'mysql','connection':connection})
            st.session_state['_catalog_clear_password']=True
            apply_catalog(candidate,on_apply,frames)
        except (ValueError,OSError) as error:st.error(str(error))
    return None


def render_catalog_workspace(profile,page):
    identity=file_identity(profile)
    prepared=st.session_state.pop('_catalog_prepared',None)
    if prepared and prepared['identity']==identity:
        st.session_state['_catalog_loaded']={**prepared,'profile_id':profile['profile_id']}
    loaded=st.session_state.get('_catalog_loaded',{})
    if loaded.get('identity')!=identity:
        if profile['source']['kind']=='files':
            try:
                with st.spinner('正在读取已确认的数据表…'):frames=file_tables(profile)
                loaded={'identity':identity,'tables':frames};st.session_state['_catalog_loaded']=loaded
            except (ValueError,OSError) as error:
                st.error(str(error));st.button('重新识别表头',on_click=edit_catalog,key='catalog_repair');return
        else:
            st.info('请输入密码，重新读取已保存的数据库接入。')
            with st.form('catalog_resume_database'):
                password=st.text_input('连接密码（不保存）',type='password',key='catalog_resume_password')
                resume=st.form_submit_button('读取数据库')
            if resume:
                engine=None
                try:
                    engine=db_engine(profile['source']['connection'],password=password)
                    raw,_=database_tables(engine,[item['table'] for item in profile['tables'].values()])
                    frames={key:raw[setting['table']] for key,setting in profile['tables'].items()}
                    for key,frame in frames.items():validate_columns(profile['tables'][key],list(frame))
                    st.session_state['_catalog_loaded']={'identity':identity,'tables':frames}
                    st.session_state['_catalog_clear_password']=True;st.rerun()
                except Exception:st.error('读取失败或表头已变化，请重新识别分类。')
                finally:
                    if engine is not None:engine.dispose()
            st.button('分类与映射',on_click=edit_catalog,key='catalog_resume_edit');return
    st.sidebar.button('分类与映射',key='open_dimension_setup',on_click=edit_catalog,width='stretch')
    st.sidebar.caption('当前为表头分类接入；分类与显示名称已保存在本机。')
    st.title(profile['display_name'])
    st.caption('已导入数据 → 选择分类汇总；可随时在左侧“分类与映射”勾选、改名或修改表头行。')
    if st.session_state.get('_catalog_notice'):st.warning(st.session_state['_catalog_notice'])
    key=st.selectbox('当前数据表',list(profile['tables']),format_func=lambda key:profile['tables'][key]['display_name'],key='catalog_current_table')
    setting=profile['tables'][key];frame=loaded['tables'][key]
    enabled={item['id']:item for item in setting['columns'] if item['enabled']}
    counts=st.columns(3)
    counts[0].metric('记录数',len(frame));counts[1].metric('识别表头',len(setting['columns']));counts[2].metric('启用分类',len(enabled))
    st.caption('记录数按原表行数统计；各表独立查看，不自动拼接或复制金额。')
    context=profile['profile_id']+':'+key
    request=st.session_state.setdefault('_catalog_requests',{}).get(context,{'groups':list(enabled)[:1],'filters':{}})
    invalid=not set(request['groups'])<=set(enabled) or not set(request['filters'])<=set(enabled)
    with st.form('catalog_filters_'+key):
        groups=st.multiselect('分析分组（顺序决定结果列顺序）',list(enabled),default=[value for value in request['groups'] if value in enabled],format_func=lambda value:enabled[value]['label'],key='catalog_group_'+key)
        filters={}
        def picker(field,item):
            from etl.column_catalog import category_value
            values=sorted(set(frame[item['field']].map(category_value)))
            filters[field]=st.multiselect(item['label'],values,default=[value for value in request['filters'].get(field,[]) if value in values],key='catalog_filter_'+key+field)
        items=list(enabled.items());cols=st.columns(3)
        for index,(field,item) in enumerate(items[:3]):
            with cols[index]:picker(field,item)
        if len(items)>3:
            with st.expander(f'更多分类（{len(items)-3}）',expanded=True):
                extra=st.columns(3)
                for index,(field,item) in enumerate(items[3:]):
                    with extra[index%3]:picker(field,item)
        submitted=st.form_submit_button('应用分类',type='primary')
    if submitted:
        request={'groups':groups,'filters':{field:values for field,values in filters.items() if values}}
        st.session_state['_catalog_requests'][context]=request
        invalid=False
    if invalid:
        st.warning('分类设置已改变，请核对并应用分类后继续。');return
    try:selected,grouped=summarize(frame,setting,request['groups'],request['filters'])
    except ValueError as error:st.warning(str(error));return
    if page not in ('经营总览','维度分析','数据与下载'):
        st.info('当前已完成分类导入。收入、毛利、预算和预测等财务指标，需要另行确认日期、金额及业务口径。')
        if profile['source']['kind']=='files':st.button('设置财务分析（可选）',on_click=edit_catalog,args=(True,),key='catalog_enable_finance')
    st.subheader('分类汇总 · 记录数')
    st.caption(f'已应用范围：{len(selected)}条记录；{len(grouped)}组。这里只按分类统计记录数，不将任意数值列认定为收入或成本。')
    st.dataframe(grouped,hide_index=True,width='stretch')
    export_artifact('下载分类汇总（CSV）',csv_bytes(grouped),file_name=safe_name(profile['display_name']+'_分类汇总.csv'),mime='text/csv',key='catalog_download_groups',on_click='ignore')
    with st.expander('查看已导入记录',expanded=page=='数据与下载'):
        st.dataframe(selected.head(1000),hide_index=True,width='stretch')
        st.caption('页面最多预览1000条，下载包含当前范围全部记录。')
        export_artifact('下载当前记录（CSV）',csv_bytes(selected),file_name=safe_name(profile['display_name']+'_记录.csv'),mime='text/csv',key='catalog_download_data',on_click='ignore')
