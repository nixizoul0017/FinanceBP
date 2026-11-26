"""Monthly file review, validation, and explicit activation."""
import streamlit as st

from analysis import FinancialEngine
from analysis.forecast_store import content_digest
from dashboard.profiles import file_identity
from dashboard.uploads import import_artifact
from etl.dimensions import profile_key
from etl.file_import import FIELDS, OPTIONAL, ROLE_LABELS, save_profile, stage_uploads, suggest_mapping, table_references
from etl.file_tables import FILE_TYPES, read_table
from etl.month_update import inspect_input, months_between, prepare_update
from etl.sources import CONTRACT
from finance.reconciliation import compare_snapshot
from finance.store import WorkspaceStore


def start_update(profile):
    st.session_state['_monthly_base'] = profile
    st.session_state.pop('_monthly_preview', None)


def update_inputs(profile, months):
    updates = {}
    roles = st.multiselect('本次提交的业务表', [r for r in ROLE_LABELS if r in profile['tables']],
                           default=['sales'], format_func=ROLE_LABELS.get)
    files = import_artifact('选择更新文件（可多选）', type=list(FILE_TYPES), key='monthly_files',
                            max_upload_size=100, accept_multiple_files=True)
    refs = table_references(stage_uploads(files)) if files else []
    used = set()
    ready = bool(roles)
    for role in roles:
        st.markdown('#### '+ROLE_LABELS[role])
        tag = 'monthly_'+role
        ids = {r['id']:r for r in refs}
        choice = st.selectbox('数据来源', [None, *ids, 'empty'], format_func=lambda k: ids[k]['label'] if k in ids else
                              ('确认所选期间无记录' if k == 'empty' else '请选择工作表或无记录'),
                              key=tag+'_ref')
        if not choice:
            ready = False
            continue
        if choice != 'empty' and choice in used:
            raise ValueError('同一工作表只能分配给一种业务。')
        used.add(choice)
        ref = None
        info = {'months':set()}
        setting = dict(profile['tables'][role])
        update = {}
        if choice != 'empty':
            item = ids[choice]
            tag += '_'+content_digest(item)[:12]
            header = st.number_input('表头行', 1, 100, setting.get('header_row',1), key=tag+'_header')
            ref = {k:item[k] for k in ('path','name','sheet_name','sha256')}
            ref['header_row'] = header
            table = read_table(ref['path'], sheet_name=ref['sheet_name'], header_row=header, limit=20)
            mapping = setting.get('mapping')
            if not mapping:
                suggested = suggest_mapping(role, table.columns)
                mapping = {}
                for field in CONTRACT[role][1:]:
                    choices = [None, *table.columns]
                    selected = st.selectbox(FIELDS[field][0], choices, index=choices.index(suggested.get(field)),
                                            key=tag+'_'+field)
                    if selected:
                        mapping[field] = selected
                    elif field not in OPTIONAL[role]:
                        ready = False
                if not ready:
                    continue
                if len(set(mapping.values())) != len(mapping):
                    raise ValueError('原始列不能重复对应业务字段。')
                update.update(mapping=mapping, defaults=OPTIONAL[role])
                setting.update(update)
            needed = set(mapping.values())
            for dimension in profile.get('dimensions', []):
                for binding in dimension['bindings'].values():
                    if binding['table'] == role:
                        for key in ('field','name_field','source_key'):
                            field=binding.get(key)
                            if field:
                                needed.add(field if binding.get('raw_fields') else mapping.get(field,field))
            aliases = {}
            known=setting.get('header_aliases',{})
            for old in sorted(needed - set(table.columns)):
                if known.get(old) in table.columns:
                    aliases[old]=known[old]
                    continue
                selected = st.selectbox('原列「'+old+'」现在对应', [None,*table.columns], key=tag+'_alias_'+old)
                if selected:
                    aliases[old] = selected
                else:
                    ready = False
            if not ready:
                continue
            if len({aliases.get(k,k) for k in needed}) != len(needed):
                raise ValueError('两个原始表头不能同时对应同一新列。')
            ref['aliases'] = aliases
            info = inspect_input(role, setting, ref, months)
            st.write(f"文件日期 {info['start']} 至 {info['end']}，共 {info['rows']} 行，文件内金额 {info['amount']} 元。")
        missing = {}
        for month in months:
            if month not in info['months']:
                missing[month] = st.selectbox(month+' 缺少记录', [None,'keep','empty'],
                    format_func=lambda v:{None:'请选择','keep':'保留旧数据','empty':'确认该月无记录'}[v], key=tag+month)
                ready &= missing[month] is not None
        updates[role] = {**update,'ref':ref,'missing':missing}
    return updates if ready else None


def render_update(on_apply, resolve):
    original = st.session_state['_monthly_base']
    profile = resolve(original)
    st.title('更新业务文件')
    st.caption(profile['entity_id']+' · '+profile['display_name'])
    if st.button('取消更新，返回原接入'):
        st.session_state.pop('_monthly_base')
        st.session_state.pop('_monthly_preview',None)
        st.rerun()
    mode = st.radio('更新方式',['部分期间文件核对','当月独立文件','年内累计文件'],horizontal=True)
    start = st.text_input('起始月份',profile['coverage']['complete_end'][:7])
    end = st.text_input('截止月份',start) if mode == '年内累计文件' else start
    try:
        months = months_between(start,end)
        if start[:4] != end[:4]:
            raise ValueError('年内累计文件请选择同一年度。')
        updates = update_inputs(profile, months)
        if mode == '部分期间文件核对':
            st.info('仅核对文件内交易，已有月份保持原状。整月数据备齐后可选择当月或累计更新。')
            return
        if not updates:
            return
        signature = content_digest((file_identity(profile),mode,start,end,updates))
        if st.button('校验全部数据并预览差异'):
            st.session_state.pop('_monthly_preview',None)
            with st.spinner('正在核对历史销售、跨月退款及唯一编号…'):
                result = prepare_update(profile, updates, start, end)
                result['identity'] = file_identity(result['profile'])
                st.session_state['_monthly_preview'] = signature,result
        preview = st.session_state.get('_monthly_preview')
        if not preview or preview[0] != signature:
            return
        result = preview[1]
        st.dataframe([{**r,'业务表':ROLE_LABELS[r['业务表']]} for r in result['summary']],hide_index=True)
        if not result['changed']:
            st.success('数据无变化')
            return
        with st.expander('查看变动明细'):
            from finance.store import dumps
            st.json(dumps(result['details']))
        engine = FinancialEngine(result['facts'])
        closes = WorkspaceStore().closes(profile_key(profile))
        affected = [r['month'] for r in closes if not r['released_at'] and compare_snapshot(r['snapshot'],engine,r['month'])['changed']]
        st.write('应用后需复核的已确认月份：'+('、'.join(affected) or '无'))
        confirmed = st.checkbox('已核对差异，提交的数据覆盖所选业务表的整月记录',key='monthly_confirm_'+signature)
        if st.button('应用此次月度更新', disabled=not confirmed):
            if result['identity'] != file_identity(result['profile']):
                raise ValueError('预览后文件已变化，请重新校验。')
            save_profile(result['profile'],expected=original)
            on_apply()
            st.session_state['_business_profile'] = result['profile']
            st.session_state['_business_prepared'] = {'facts':result['facts'],'identity':result['identity']}
            st.session_state['_business_edit'] = False
            st.session_state.pop('_monthly_preview',None)
            st.session_state.pop('_monthly_base',None)
            st.rerun()
    except (ValueError, ArithmeticError, OSError, KeyError) as error:
        st.error('更新未应用。'+str(error))

