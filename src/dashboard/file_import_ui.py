"""Preview, map and explicitly apply uploaded business files."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.uploads import import_artifact
from dashboard.profiles import file_identity
from etl.file_import import ROLE_LABELS, FIELDS, OPTIONAL, build_profile, save_profile, saved_profiles, stage_uploads, suggest_mapping, table_references, financial_file_hint
from etl.file_tables import FILE_TYPES, read_table
from etl.sources import CONTRACT, load_facts
from etl.dimensions import recommend
from dashboard.column_catalog_ui import apply_catalog, file_catalog_inputs
from etl.column_catalog import ADAPTER, build_catalog

MISSING='（未提供）'
UNMAPPED='__unmapped__'
EMPTY='__confirmed_empty__'
ROLE_NAMES={
 'sales':('sales','销售','销售明细','销售流水','订单明细'),
 'refunds':('refunds','returns','退款','退款明细','退货'),
 'expenses':('expenses','费用','费用明细','公司费用'),
 'sales_budget':('sales_budget','budget_sales','销售预算'),
 'expense_budget':('expense_budget','budget_expenses','费用预算'),
}


@st.cache_data(show_spinner=False,max_entries=32)
def _references(serialized):
    return table_references(json.loads(serialized))


@st.cache_data(show_spinner=False,max_entries=48)
def _preview(path, sheet_name, header_row, modified):
    return read_table(path,sheet_name=sheet_name,header_row=header_row,limit=20)


@st.cache_data(show_spinner=False,max_entries=32)
def _financial_hint(path,sheet_name,header_row,modified):
    return financial_file_hint(path,sheet_name=sheet_name,header_row=header_row)


def _suggest_table(role, references):
    for item in references:
        label=item['sheet_name'] if item['sheet_name'] is not None else Path(item['name']).stem
        if label.casefold() in ROLE_NAMES[role]:
            return item['id']
    return references[0]['id'] if role=='sales' and len(references)==1 else None


def _validation_message(error):
    reason=str(error)
    messages={
        'standard_refund_unknown_sale':'退款引用了未导入的销售明细。请同时提供原销售，核对销售明细编号。',
        'standard_refund_before_sale':'有退款日期早于原销售确认日期，请核对日期字段。',
        'standard_cumulative_refund_exceeds_sale':'累计退款金额或退货数量超过原销售，请核对是否重复导入或重复映射。',
        'standard_reversal_mismatch':'成本冲回与原销售成本、可回库数量不一致，请核对历史成本。',
        'actual_beyond_declared_cutoff':'实际记录晚于所填截止月，请核对完整实际期间；不要直接把未核对月份标为完整。',
        'invalid_standard_budget_month':'预算月份须对应每月1日，可使用YYYY-MM或YYYY-MM-01。',
    }
    if reason in messages: return messages[reason]
    if reason.startswith('actual_beyond_declared_cutoff:'):
        return messages['actual_beyond_declared_cutoff']
    if reason.startswith('duplicate_standard_key:'):
        role=reason.split(':',1)[1]
        if role=='sales':
            return '销售明细的编号重复。同一订单只有一行时，订单编号须唯一；同一订单有多条明细时，请打开“同一订单包含多条明细（高级）”，另外选择每行唯一的销售明细编号。不会合并或重复计入收入。'
        return ROLE_LABELS.get(role,role)+'出现重复业务键。请核对唯一编号或预算维度，不能重复计入金额。'
    if reason.startswith('invalid_date:'):
        field=reason.split(':',1)[1]
        return '无法识别“'+FIELDS.get(field,(field,()))[0]+'”。支持2026-10-21、2026/10/21、20261021及2026-10-21 9：20或09:20:30；请检查空值、无效日期和时间。预算月份也支持YYYY-MM。'
    if reason.startswith(('missing_standard_field:','invalid_amount:','invalid_integer:','empty_standard_field:')):
        field=reason.split(':',1)[1].split('.')[-1]
        return '请核对“'+FIELDS.get(field,(field,()))[0]+'”的映射、空值与精度。金额默认严格校验；Stata浮点金额可在该表中明确启用四舍五入。'
    if isinstance(error,ValueError) and len(reason)<300 and not reason.startswith('source_quality_failed'):
        return reason
    return '文件验证未通过。请检查文件是否损坏/加密、表头、日期、金额、唯一编号及字段映射；Excel公式须先计算并保存。'


def render_file_importer(on_apply):
    active=st.session_state.get('_business_profile')
    if active and not st.session_state.get('_business_edit'):
        st.sidebar.caption('业务文件接入：'+active.get('display_name',active['entity_id']))
        if active.get('tables',{}).get('sales',{}).get('quantity_basis')=='one_per_row':
            st.sidebar.caption('数量口径：未选择数量列，每条销售明细默认按1计数。')
        if st.sidebar.button('更换文件 / 修改映射',key='business_edit_open',width='stretch'):
            st.session_state['_business_edit']=True
            st.rerun()
        return deepcopy(active)

    st.title('导入业务数据')
    st.write('选择文件 → 选择表头行（默认第1行）→ 勾选分类并改名 → 确认导入。')
    st.caption('支持Excel（xlsx/xls/xlsm）、Stata（dta）、CSV、TSV及记录列表JSON。无需先编写JSON配置。')
    saved=saved_profiles()
    if saved:
        with st.expander('继续使用已保存的文件接入'):
            index=st.selectbox('选择接入',range(len(saved)),format_func=lambda i:saved[i]['entity_id']+' · '+saved[i].get('display_name',saved[i]['profile_id']),key='business_saved')
            if st.button('使用此接入',key='business_saved_apply'):
                try:
                    candidate=saved[index]
                    file_identity(candidate)
                    on_apply()
                    st.session_state['_business_profile']=candidate
                    st.session_state['_business_edit']=False
                    st.rerun()
                except (OSError,ValueError):
                    st.error('该接入的业务文件已丢失或配置无效，请重新选择原业务文件。')
    if active and st.button('取消导入修改，返回已应用数据',key='business_cancel'):
        st.session_state['_business_edit']=False
        st.rerun()

    uploaded=import_artifact('选择业务文件（可多选）',type=list(FILE_TYPES),key='business_files',max_upload_size=100,accept_multiple_files=True)
    restored=(active or {}).get('import_files',[])
    if not uploaded and not restored:
        st.info('Excel可包含多个工作表；也可同时选择销售、退款、费用等多个dta或CSV文件。文件选择后会先预览，不立即替换已应用数据。')
        return None
    try:
        staged=stage_uploads(uploaded) if uploaded else restored
        references=_references(json.dumps(staged,ensure_ascii=False,sort_keys=True))
    except Exception as error:
        st.error(_validation_message(error))
        return None
    by_id={item['id']:item for item in references}
    signature=hashlib.sha256(json.dumps(staged,sort_keys=True).encode()).hexdigest()[:12]
    st.success(f'已读取{len(staged)}个文件，发现{len(references)}张业务表。请核对各表用途。')
    st.caption('第一行通常是字段名；有标题或说明行的Excel可调整表头行。文件仅保存在本机个人数据目录，不写入企业数据库。')
    columns=st.columns(2)
    entity=columns[0].text_input('企业 / 分析主体',value=active['entity_id'] if active else '自定义企业',key='business_entity')
    name=columns[1].text_input('接入名称',value=active.get('display_name','业务文件接入') if active else '业务文件接入',key='business_name',help='相同企业和接入名称复用分类布局；不同企业请分别命名。')
    specs=file_catalog_inputs(staged,active)
    if specs is None:return None
    hinted=None;hint={}
    for spec in specs:
        ref=spec['reference']
        try:candidate_hint=_financial_hint(ref['path'],ref.get('sheet_name'),spec['header_row'],Path(ref['path']).stat().st_mtime_ns)
        except (ValueError,OSError) as error:
            st.error(_validation_message(error));return None
        if candidate_hint.get('detected'):
            hinted=spec;hint=candidate_hint;break
    if st.session_state.get('_business_recommended_signature')!=signature:
        st.session_state['_business_recommended_signature']=signature
        if not active:
            st.session_state['business_financial_mode']=bool(hint.get('detected'))
            st.session_state['business_start']=hint.get('start_month','')
            st.session_state['business_end']=hint.get('end_month','')
            st.session_state['business_partial_period']=True
    if hint.get('detected'):
        st.success('已识别订单编号、销售日期和金额，建议继续财务分析设置。编号和日期沿用推荐，未提供数量时默认1；请核对后确认。')
    financial_defaults={} if 'business_financial_mode' in st.session_state else {'value':bool(active and active.get('adapter')!=ADAPTER) or bool(hint.get('detected'))}
    financial=st.toggle('同时设置财务分析（可选）',**financial_defaults,key='business_financial_mode',help='识别到订单、日期及金额时默认推荐财务分析；可关闭，仅按分类统计记录。')
    if not financial:
        confirmed=st.checkbox('已核对表头行、分类勾选及显示名称，确认导入。',key='business_'+signature+'_catalog_confirmed')
        if st.button('确认分类并导入',type='primary',disabled=not confirmed,width='stretch',key='business_apply'):
            try:
                candidate=build_catalog(entity,name,specs)
                candidate['import_files']=staged
                with st.spinner('正在校验全部记录与表头…'):apply_catalog(candidate,on_apply)
            except (ValueError,OSError) as error:st.error(str(error))
        st.caption('分类名称可以随后在“分类与映射”中修改。普通分类导入不要求订单编号、金额等财务字段，也不自动计算财务指标。')
        return None
    st.markdown('### 可选：财务计算设置')
    partial_defaults={} if 'business_partial_period' in st.session_state else {'value':bool((active or {}).get('coverage',{}).get('incomplete_months')) if active else True}
    partial_period=st.checkbox('这是单日或部分期间数据（不作为完整月实际）',**partial_defaults,
        key='business_partial_period',help='单日、小时或未完结月份使用此选项。保留已知交易核对与分组，不据此生成整月完成率、同比环比或预测。')
    columns=st.columns(2)
    start_defaults={} if 'business_start' in st.session_state else {'value':(active or {}).get('coverage',{}).get('complete_start',hint.get('start_month',''))[:7]}
    end_defaults={} if 'business_end' in st.session_state else {'value':(active or {}).get('coverage',{}).get('complete_end',hint.get('end_month',''))[:7]}
    start=columns[0].text_input('数据开始月份' if partial_period else '完整实际开始月份',**start_defaults,placeholder='例如2026-01',key='business_start')
    end=columns[1].text_input('数据截止月份' if partial_period else '完整实际截止月份',**end_defaults,placeholder='例如2026-09',key='business_end')
    if hint.get('first_date'):
        st.caption(f"按全表推荐：{hint['row_count']}条记录，销售日期{hint['first_date']}至{hint['last_date']}；这只表示文件日期，不证明期间完整。")
    if partial_period:
        st.info('这些月份将明确标为不完整。可查看已导入交易、分类和已知金额；完整月指标、完成率和预测保持不可用。')
    st.caption('完整月须按已核对的覆盖情况确认，不能只根据文件最大日期推断。金额为人民币元、不含税，销售金额为折后、退款前金额。未选择数量列时每行默认1，选择后使用实际数量。')
    selections={}
    sales_preview=None
    for role,label in ROLE_LABELS.items():
        prefix='business_'+signature+'_'+role
        default=_suggest_table(role,references)
        if role=='sales' and hinted:
            default=hinted['reference']['id']
        if role=='refunds' and default is None and partial_period and hint.get('refunds_zero'):
            default=EMPTY
        options=[UNMAPPED,*([EMPTY] if role!='sales' else []),*by_id]
        with st.expander(label+' · 工作表与字段',expanded=role=='sales' or default is not None):
            chosen=st.selectbox(label+'来源',options,index=options.index(default or UNMAPPED),format_func=lambda value:'请选择销售明细' if value==UNMAPPED and role=='sales' else '未提供（相关指标暂不可确认）' if value==UNMAPPED else '确认无此类记录（按0计算）' if value==EMPTY else by_id[value]['label'],key=prefix+'_table')
            if role=='refunds' and hint.get('refunds_zero') and partial_period:
                st.caption('已识别销售文件的“'+hint['refund_column']+'”整列为0，建议本次文件范围无退款，仍需确认。其他日期或另表退款须另行提供；不能据此认定整月无退款。')
            if chosen==UNMAPPED:
                selections[role]=None
                if role=='refunds': st.caption('没有退款时请选择“确认无此类记录”；未提供退款来源时，净收入和净成本保持未确认。')
                continue
            if chosen==EMPTY:
                selections[role]={'empty':True}
                continue
            reference=by_id[chosen]
            table_key=hashlib.sha256(chosen.encode()).hexdigest()[:10]
            selected_spec=next((spec for spec in specs if spec['reference']['id']==chosen),{})
            header=selected_spec.get('header_row',1)
            if Path(reference['path']).suffix.lower() in ('.xlsx','.xls','.xlsm','.csv','.tsv'):
                header=int(st.number_input(label+'表头所在行',min_value=1,max_value=100,value=header,key=prefix+'_'+table_key+'_header'))
            try:
                table=_preview(reference['path'],reference.get('sheet_name'),header,Path(reference['path']).stat().st_mtime_ns)
                if not table.columns:
                    st.warning('该表没有表头或记录。没有此类业务时请选择“确认无此类记录”。')
                    return None
            except Exception as error:
                st.error(_validation_message(error))
                return None
            st.dataframe(pd.DataFrame(table.rows,columns=table.columns),hide_index=True,width='stretch')
            st.caption('以上最多预览20行，确认时会校验全部记录。文本编码保留前导零；Stata保留原始编码，变量标签仅用于辅助识别。')
            suggested=suggest_mapping(role,table.columns,table.comments)
            previous=(active or {}).get('tables',{}).get(role,{})
            same_table=(reference['path'] in previous.get('files',[]) and
                        reference.get('sheet_name')==previous.get('sheet_name') and
                        header==int(previous.get('header_row',1)))
            previous_mapping=previous.get('mapping',{}) if same_table else {}
            suggested.update({field:column for field,column in previous_mapping.items() if column in table.columns})
            separate_lines=False
            if role=='sales':
                if 'order_id' not in suggested and 'sale_line_id' in suggested:
                    suggested['order_id']=suggested['sale_line_id']
                separate_lines=st.toggle('同一订单包含多条明细（高级）',
                    value=bool(previous_mapping.get('sale_line_id') and previous_mapping.get('order_id') and
                               previous_mapping['sale_line_id']!=previous_mapping['order_id']),
                    key=prefix+'_'+table_key+'_'+str(header)+'_separate_lines',
                    help='通常只需选择一次订单编号。只有同一订单分成多行时，才另外指定每行唯一的明细编号；退款仍须引用原明细。')
            mapping={}
            cols=st.columns(2)
            fields=[field for field in CONTRACT[role][1:] if not (role=='sales' and field=='sale_line_id' and not separate_lines)]
            for index,field in enumerate(fields):
                choices=[UNMAPPED,*table.columns]
                field_name=FIELDS[field][0]
                if field=='sale_line_id':
                    field_name='独立销售明细编号（每行唯一）' if role=='sales' else '原订单编号（唯一明细编号）'
                elif role=='sales' and field=='order_id' and separate_lines:
                    field_name='订单编号（同一订单可重复）'
                label_field=field_name+(' *' if field not in OPTIONAL[role] else '')
                if role=='sales' and field=='quantity':
                    label_field='成交数量（未提供时默认1）'
                value=cols[index%2].selectbox(label_field,choices,index=choices.index(suggested.get(field,UNMAPPED)),format_func=lambda value,field=field,role=role:('默认1（每条销售明细）' if role=='sales' and field=='quantity' else MISSING) if value==UNMAPPED else value+(' · '+table.comments[value] if table.comments.get(value) and table.comments[value]!=value else ''),key=prefix+'_'+table_key+'_'+str(header)+'_'+field)
                if value!=UNMAPPED: mapping[field]=value
            if role=='sales':
                if not separate_lines and mapping.get('order_id'):
                    mapping['sale_line_id']=mapping['order_id']
                if separate_lines and not mapping.get('sale_line_id'):
                    st.warning('多明细模式须另外选择每行唯一的销售明细编号。')
                st.caption('支付时间、付款时间可自动推荐为销售确认日期；支持带时分秒及中文冒号，分析时取该时间的日期，不改写原文件。选择支付时间表示你确认以支付日作为本文件的销售确认日。')
                if 'quantity' not in mapping:
                    st.info('未选择成交数量列：每条销售明细按1计数。它是默认计数，不能据此推断一笔订单实际包含多少件商品。')
                st.caption('“订单金额”仅为字段推荐，须确认单位为元、是否含税及是否已经扣券；优惠券列不会被再次自动扣减。')
            st.caption('带*字段必须对应实际列；未提供商品、渠道、地区时列入“未归属”，缺历史成本时不补0。只含金额的预算请通过预算工作台模板导入，不虚构销量和单价。')
            rounded=st.checkbox('确认将超出精度的金额四舍五入（金额至分、单价和单位成本至4位）',value=False,key=prefix+'_'+table_key+'_round',help='默认严格保留原值。仅在已确认Stata浮点存储等精度问题时启用；原业务文件保持原样。')
            selections[role]={'reference':reference,'header_row':header,'mapping':mapping,'round_money':rounded,
                              'separate_line_id':separate_lines}
            if role=='sales': sales_preview=table
    dimensions=[]
    if sales_preview:
        source=selections['sales']['reference']['id']
        dimensions=[item for spec in specs if spec['reference']['id']==source for item in spec['columns'] if item['enabled']]
        st.caption('已启用的销售分类沿用上方勾选和名称。预算具有这些分类时，可在“分类与映射”中另行确认预算粒度。')
    confirmed=st.checkbox('已确认：文件属于同一分析主体，数据期间及完整性、人民币不含税口径、字段与分类含义、数量默认方式，以及退款/费用提供情况均与实际一致。',key='business_'+signature+'_confirmed')
    if st.button('验证并应用业务数据',type='primary',disabled=not confirmed,width='stretch',key='business_apply'):
        try:
            candidate=build_profile(entity,name,start,end,selections,dimension_fields=dimensions,comments=sales_preview.comments if sales_preview else {},selected_headers=True,partial_period=partial_period)
            candidate['import_files']=staged
            candidate['header_catalog']={item['table_id']:{'header_row':item['header_row'],'columns':item['columns']} for item in specs}
            with st.spinner('正在读取全部记录，核对金额、日期、关联及唯一编号…'):
                facts=load_facts(candidate)
                if facts.tables['sales'].empty:
                    raise ValueError('销售明细没有有效记录，请检查表头行与数据范围。')
            on_apply()
            st.session_state['_business_profile']=candidate
            st.session_state['_business_edit']=False
            st.session_state['_business_prepared']={'identity':file_identity(candidate),'facts':facts}
            try:
                save_profile(candidate)
            except OSError:
                st.session_state['dimension_notice']='本次导入已生效，但接入配置无法保存；请检查个人数据目录权限。'
            st.rerun()
        except Exception as error:
            st.error(_validation_message(error))
    st.caption('接入配置和文件保存在本机，后续可继续使用。个人数据备份不包含企业业务文件，换电脑时请另外保留原始数据。')
    return None
