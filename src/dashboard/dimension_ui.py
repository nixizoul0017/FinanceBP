"""Locally rerun filter editor, with explicit, atomic application to analysis."""
from copy import deepcopy
import streamlit as st
from .exports import export_artifact
from .uploads import import_artifact
from etl.dimensions import profile_key
from .dimension_store import DimensionStore, clean_layout
from .filter_state import normalized, selection, errors, repaired

LEGACY_KEYS={'product_id':'product_filter','channel_id':'channel_filter','region_id':'region_filter'}


def value_key(field):
    return LEGACY_KEYS.get(field,'dim_value_'+field)


def _remember():
    request=st.session_state['_filter_applied']
    store=DimensionStore()
    if not store.remember(st.session_state['_dimension_scope'],request['layout'],
                          st.session_state['_dimension_known'],request['scheme']):
        st.session_state['dimension_notice']=store.warning


def _set_layout(layout,active=None,clear_values=False):
    st.session_state['dimension_layout']=deepcopy(layout)
    if clear_values:
        for field in st.session_state['_dimension_known']:
            st.session_state[value_key(field)]=[]
    for key in list(st.session_state):
        if key.startswith('dimension_slot_'):
            del st.session_state[key]
    for index,field in enumerate(layout['slots']):
        st.session_state['dimension_slot_'+str(index)]=field
    st.session_state['dimension_group_by']=list(layout['group_by'])
    st.session_state['dimension_scheme']=active


def _restore(request):
    st.session_state['_filter_draft']=deepcopy(request)
    _set_layout(request['layout'],request['scheme'],True)
    for field,values in request['objects'].items():
        st.session_state[value_key(field)]=list(values)
    for key,field in (('month','month'),('budget_version','version'),('display_unit','unit')):
        st.session_state[key]=request[field]


def discard_draft():
    if '_filter_applied' in st.session_state:
        request=st.session_state['_filter_applied']
        options=st.session_state.get('_filter_options')
        if options:
            request=repaired(request,*options)
        _restore(request)


def initialize(engine,profile,months,versions,default_month,default_unit,page):
    store_scope=engine.metadata.get('profile_id') or profile_key(profile)
    scope=engine.entity_id+'|'+store_scope
    known=list(engine.selectable_dimension_ids)
    st.session_state['_dimension_scope']=store_scope
    token=(scope,engine.metadata.get('source_fingerprint') or id(engine),tuple(known))
    fresh=st.session_state.get('_filter_snapshot')!=token
    if fresh:
        st.session_state['_filter_candidates']={field:engine.dimension_values(field) for field in known}
        st.session_state['_filter_snapshot']=token
    candidates=st.session_state['_filter_candidates']
    st.session_state['_filter_options']=(known,candidates,months,versions,default_month)
    if st.session_state.get('_filter_scope')!=scope:
        store=DimensionStore()
        layout,unknown,active=store.layout(store_scope,known)
        st.session_state['_dimension_scope']=store_scope
        st.session_state['_dimension_known']=known
        st.session_state['_filter_scope']=scope
        request={'month':default_month,'version':versions[0],
                 'unit':st.session_state.get('display_unit',default_unit),
                 'layout':layout,'objects':{},'scheme':active}
        st.session_state['_filter_applied']=normalized(request)
        st.session_state['_filter_invalid']=['保存的分类已失效：'+', '.join(unknown)] if unknown else []
        _restore(request)
        if store.warning:
            st.session_state['dimension_notice']=store.warning
    else:
        st.session_state['_dimension_known']=known
        invalid=errors(st.session_state['_filter_applied'],known,candidates,months,versions)
        if invalid:
            st.session_state['_filter_invalid']=invalid
            if fresh or st.session_state.get('_filter_page')!=page:
                _restore(repaired(st.session_state['_filter_applied'],known,candidates,months,versions,default_month))
        elif fresh or st.session_state.get('_filter_page')!=page:
            discard_draft()
    st.session_state['_filter_page']=page
    pending=st.session_state.pop('finance_pending_version',None)
    if pending in versions:
        # Publishing is an explicit business action, including selection of its result.
        request={**st.session_state['_filter_applied'],'version':pending}
        st.session_state['_filter_applied']=request
        _restore(request)


def _slot_changed(index):
    layout=deepcopy(st.session_state['dimension_layout'])
    old=layout['slots'][index]
    new=st.session_state['dimension_slot_'+str(index)]
    layout['slots'][index]=new
    for field in (old,new):
        if field:
            st.session_state[value_key(field)]=[]
    st.session_state['dimension_layout']=layout


def _apply_scheme():
    selected=st.session_state.get('dimension_scheme')
    scheme=next((x for x in DimensionStore().schemes(st.session_state['_dimension_scope']) if x['id']==selected),None)
    if scheme:
        try:
            layout,_=clean_layout(scheme['layout'],st.session_state['_dimension_known'])
            _set_layout(layout,selected,True)
        except ValueError as error:
            st.session_state['dimension_notice']=str(error)
            st.session_state['dimension_scheme']=None


def _group_changed():
    st.session_state['dimension_layout']['group_by']=list(st.session_state['dimension_group_by'])


