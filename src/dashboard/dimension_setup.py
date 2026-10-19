"""First-use confirmation of detected categories; no source database writes."""
from copy import deepcopy
import hashlib

import pandas as pd
import streamlit as st

from etl.dimensions import BUILTINS, validate_dimensions


def render_setup(profile, scan, confirm):
    if not st.session_state.get('dimension_setup_open'):
        return
    draft=st.session_state.get('dimension_draft_profile',profile)
    preview=st.session_state.get('dimension_preview')
    with st.container(key='dimension_setup_panel',border=True):
        title,close=st.columns([5,1])
        title.markdown('### 数据分类 · 识别与确认')
        if close.button('关闭',key='dimension_setup_close'):
            st.session_state['dimension_setup_open']=False
            st.rerun()
        st.caption('只检查配置中的业务表。分类推荐不是业务含义的确认；销售部门与费用部门分别处理。')
        password=st.text_input('分类识别连接密码（仅本次验证）',type='password',key='dimension_setup_password') if draft['source']['kind']=='mysql' else None
        if st.button('扫描字段 / 重新识别',key='dimension_scan',type='primary'):
            try:
                preview=scan(draft,password)
                st.session_state['dimension_preview']=preview
                st.session_state['dimension_draft_profile']=deepcopy(draft)
                st.success('扫描完成，请确认分类含义后保存。')
            except Exception:
                st.error('扫描失败，请核对连接、密码、表名与读取权限。')
        with st.expander('添加关联分类表（可选）'):
            st.caption('只支持多对一关联；一条销售对应多个员工时，需要另行定义分配规则。')
            alias=st.text_input('关联表配置名称',key='dimension_lookup_alias',placeholder='例如 employees')
            location=st.text_input('MySQL表名' if draft['source']['kind']=='mysql' else '本机CSV文件路径',key='dimension_lookup_location')
            if st.button('加入配置并扫描',key='dimension_lookup_add'):
                try:
                    if not alias.strip() or alias in draft['tables'] or not location.strip():
                        raise ValueError('请输入新的配置名称和有效来源位置')
                    updated=deepcopy(draft)
                    updated['tables'][alias.strip()]={'table':location.strip()} if draft['source']['kind']=='mysql' else {'files':[location.strip()]}
                    updated['lookup_tables']=[*draft.get('lookup_tables',[]),alias.strip()]
                    updated['profile_version']=2
                    preview=scan(updated,password)
                    st.session_state['dimension_draft_profile']=updated
                    st.session_state['dimension_preview']=preview
                    st.rerun()
                except Exception:
                    st.error('无法加入关联表，请核对名称、文件路径或数据库读取权限。')
        if not preview:
            st.info('先扫描字段，再选择需要启用的分类。')
            return
        fields=preview['fields']
        candidates=preview['candidates']
        st.markdown(f'**发现{len(candidates)}个候选字段 · 当前已确认{len(BUILTINS)+len(draft.get("dimensions",[]))}个分类维度**')
        if candidates:
            st.dataframe(pd.DataFrame([{'来源表':x['table'],'字段':x['field'],'建议名称':x['label'],'字段类型':x.get('type','unknown'),'建议启用':'是' if x['recommended'] else '手动确认',
                                       '样例（最多5个）':'、'.join(x['sample_values']),'样本缺失率':f"{x['missing_rate']:.1%}",'字段注释':x.get('comment','')} for x in candidates]),hide_index=True,width='stretch')
        options=[x['table']+'.'+x['field'] for x in candidates]
        candidate_map=dict(zip(options,candidates))
        chosen=st.multiselect('选择准备启用的候选分类',options,format_func=lambda key:candidate_map[key]['label']+' · '+key,key='dimension_candidates',placeholder='选择后在下方确认映射')
        if st.button('把所选候选加入编辑区',key='dimension_candidates_add'):
            specs=deepcopy(st.session_state.get('dimension_edit_specs',draft.get('dimensions',[])))
            used={x['id'] for x in specs}
            for key in chosen:
                item=candidate_map[key]
                if any(x['bindings']['sales']['table']==item['table'] and x['bindings']['sales']['field']==item['field'] for x in specs):
                    continue
                identifier=item['id']
                if identifier in used:
                    identifier='dim_'+hashlib.sha256(key.encode()).hexdigest()[:12]
                used.add(identifier)
                specs.append({'id':identifier,'label':item['label'],'bindings':{'sales':{'table':item['table'],'field':item['field']}}})
            st.session_state['dimension_edit_specs']=specs
            st.rerun()
        if st.button('手动添加分类',key='dimension_manual_add'):
            specs=deepcopy(st.session_state.get('dimension_edit_specs',draft.get('dimensions',[])))
            table='sales' if 'sales' in fields else 'orders'
            specs.append({'id':'dim_custom_'+str(len(specs)+1),'label':'新分类','bindings':{'sales':{'table':table,'field':fields[table][0]}}})
            st.session_state['dimension_edit_specs']=specs
            st.rerun()
        specs=st.session_state.get('dimension_edit_specs',draft.get('dimensions',[]))
        edited=[]
        sales_tables=[name for name in fields if name not in ('sales_budget','budget_sales','expenses','expense_budget','budget_expenses')]
        for index,spec in enumerate(specs):
            prefix='dimension_mapping_'+str(index)+'_'
            with st.expander(spec['label']+' · '+spec['id'],expanded=True):
                enabled=st.checkbox('启用这个分类',value=True,key=prefix+'enabled')
                columns=st.columns(2)
                identifier=columns[0].text_input('稳定编号',value=spec['id'],key=prefix+'id',help='改显示名称不改编号，记忆和方案才能继续匹配。')
                label=columns[1].text_input('显示名称',value=spec['label'],key=prefix+'label')
                original=spec['bindings']['sales']
                table=st.selectbox('销售归属字段所在表',sales_tables,index=sales_tables.index(original['table']) if original['table'] in sales_tables else 0,key=prefix+'table')
                field=st.selectbox('分类编码字段',fields[table],index=fields[table].index(original['field']) if original['field'] in fields[table] else 0,key=prefix+'field')
                binding={'table':table,'field':field}
                name_options=[None,*fields[table]]
                name_field=st.selectbox('显示名称字段（可选）',name_options,index=name_options.index(original.get('name_field')) if original.get('name_field') in name_options else 0,format_func=lambda x:'使用分类编码' if x is None else x,key=prefix+'name')
                if name_field:
                    binding['name_field']=name_field
                if table not in ('sales','orders','order_items','products','customers'):
                    cols=st.columns(2)
                    binding['sales_key']=cols[0].selectbox('销售记录关联键',['sale_line_id','order_id','product_id'],key=prefix+'left')
                    binding['source_key']=cols[1].selectbox('分类表唯一关联键',fields[table],key=prefix+'right')
                lookup_old=original.get('lookup',{})
                lookup_options=[None,*[name for name in fields if name!=table]]
                lookup_table=st.selectbox('通过唯一键关联名称或其他分类（可选）',lookup_options,index=lookup_options.index(lookup_old.get('table')) if lookup_old.get('table') in lookup_options else 0,format_func=lambda x:'不关联其他表' if x is None else x,key=prefix+'lookup')
                if lookup_table:
                    keys=fields[lookup_table]
                    right=st.selectbox('关联表唯一键',keys,index=keys.index(lookup_old['key']) if lookup_old.get('key') in keys else 0,key=prefix+'lookup_key')
                    value_options=[None,*keys]
                    value=st.selectbox('关联后使用的分类编码',value_options,index=value_options.index(lookup_old.get('value_field')) if lookup_old.get('value_field') in value_options else 0,format_func=lambda x:'保留原分类编码' if x is None else x,key=prefix+'lookup_value')
                    name=st.selectbox('关联后的名称字段',value_options,index=value_options.index(lookup_old.get('name_field')) if lookup_old.get('name_field') in value_options else 0,format_func=lambda x:'无名称字段' if x is None else x,key=prefix+'lookup_name')
                    binding['lookup']={'table':lookup_table,'key':right,**({'value_field':value} if value else {}),**({'name_field':name} if name else {})}
                    st.caption('员工当前资料不会自动成为历史部门归属；请优先使用交易时点归属字段。')
                bindings={'sales':binding}
                budget_table='sales_budget' if 'sales_budget' in fields else 'budget_sales' if 'budget_sales' in fields else None
                if budget_table:
                    budget_old=spec['bindings'].get('sales_budget',{})
                    has_budget=st.checkbox('销售预算也提供此分类',value=bool(budget_old),key=prefix+'has_budget')
                    if has_budget:
                        keys=fields[budget_table]
                        old_field=budget_old.get('field',field)
                        budget_field=st.selectbox('销售预算分类字段',keys,index=keys.index(old_field) if old_field in keys else 0,key=prefix+'budget_field')
                        bindings['sales_budget']={'table':budget_table,'field':budget_field}
                        available_versions=preview.get('budget_versions',[])
                        if available_versions:
                            applicable=st.multiselect('适用预算版本（空表示全部）',available_versions,default=budget_old.get('versions',[]),key=prefix+'budget_versions')
                            if applicable:
                                bindings['sales_budget']['versions']=applicable
                forecast=st.checkbox('用于细分预测（仍需足够且完整的历史归属）',value=spec['id'] in draft.get('forecast_dimensions',[x['id'] for x in specs]),key=prefix+'forecast')
                if enabled:
                    edited.append({'id':identifier.strip(),'label':label.strip(),'bindings':bindings,'forecast':forecast})
        submitted=st.button('确认分类并验证数据',type='primary',width='stretch')
        if submitted:
            candidate=deepcopy(draft)
            candidate['profile_version']=2
            candidate['forecast_dimensions']=[*BUILTINS,*[item['id'] for item in edited if item['forecast']]]
            candidate['dimensions']=[{key:value for key,value in item.items() if key!='forecast'} for item in edited]
            try:
                validate_dimensions(candidate)
                with st.spinner('正在校验关联、行数与金额…'):
                    confirm(candidate,password)
                st.session_state['dimension_setup_open']=False
                st.session_state['clear_dimension_password_next']=True
                st.rerun()
            except ValueError as error:
                st.error('分类未保存：'+str(error))
            except Exception:
                st.error('分类验证失败，请核对连接密码、关联键、字段与数据完整性；原映射未替换。')
