"""Local financial workflow screens, kept separate from the analytical cockpit."""
from datetime import date
from decimal import Decimal
import json
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from .exports import export_artifact
from .uploads import import_artifact

from analysis.historical import historical_variance, REASONS as HISTORY_REASONS
from .result_cache import cached_result
from analysis.metrics import Filters
from analysis.forecast_store import content_digest
from etl.common import encode
from .view_model import csv_bytes, money_text, percent_text
from finance.budgets import workbook_bytes, parse_workbook, FEE_KEYS, LABELS
from finance.reconciliation import reconciliation, compare_snapshot, CONTROL_FIELDS
from finance.issues import DEFAULTS, STATUSES, detect_issues
from finance.store import WorkspaceError

MIME='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def json_download(label,value,filename,key):
    export_artifact(label,json.dumps(value,ensure_ascii=False,indent=2,default=encode,allow_nan=False).encode('utf-8'),file_name=filename+'.json',mime='application/json',key=key,on_click='ignore')


def frame(rows,labels=None):
    names={**LABELS,'at':'操作时间','object_id':'对象编号','object_type':'对象类型','action':'操作','actor':'记录人','note':'说明',
           'revision':'修订','created_at':'创建时间','released_at':'解除时间','release_actor':'解除人','release_reason':'解除原因',
           'product_id':'商品编码','product_state':'成交状态','q_base':'基期件数','q_actual':'本期件数','revenue_base':'基期退款前收入（元）','revenue_actual':'本期退款前收入（元）',
           'cost_base':'基期成交成本（元）','cost_actual':'本期成交成本（元）','refund_base':'基期退款（元）','refund_actual':'本期退款（元）',
           'reversal_base':'基期成本转回（元）','reversal_actual':'本期成本转回（元）','price_base':'基期均价（元）','price_actual':'本期均价（元）','unit_cost_base':'基期单位成本（元）','unit_cost_actual':'本期单位成本（元）',**(labels or {})}
    return pd.DataFrame([{key:'—' if value is None else money_text(value) if isinstance(value,Decimal) else value for key,value in row.items()} for row in rows],dtype=object).rename(columns=names)