def _add_slot():
    st.session_state['dimension_slot_'+str(len(st.session_state['dimension_layout']['slots']))]=None
    st.session_state['dimension_layout']['slots'].append(None)
    st.session_state['dimension_open_more']=True


def _remove_slot():
    field=st.session_state['dimension_layout']['slots'].pop()
    if field:
        st.session_state[value_key(field)]=[]


def _collect():
    layout=deepcopy(st.session_state['dimension_layout'])
    return {'month':st.session_state['month'],'version':st.session_state['budget_version'],
            'unit':st.session_state['display_unit'],'layout':layout,
            'objects':{field:list(st.session_state.get(value_key(field),[])) for field in layout['slots'] if field},
            'scheme':st.session_state.get('dimension_scheme')}


def _dirty():
    return bool(st.session_state.get('_filter_invalid')) or normalized(_collect())!=st.session_state['_filter_applied']


def _save_scheme(mode):
    if _dirty():
        st.session_state['dimension_notice']='请先应用筛选，再保存或更新方案。'
        return
    store=DimensionStore()
    scope=st.session_state['_dimension_scope']
    request=st.session_state['_filter_applied']
    active=request['scheme']
    try:
        schemes={item['id']:item for item in store.schemes(scope)}
        if mode=='delete':
            if not store.delete(scope,active):
                raise ValueError(store.warning)
            active=None
        else:
            name=(st.session_state.get('dimension_scheme_name','') if mode=='new' else
                  st.session_state.get('dimension_rename_'+active,'') if mode=='rename' else schemes[active]['name'])
            active=store.save_scheme(scope,name,request['layout'],st.session_state['_dimension_known'],None if mode=='new' else active)
        request={**request,'scheme':active}
        st.session_state['_filter_applied']=request
        st.session_state['_filter_draft']=deepcopy(request)
        st.session_state['dimension_scheme']=active
        st.session_state['dimension_notice']='方案已保存。' if active else '方案已删除，当前分析范围保持不变。'
    except (ValueError,KeyError) as error:
        st.session_state['dimension_notice']=str(error)


def _import_scheme():
    try:
        count=DimensionStore().import_schemes(st.session_state['_dimension_scope'],st.session_state['dimension_import'].getvalue(),st.session_state['_dimension_known'])
        st.session_state['dimension_notice']=f'已导入{count}个方案，请选择后应用。'
    except (ValueError,KeyError,TypeError) as error:
        st.session_state['dimension_notice']='未导入方案：'+str(error)


def _apply():
    request=normalized(_collect())
    known,candidates,months,versions,_=st.session_state['_filter_options']
    problems=errors(request,known,candidates,months,versions)
    if problems:
        st.session_state['dimension_notice']='；'.join(problems)+'，请重新选择后应用。'
        return False
    if request==st.session_state['_filter_applied'] and not st.session_state.get('_filter_invalid'):
        return False
    st.session_state['_filter_applied']=request
    st.session_state['_filter_draft']=deepcopy(request)
    st.session_state['_filter_invalid']=[]
    _remember()
    st.session_state['_filter_loading']=True
    return True


@st.fragment
def render_controls(engine,profile,page,months,versions,default_month,default_unit):
    # Widget events rerun only this area, leaving analysis and downloads untouched.
    draft=st.session_state['_filter_draft']
    for key,field in (('month','month'),('budget_version','version'),('display_unit','unit')):
        if key not in st.session_state:
            st.session_state[key]=draft[field]
    for field,values in draft['objects'].items():
        if value_key(field) not in st.session_state:
            st.session_state[value_key(field)]=list(values)
    columns=st.columns([2,2,1])
    options=[value for value in months if engine.is_complete(value)] if page=='预测与情景' else months
    if st.session_state['month'] not in options:
        options=sorted(set(options+[st.session_state['month']]))
    columns[0].selectbox('预测截止月份' if page=='预测与情景' else '分析月份',options,key='month')
    columns[1].selectbox('预算版本',versions,key='budget_version',format_func=lambda value:engine.metadata.get('budget_labels',{}).get(value,value))
    columns[2].selectbox('显示单位',['元','万元'],key='display_unit')
    if page in ('预算工作台','对账与跟进'):
        with st.expander('销售筛选与分析方案 · '+('不影响预算编制，按模板独立选择分类' if page=='预算工作台' else '仅作用于异常扫描，对账与确认采用公司范围')):
            render_filters(engine,profile)
    else:
        render_filters(engine,profile)
    if page=='维度分析':
        st.markdown('**分析分组**')
        st.caption('独立于范围筛选；列顺序按此选择顺序排列，点击应用后生效。')
        if 'dimension_group_by' not in st.session_state:
            st.session_state['dimension_group_by']=list(st.session_state['dimension_layout']['group_by'])
        st.multiselect('分组维度（顺序决定列顺序）',list(engine.selectable_dimension_ids),format_func=engine.dimension_labels.get,
                       key='dimension_group_by',on_change=_group_changed,placeholder='选择一个或多个分组维度')
    st.session_state['_filter_draft']=deepcopy(_collect())
    dirty=_dirty()
    if st.session_state.get('_filter_invalid'):
        st.warning('数据已更新，原条件含失效项目。请核对待选条件并重新应用；分析暂未扩大范围。'+'；'.join(st.session_state['_filter_invalid']))
    st.caption('● 有未应用的修改 · 下方分析与下载仍采用已应用条件' if dirty else '筛选已应用 · 可连续选择，确认后统一更新')
    actions=st.columns([1,1,3])
    if actions[0].button('应用筛选',key='filter_apply',type='primary',disabled=not dirty,width='stretch'):
        if _apply():
            st.rerun()
    actions[1].button('取消修改',key='filter_cancel',on_click=discard_draft,
                      disabled=not dirty and _collect()['layout']==st.session_state['_filter_applied']['layout'],width='stretch')