def budget_workbench(engine,store,context,month):
    st.caption('下载模板 → 填写 → 上传校验 → 保存草稿 → 确认发布。已发布版本才进入上方预算选择；全部记录按企业及接入配置隔离。')
    st.info('金额预算填写扣除退款后的净收入、净成本。驱动预算填写退款前销量、均价及独立退款。费用始终为公司全口径。')
    tag=content_digest(context)[:16]
    message=st.session_state.pop('finance_notice',None)
    if message:
        st.success(message)
    tabs=st.tabs(['编制与导入','版本与发布','操作记录'])
    with tabs[0]:
        c=st.columns(2)
        year=c[0].number_input('预算年度',2000,2100,int(month[:4]),key='budget_year_'+tag)
        mode=c[1].selectbox('填写方式',['amounts','drivers'],format_func=lambda v:'金额预算（净收入、净成本）' if v=='amounts' else '驱动预算（销量、均价、成本、退款）',key='budget_mode_'+tag)
        grain=st.multiselect('销售预算分类（留空为公司合计）',list(engine.dimension_ids),format_func=engine.dimension_labels.get,key='budget_grain_'+tag)
        expense_grain=st.multiselect('费用预算分类（留空为公司费用合计）',list(FEE_KEYS),format_func=LABELS.get,key='budget_fee_grain_'+tag)
        st.caption('分类越细，需要填写的预算行越多；系统不会把公司预算自动分摊到销售员或商品。')
        export_artifact('下载当前企业预算模板',workbook_bytes(engine,year,grain,mode,expense_grain),file_name=f'{engine.entity_id}_{year}_预算模板.xlsx',mime=MIME,key='budget_template_'+tag,on_click='ignore')
        upload=import_artifact('上传已填写的预算模板',type=['xlsx'],key='budget_upload_'+tag,max_upload_size=20)
        allow_new=st.checkbox('允许明确的新业务计划编码（会保留提示）',key='budget_allow_new_'+tag)
        dataset=None
        if upload:
            try:
                dataset=parse_workbook(upload.getvalue(),engine,allow_new)
                st.success(f"校验通过：销售预算 {len(dataset['sales'])} 行，费用预算 {len(dataset['expenses'])} 行。")
                for warning in dataset['warnings']:
                    st.warning(warning)
                st.caption('预览金额为元、显示至分，空白成本保持未知；版本文件与JSON保留原精度。')
                if dataset['sales']:
                    st.dataframe(frame(dataset['sales'][:200],engine.dimension_labels),hide_index=True,width='stretch')
                else:
                    st.info('此文件未填写销售预算，销售预算保持未知。')
                if dataset['expenses']:
                    st.dataframe(frame(dataset['expenses'][:200]),hide_index=True,width='stretch')
                else:
                    st.info('此文件未填写公司费用预算，费用预算保持未知。')
            except WorkspaceError as error:
                st.error(str(error))
        versions=store.budgets(context)
        published={row['id']:row for row in versions if row['status']=='published'}
        if dataset:
            with st.form('budget_new_'+tag):
                name=st.text_input('预算名称',placeholder=f'{year}年度原始预算',max_chars=60)
                actor=st.text_input('编制人',max_chars=60)
                kind=st.selectbox('预算性质',['original','adjustment'],format_func=lambda v:'原始预算' if v=='original' else '调整预算')
                parent=st.selectbox('调整所依据的版本',[None,*published],format_func=lambda v:'原始预算可留空' if v is None else published[v]['name'])
                note=st.text_area('编制说明',max_chars=2000)
                if st.form_submit_button('保存为预算草稿',type='primary'):
                    try:
                        row=store.save_budget(context,name,kind,dataset,actor,note,parent_id=parent if kind=='adjustment' else None)
                        st.session_state['finance_notice']='草稿已保存。请在“版本与发布”中核对并发布，发布前不会改变分析。'
                        st.session_state['budget_saved_id']=row['id']
                        st.rerun()
                    except WorkspaceError as error:
                        st.error(str(error))
    with tabs[1]:
        versions=store.budgets(context)
        if not versions:
            st.info('还没有本机预算。原数据库中的预算仍可在上方选择。')
        else:
            lookup={row['id']:row for row in versions}
            selected=st.selectbox('本机预算版本',list(lookup),format_func=lambda v:lookup[v]['name']+' · '+('已发布' if lookup[v]['status']=='published' else '草稿'),key='budget_local_version_'+tag)
            row=lookup[selected]
            d=row['dataset']
            st.caption(f"年度 {d['year']} · {'原始预算' if row['kind']=='original' else '调整预算'} · 修订 {row['revision']} · 编制人 {row['creator']} · 确认人 {row['approver'] or '尚未确认'}")
            if row['parent_id']:
                st.caption('关联原版本：'+lookup.get(row['parent_id'],{}).get('name',row['parent_id']))
            st.caption('销售分类：'+('、'.join(engine.dimension_labels.get(f,f) for f in d['grain']) or '公司合计')+'；费用分类：'+('、'.join(LABELS[f] for f in d['expense_grain']) or '公司合计'))
            if d['sales']:
                st.dataframe(frame(d['sales'][:200],engine.dimension_labels),hide_index=True,width='stretch')
            if d['expenses']:
                st.dataframe(frame(d['expenses'][:200]),hide_index=True,width='stretch')
            try:
                export_artifact('下载此版本明细（可另存修改）',workbook_bytes(engine,d['year'],dataset=d),file_name=row['name']+'.xlsx',mime=MIME,key='budget_download_version_'+tag,on_click='ignore')
            except WorkspaceError as error:
                st.warning(str(error))
            json_download('下载此版本及追溯信息',row,row['id'],'budget_json_'+tag)
            if row['status']=='draft':
                with st.form('budget_publish_'+selected+'_'+str(row['revision'])):
                    actor=st.text_input('发布确认人',max_chars=60)
                    note=st.text_area('发布说明',max_chars=2000)
                    checked=st.checkbox('我已核对企业、年度、分类粒度和金额，确认将此版本发布到分析中')
                    if st.form_submit_button('确认发布预算',type='primary'):
                        try:
                            if not checked:
                                raise WorkspaceError('请先完成核对并勾选确认')
                            store.publish_budget(context,selected,actor,note,row['revision'])
                            st.session_state['finance_pending_version']=selected
                            st.session_state['finance_notice']='预算已发布，上方已切换到此版本。发布内容锁定；后续修改请新建调整预算。'
                            st.rerun()
                        except WorkspaceError as error:
                            st.error(str(error))
                if dataset:
                    with st.form('budget_replace_'+selected+'_'+str(row['revision'])):
                        st.caption('使用“编制与导入”中当前校验通过的文件替换此草稿。')
                        actor=st.text_input('替换草稿编制人')
                        note=st.text_input('替换说明')
                        if st.form_submit_button('用上传内容更新草稿'):
                            try:
                                store.save_budget(context,row['name'],row['kind'],dataset,actor,note,identity=selected,expected_revision=row['revision'],parent_id=row['parent_id'])
                                st.rerun()
                            except WorkspaceError as error:
                                st.error(str(error))
            else:
                st.success('此预算已锁定。原内容、编制人、确认人和变更依据会保留。')
                with st.form('budget_clone_'+selected):
                    name=st.text_input('新调整预算名称',max_chars=60)
                    actor=st.text_input('调整预算编制人',max_chars=60)
                    note=st.text_input('调整原因')
                    if st.form_submit_button('从此版本建立调整草稿'):
                        try:
                            store.save_budget(context,name,'adjustment',d,actor,note,parent_id=selected)
                            st.session_state['finance_notice']='调整草稿已建立，可下载修改后上传替换草稿。'
                            st.rerun()
                        except WorkspaceError as error:
                            st.error(str(error))
    with tabs[2]:
        audit=[row for row in store.audit(context) if row['object_type']=='budget']
        st.dataframe(frame([{key:row[key] for key in ('at','object_id','action','actor','note')} for row in audit]),hide_index=True,width='stretch')
        json_download('下载预算操作记录',audit,'预算操作记录','budget_audit_'+tag)


def history_mode():
    if st.session_state.get('history_mode') not in ('mom','yoy'):
        st.session_state['history_mode']=st.session_state.get('_history_mode','mom')
    mode=st.radio('历史比较方式',['mom','yoy'],format_func=lambda value:'环比 · 上一个自然月' if value=='mom' else '同比 · 上年同月',horizontal=True,key='history_mode',on_change=lambda:st.session_state.update(_history_mode=st.session_state['history_mode']))
    return mode


def historical_panel(engine,month,filters,group_by,theme):
    st.markdown('### 经营变化解释 · 无需预算')
    mode=history_mode()
    history=cached_result(engine,'historical',(month,filters,mode,group_by),lambda:historical_variance(engine,month,filters,mode,group_by))
    base_month=str(history['metadata']['base_month'])[:7]
    st.caption(f'本期 {month} 对比历史实际 {base_month}。先计算共同商品销量、结构、价格，再单列本期/基期未成交商品和退款变化。金额分解不等于业务原因。')
    choice=st.selectbox('拆解指标',['revenue_bridge','gross_margin_bridge','operating_bridge'],format_func={'revenue_bridge':'当前范围 · 净收入','gross_margin_bridge':'当前范围 · 毛利','operating_bridge':'公司 · 经营利润'}.get,key='history_metric')
    bridge=history[choice]
    if bridge['status']!='complete':
        reason=HISTORY_REASONS.get(bridge['reason'],'销售筛选范围不分摊公司费用，无法形成分类经营利润')
        st.info('本项拆解不可用：'+reason+'。当前筛选保持有效。')
    else:
        rows=bridge['components']
        figure=go.Figure(go.Waterfall(x=[base_month+' 实际',*[r['factor_label'] for r in rows],month+' 实际'],measure=['absolute',*['relative']*len(rows),'total'],y=[float(bridge['base']),*[float(r['amount']) for r in rows],0],connector={'line':{'color':theme.muted}},totals={'marker':{'color':theme.primary}},increasing={'marker':{'color':theme.success}},decreasing={'marker':{'color':theme.danger}}))
        figure.update_layout(height=390,margin=dict(l=20,r=20,t=20,b=35),paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',yaxis_title='人民币不含税元')
        st.plotly_chart(figure,width='stretch',config={'displaylogo':False})
        displayed=[{'因素':r['factor_label'],'金额贡献（元）':money_text(r['amount'])} for r in rows]
        shown=sum((Decimal(r['金额贡献（元）'].replace(',','')) for r in displayed),Decimal(0))
        residual=Decimal(money_text(bridge['variance']).replace(',',''))-shown
        if residual:
            displayed.append({'因素':'显示舍入尾差（非经营因素）','金额贡献（元）':money_text(residual)})
        st.dataframe(frame(displayed),hide_index=True,width='stretch')
        st.caption('分解合计与实际差额精确勾稽；跨月退款按退款发生月和原销售归属计入。')
    with st.expander('查看商品与分类的历史比较'):
        st.dataframe(frame(history['products']),hide_index=True,width='stretch')
        ranked=[{**{field:r[field] for field in group_by},'本期净收入（元）':r['net_revenue']['current'],'基期净收入（元）':r['net_revenue']['base'],'变化额（元）':r['net_revenue']['change_amount'],'变化率':r['net_revenue']['change_rate']} for r in history['rankings']]
        st.dataframe(frame(ranked),hide_index=True,width='stretch')
        export_artifact('下载历史分类变化（精确元）',csv_bytes(pd.DataFrame(ranked)),file_name=f'{engine.entity_id}_{month}_{mode}_历史分类变化.csv',mime='text/csv',key='history_csv',on_click='ignore')
    json_download('下载历史差异解释包（精确JSON）',history,f'{engine.entity_id}_{month}_{mode}_历史差异','history_json')


def finance_workbench(engine,store,context,month,filters,version,group_by):
    st.caption('对账及月份确认使用公司全口径。异常扫描采用当前销售筛选及分组；公司费用不会分摊给销售员。所有记录保存在本机财务工作区。')
    tab1,tab2,tab3=st.tabs(['财务对账','月份确认','异常跟进'])
    tag=content_digest(context)[:16]+'_'+month
    controls=store.controls(context,month)
    rec=reconciliation(engine,month,controls)
    with tab1:
        st.caption(rec['source_basis']+'。独立参考值请取自总账、业务系统核对表等外部依据，不能复制本页合计作为核对依据。允许尾差为0.01元。')
        st.dataframe(frame([{k:v for k,v in row.items() if k!='field'} for row in rec['rows']]),hide_index=True,width='stretch')
        with st.form('finance_controls_'+tag):
            st.markdown('#### 录入独立核对依据')
            values={}
            cols=st.columns(2)
            for index,(field,label) in enumerate(CONTROL_FIELDS.items()):
                value=(controls or {}).get('amounts',{}).get(field)
                values[field]=cols[index%2].text_input(label+'（元）',value='' if value is None else str(value),key='control_'+field+'_'+tag,placeholder='未知留空；已知零请填0')
            actor=st.text_input('核对人',value=(controls or {}).get('actor',''),max_chars=60)
            source=st.text_area('独立参考来源与期间',value=(controls or {}).get('source',''),placeholder='例如：2026年9月总账试算平衡表，导出时间、科目范围及凭证位置',max_chars=1000)
            if st.form_submit_button('保存核对依据',type='primary'):
                try:
                    store.save_controls(context,month,values,actor,source)
                    st.rerun()
                except WorkspaceError as error:
                    st.error(str(error))
        with st.expander('分类缺失与预算覆盖提示'):
            st.dataframe(frame(rec['missing_dimensions']),hide_index=True,width='stretch')
            st.caption('缺失分类保留在未归属，不会丢金额。预算是否可比请结合预算页；预算缺失不妨碍确认实际账务。')
        json_download('下载本月对账结果',rec,f'{engine.entity_id}_{month}_对账','reconcile_download')
    with tab2:
        closes=store.closes(context,month)
        active=next((row for row in reversed(closes) if not row['released_at']),None)
        if active:
            compared=compare_snapshot(active['snapshot'],engine,month)
            if compared['changed']:
                st.error('本月数据与确认时不一致，请复核变更明细。原确认快照仍保留，需要解除后重新确认。')
                st.dataframe(frame([{'对象':row['object'],'业务编号':row['id'],'变更':row['kind'],'变化字段':'、'.join(row['fields'])} for row in compared['rows']]),hide_index=True,width='stretch')
                json_download('下载确认后变更明细',compared,f'{month}_确认后变更','close_changes')
            else:
                st.success(f"本月已由 {active['actor']} 确认 · 修订 {active['revision']} · {active['created_at']}。当前实际与快照一致。")
            st.caption('确认说明：'+active['note'])
            json_download('下载原确认快照',active,f'{month}_确认快照','close_snapshot')
            with st.expander('解除本月确认'):
                with st.form('close_release_'+active['id']):
                    actor=st.text_input('解除确认人',max_chars=60)
                    reason=st.text_area('解除原因',max_chars=2000)
                    if st.form_submit_button('保留历史并解除确认'):
                        try:
                            store.release_month(context,active['id'],actor,reason)
                            st.rerun()
                        except WorkspaceError as error:
                            st.error(str(error))
        else:
            if rec['can_confirm']:
                st.success('内部勾稽与独立参考核对通过，可由人员确认本月。')
            else:
                st.warning('尚不能确认：'+'；'.join(rec['blockers']))
            st.caption('确认保存当时的明细和金额；不会冻结来源数据库。以后只新增月份或预算，不会使旧月份自动失效。')
            with st.form('close_confirm_'+tag):
                actor=st.text_input('月份确认人',max_chars=60)
                note=st.text_area('月份确认说明',max_chars=2000)
                agreed=st.checkbox('我已核对独立依据并确认本月实际；这是本程序的管理确认，不代表法定审计或数据库关账')
                if st.form_submit_button('保存本月确认快照',type='primary',disabled=not rec['can_confirm']):
                    try:
                        if not agreed:
                            raise WorkspaceError('请先勾选月份确认声明')
                        store.confirm_month(context,engine,month,actor,note)
                        st.rerun()
                    except WorkspaceError as error:
                        st.error(str(error))
        if closes:
            st.dataframe(frame([{key:row[key] for key in ('revision','actor','note','created_at','released_at','release_actor','release_reason')} for row in closes]),hide_index=True,width='stretch')
    with tab3:
        _issues_ui(engine,store,context,month,filters,version,group_by,tag)


def _issues_ui(engine,store,context,month,filters,version,group_by,tag):
    context_tag=content_digest(context)[:16]
    mode=st.selectbox('异常历史比较基期',['mom','yoy'],format_func=lambda v:'环比' if v=='mom' else '同比',key='issue_mode_'+tag)
    settings=store.settings(context) or DEFAULTS
    with st.expander('异常阈值设置'):
        with st.form('issue_settings_'+context_tag):
            c=st.columns(3)
            amount=c[0].number_input('最低影响金额（元）',0.0,1e12,float(settings['amount']),100.0)
            rate=c[1].number_input('最低变化率（%）',0.0,1000.0,float(Decimal(str(settings['rate']))*100),1.0)
            points=c[2].number_input('毛利率最低下降（百分点）',0.0,100.0,float(Decimal(str(settings['margin_points']))*100),0.5)
            actor=st.text_input('阈值设置人',max_chars=60)
            if st.form_submit_button('保存异常阈值'):
                try:
                    store.save_settings(context,{'amount':str(amount),'rate':str(Decimal(str(rate))/100),'margin_points':str(Decimal(str(points))/100)},actor)
                    st.rerun()
                except WorkspaceError as error:
                    st.error(str(error))
    st.caption('金额与变化率须同时触发；毛利率用“百分点下降＋毛利影响金额”。基期为零时不强算增长率。首次扫描或刷新事实不会改写人工原因和处理状态。')
    actor=st.text_input('本次扫描记录人',max_chars=60,key='issue_scan_actor_'+context_tag)
    if st.button('扫描本月当前范围异常',type='primary',key='issue_scan'):
        try:
            result=detect_issues(engine,month,filters,version,group_by,mode,settings)
            store.scan_issues(context,month,result['candidates'],actor,result['scan_key'])
            st.session_state['issue_scan_gaps_'+tag]=result['coverage_gaps']
            st.success(f"扫描完成，当前范围触发 {len(result['candidates'])} 项；以往人工跟进保留。")
        except WorkspaceError as error:
            st.error(str(error))
    for gap in st.session_state.get('issue_scan_gaps_'+tag,[]):
        st.caption('未覆盖检查：'+gap)
    all_months=st.checkbox('同时查看其他月份未结束事项',key='issue_all_months_'+context_tag)
    rows=store.issues(context,None if all_months else month)
    if all_months:
        rows=[r for r in rows if r['month']==month or r['status'] not in ('resolved','ignored')]
    if rows:
        st.dataframe(frame([{'月份':r['month'],'异常':r['facts']['title'],'当前仍触发':r['facts']['currently_detected'],'状态':STATUSES[r['status']],'影响金额（元）':r['facts']['impact_amount'],'负责人':r['notes'].get('owner',''),'截止日':r['notes'].get('due_date',''),'最近更新':r['updated_at']} for r in rows]),hide_index=True,width='stretch')
    else:
        st.info('还没有保存的异常事项。设置阈值并扫描后，系统会记录触发项；没有触发项时仍需查看未覆盖检查。')
    if rows:
        export=[{'月份':r['month'],'系统事实':r['facts']['title'],'处理状态':STATUSES[r['status']],'当前触发':r['facts']['currently_detected'],
                 '销售筛选':json.dumps(r['facts']['scope']['filters'],ensure_ascii=False),'分组对象':json.dumps(r['facts'].get('group_values'),ensure_ascii=False),
                 '影响金额（元）':r['facts']['impact_amount'],**r['notes']} for r in rows]
        export_frame=pd.DataFrame(export).rename(columns={'owner':'负责人','cause':'人工原因','evidence':'核实依据','action':'后续行动','due_date':'截止日','resolution':'处理结果','review_month':'复盘月份','review_result':'复盘结论','cause_status':'原因核实状态'})
        export_artifact('下载完整跟进表（CSV）',csv_bytes(export_frame),file_name=f'{engine.entity_id}_{month}_异常跟进.csv',mime='text/csv',key='issues_csv',on_click='ignore')
        lookup={r['id']:r for r in rows}
        selected=st.selectbox('选择需要跟进的事项',list(lookup),format_func=lambda v:lookup[v]['month']+' · '+lookup[v]['facts']['title']+' · '+str(lookup[v]['facts'].get('group_values') or '当前范围'),key='issue_selected_'+context_tag)
        row=lookup[selected]
        facts,notes=row['facts'],row['notes']
        selection=Filters.from_dict(facts['scope']['filters'])
        scope='公司全部销售' if selection.is_company else '；'.join(engine.dimension_labels.get(field,field)+'：'+ '、'.join(engine.dimension_text(field,value) for value in values) for field,values in selection.items if values)
        groups=' / '.join(engine.dimension_labels.get(field,field)+'：'+engine.dimension_text(field,value) for field,value in (facts.get('group_values') or {}).items())
        st.caption('记录范围：'+scope+('；分组：'+groups if groups else '')+'；历史基期：'+str(facts['base_month'])[:7]+'。系统识别金额变化，原因需要人工核实。')
        numeric=percent_text if facts['rule']=='margin_decline' else money_text
        st.dataframe(frame([{'本期值':numeric(facts['actual']),'比较值':numeric(facts['reference']),'影响金额（元）':money_text(facts['impact_amount']),'变化比例／百分点':percent_text(facts['change_rate'])}]),hide_index=True,width='stretch')
        if facts.get('source_fingerprint')!=engine.metadata.get('source_fingerprint'):
            st.info('该事实保存于另一数据快照。需要时按原筛选和基期重新扫描；处理记录会保留。')
        review_filters=Filters.from_dict(facts['scope']['filters'])
        try:
            metric=engine.summary(month,filters=review_filters)
            st.caption('复盘参考 · 当前顶部月份 '+month+' · 原事项销售范围：净收入 '+money_text(metric['net_revenue'])+' 元；毛利 '+money_text(metric['gross_margin'])+' 元。公司费用不随销售范围分摊。')
        except ValueError:
            st.warning('原事项筛选对象已失效，当前复盘参考不可用，请核对来源映射。')
        with st.form('issue_edit_'+selected+'_'+str(row['revision'])):
            status=st.selectbox('处理状态',list(STATUSES),index=list(STATUSES).index(row['status']),format_func=STATUSES.get)
            owner=st.text_input('负责人',value=notes.get('owner',''),max_chars=60)
            cause_status=st.selectbox('原因核实状态',['pending','confirmed'],index=1 if notes.get('cause_status')=='confirmed' else 0,format_func=lambda v:'待核实' if v=='pending' else '已核实（需依据）')
            cause=st.text_area('人工原因说明',value=notes.get('cause',''),max_chars=4000)
            evidence=st.text_area('核实依据（凭证、合同、记录位置）',value=notes.get('evidence',''),max_chars=4000)
            action=st.text_area('后续行动',value=notes.get('action',''),max_chars=4000)
            due=st.text_input('截止日（YYYY-MM-DD）',value=notes.get('due_date',''))
            resolution=st.text_area('处理结果／忽略理由',value=notes.get('resolution',''),max_chars=4000)
            review_month=st.text_input('复盘月份（YYYY-MM）',value=notes.get('review_month',''))
            review_result=st.text_area('复盘结论',value=notes.get('review_result',''),max_chars=4000)
            editor=st.text_input('本次记录人',max_chars=60)
            if st.form_submit_button('保存跟进记录',type='primary'):
                try:
                    store.update_issue(context,selected,dict(owner=owner,cause_status=cause_status,cause=cause,evidence=evidence,action=action,due_date=due,resolution=resolution,review_month=review_month,review_result=review_result),status,editor,row['revision'])
                    st.rerun()
                except WorkspaceError as error:
                    st.error(str(error))
        json_download('下载异常事实与人工记录',rows,f'{engine.entity_id}_{month}_异常跟进','issues_download')
    with st.expander('查看本机财务操作记录'):
        audit=store.audit(context)
        st.dataframe(frame([{k:r[k] for k in ('at','object_type','action','actor','note')} for r in audit]),hide_index=True,width='stretch')
        json_download('下载完整操作记录',audit,'财务操作记录','finance_audit_download')