def render_filters(engine,profile):
    known=list(engine.selectable_dimension_ids)
    store=DimensionStore()
    scope=st.session_state['_dimension_scope']
    lookup={x['id']:x for x in store.schemes(scope)}
    active=st.session_state.get('dimension_scheme')
    if active not in lookup:
        st.session_state['dimension_scheme']=None
        active=None
    header=st.columns([3,1.2,1.2],vertical_alignment='bottom')
    header[0].selectbox('分析方案',[None,*lookup],format_func=lambda key:'最近使用 / 自定义' if key is None else lookup[key]['name'],
                        key='dimension_scheme',on_change=_apply_scheme,placeholder='最近使用 / 自定义')
    dirty=_dirty()
    with header[1].popover('保存方案',width='stretch',icon=':material/bookmark_add:'):
        st.text_input('方案名称',key='dimension_scheme_name',max_chars=60)
        st.button('另存为新方案',key='dimension_save_new',width='stretch',disabled=dirty,on_click=_save_scheme,args=('new',))
        if active in lookup:
            st.button('更新当前方案',key='dimension_update',width='stretch',disabled=dirty,on_click=_save_scheme,args=('update',))
        st.caption('请先应用筛选再保存或更新方案。只保存分类、顺序和分组，不保存对象、月份或密码。')
    with header[2].popover('方案管理',width='stretch',icon=':material/settings:'):
        if active in lookup:
            st.text_input('修改方案名称',value=lookup[active]['name'],key='dimension_rename_'+active,max_chars=60)
            st.button('重命名当前方案',key='dimension_rename',disabled=dirty,on_click=_save_scheme,args=('rename',))
            st.button('删除当前方案',key='dimension_delete',disabled=dirty,on_click=_save_scheme,args=('delete',))
        export_artifact('导出本企业方案',store.export(scope,engine.registry),file_name='FinanceBP_分类方案.json',mime='application/json',on_click='ignore',key='dimension_export')
        imported=import_artifact('导入分类方案',type='json',key='dimension_import')
        if imported:
            st.button('导入方案',key='dimension_import_apply',on_click=_import_scheme)
    notice=st.session_state.pop('dimension_notice',None)
    if notice:
        st.info(notice)
    layout=st.session_state['dimension_layout']
    def slot(index,column,values_column=None):
        current=layout['slots'][index]
        choices=[None,*[field for field in known if field==current or field not in layout['slots']]]
        key='dimension_slot_'+str(index)
        if key not in st.session_state:
            st.session_state[key]=current
        with column:
            field=st.selectbox(f'分类{index+1}',choices,format_func=lambda x:'未设置' if x is None else engine.dimension_labels[x],
                               key=key,on_change=_slot_changed,args=(index,))
        with values_column if values_column is not None else column:
            if field:
                st.multiselect(engine.dimension_labels[field]+'（留空表示全部）',st.session_state['_filter_candidates'][field],
                               format_func=lambda value:engine.dimension_text(field,value),key=value_key(field),placeholder='全部'+engine.dimension_labels[field])
            else:
                st.caption('选择一个分类维度')
    for index,column in enumerate(st.columns(3)):
        slot(index,column)
    extras=layout['slots'][3:]
    configured=sum(field is not None for field in extras)
    with st.expander(f'更多分类 · 已配置{configured}项',expanded=bool(configured) or st.session_state.pop('dimension_open_more',False)):
        for index in range(3,len(layout['slots'])):
            left,right=st.columns([1,2])
            slot(index,left,right)
        actions=st.columns(2)
        if len([x for x in layout['slots'] if x])<len(known):
            actions[0].button('添加分类',icon=':material/add:',key='dimension_add',on_click=_add_slot)
        if len(layout['slots'])>3:
            actions[1].button('移除最后一个位置',key='dimension_remove_last',on_click=_remove_slot)
    if configured:
        st.caption('待选额外分类：'+'、'.join(engine.dimension_labels[field] for field in extras if field))


def applied_scope(engine):
    request=st.session_state['_filter_applied']
    filters=selection(request)
    summary='公司全部销售' if filters.is_company else ' · '.join(engine.dimension_labels.get(field,field)+'：'+', '.join(engine.dimension_text(field,x) for x in values) for field,values in filters.items if values)
    return request,filters,summary
