from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import html
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.metrics import month_date, month_range, shift_month
from analysis.service import analysis_pack
from analysis.variance import variance_pack
from analysis.pvm import FACTOR_LABELS
from analysis.forecast import METHODS, METHOD_LABELS, forecast_base
from analysis.scenario import Assumptions, forecast_pack
from analysis.forecast_store import content_digest, load_forecast, saved_forecasts, save_forecast
from analysis.metrics import filter_dimensions
from dashboard.profiles import PRESETS, file_identity, selected_profile
from dashboard.theme import PALETTES, load_preference, palette, save_preference, theme_css
from dashboard.navigation import render_navigation, navigate, group_for
from dashboard.view_model import budget_rows, chart_frame, csv_bytes, detail_tables, forecast_groups, money_text, monthly_trend, percent_text, safe_export_name
from etl.common import db_engine, encode
from etl.sources import load_facts, inspect_profile
from etl.dimensions import profile_key
from dashboard.dimension_store import DimensionStore, mapping_signature
from dashboard.dimension_ui import initialize as initialize_filters, render_controls, applied_scope
from dashboard.result_cache import cached_result
from dashboard.exports import export_artifact
from dashboard.uploads import import_artifact
from desktop.events import stage as desktop_stage
from dashboard.dimension_setup import render_setup
from reporting.service import build_report, markdown_report, SCENARIOS as REPORT_SCENARIOS
from reporting.tables import ADJUSTMENTS
from reporting.excel import excel_bytes
from finance.store import WorkspaceStore, WorkspaceError
from finance.budgets import overlay as budget_overlay
from finance.issues import workflow_snapshot
from analysis.historical import historical_variance
from dashboard.finance_ui import budget_workbench, finance_workbench, historical_panel

st.set_page_config(page_title="经营分析工作台", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
if st.session_state.get("ui_theme") not in PALETTES:
    st.session_state["ui_theme"] = load_preference()
THEME = palette(st.session_state["ui_theme"])
st.markdown(theme_css(THEME), unsafe_allow_html=True)
loading_placeholder = st.empty()


def begin_loading():
    loading_placeholder.markdown('<div class="fb-loading" data-active="true" role="status" aria-live="polite"><div class="loading-card"><span class="loading-ring"></span><strong>加载中</strong><span>正在准备分析页面，请稍候…</span></div></div>', unsafe_allow_html=True)

try:
    if any((st.session_state.pop('_filter_loading',False),st.session_state.pop('_source_loading',False))):
        begin_loading()
    if st.session_state.pop("clear_dimension_password_next",False):
        st.session_state.pop("dimension_setup_password",None)

    LABELS = {"net_revenue": "净收入", "net_cost": "净成本", "gross_margin": "毛利", "gross_margin_rate": "毛利率", "expenses": "公司费用", "operating_profit": "经营利润", "sales_quantity": "成交件数", "returned_quantity": "退货件数", "confirmed_orders": "确认订单", "confirmed_lines": "确认明细", "average_selling_price": "成交平均售价", "average_order_value": "成交客单价", "sales_revenue": "退款前销售", "refund_amount": "退款金额", "sales_cost": "成交成本", "cogs_reversal_amount": "成本转回", "net_quantity": "净销量", "operating_margin_rate": "经营利润率", "expense_rate": "费用率"}
    DIM_LABELS = {"product_id": "商品", "channel_id": "渠道", "region_id": "区域"}
    CHANNEL_NAMES = {"C01": "自营商城", "C02": "平台商城", "C03": "直播渠道"}
    REGION_NAMES = {"R01": "华东", "R02": "华南", "R03": "华北", "R04": "西部"}
    FIELD_NAMES = {**LABELS, "entity_id": "企业", "sale_line_id": "销售明细ID", "order_id": "订单ID", "revenue_date": "销售确认日", "refund_id": "退款ID", "refund_date": "退款确认日", "expense_id": "费用ID", "expense_date": "费用确认日", "product_id": "商品编码", "channel_id": "渠道编码", "region_id": "区域编码", "quantity": "成交数量", "sales_amount_before_refund": "退款前收入（元）", "cogs_amount": "成交成本（元）", "returned_quantity": "退货数量", "recoverable_quantity": "可回库数量", "cost_reversal_amount": "成本转回（元）", "expense_category": "费用类别", "department": "部门", "channel_scope": "渠道归属", "region_scope": "区域归属", "amount": "费用金额（元）", "month": "月份", "period_is_complete": "期间完整", "scope": "费用/数据范围", "actual": "实际", "budget": "预算", "variance": "差额", "variance_rate": "差异率", "completion_rate": "完成率", "direction": "方向", "has_budget": "有预算记录", "has_actual_record": "有实际记录", "metric": "指标"}
    ISSUES = {"historic_cost_missing": "部分成交缺少历史成本，成本、毛利和利润暂不可计算。", "refund_source_missing": "尚未提供退款来源，净收入和净成本暂不可确认。", "expense_source_missing": "尚未提供费用来源，公司费用和经营利润暂不可确认。"}
    FIELD_NAMES.update(source_available="来源已提供", actual_is_complete="实际期间完整", budget_version="预算版本", comparison_status="预算覆盖状态", is_complete="期间完整", rate_unavailable_reason="比率不可用原因")
    for money_field in ("net_revenue", "net_cost", "gross_margin", "sales_revenue", "refund_amount", "sales_cost", "cogs_reversal_amount", "expenses", "operating_profit", "average_selling_price", "average_order_value", "actual", "budget", "variance"):
        FIELD_NAMES[money_field] = FIELD_NAMES[money_field] + "（元）"
    VALUE_NAMES = {"company_expenses": "公司费用", "company_sales": "全部销售", "sales_dimensions": "当前销售筛选", "favorable": "有利", "unfavorable": "不利", "on_budget": "持平", "unknown": "未知", "complete": "完整", "missing_budget": "缺预算", "no_budget": "无预算", "actual_unknown": "实际未知", "budget_missing": "缺少预算", "nonpositive_budget": "预算为零或负数", "base_unknown": "基期未知", "nonpositive_base": "基期为零或负数", "current_unknown": "当前值未知", "marketing": "营销费", "platform_commission": "平台佣金", "logistics": "物流费", "payroll": "人工费用", "administration": "管理费用"}
    FIELD_NAMES.update(factor="因素编码", factor_label="差异因素", negative_contribution_share="不利贡献占比", product_state="商品比较状态", q_actual="实际销量", q_budget="预算销量", revenue_actual="实际退款前收入（元）", revenue_budget="预算退款前收入（元）", cost_actual="实际成交成本（元）", cost_budget="预算成交成本（元）", refund_actual="实际退款（元）", refund_budget="预算退款（元）", reversal_actual="实际成本转回（元）", reversal_budget="预算成本转回（元）", price_actual="实际均价（元/件）", price_budget="预算均价（元/件）", unit_cost_actual="实际单位成本（元/件）", unit_cost_budget="预算单位成本（元/件）")
    BRIDGE_REASONS = {"actual_incomplete": "月份实际数据尚不完整", "budget_incomplete": "当前期间或实际维度缺完整销售预算", "quantity_unit_unconfirmed": "未确认统一的件数口径", "refund_source_missing": "未提供退款来源", "historic_cost_missing": "实际缺历史成本", "budget_cost_missing": "预算缺单位成本", "expense_source_missing": "未提供公司费用来源", "expense_budget_incomplete": "公司费用预算不完整"}
    BRIDGE_REASONS.update(budget_drivers_missing='所选金额预算没有销量、均价等驱动数据，不能做量价结构拆解；金额比较仍可使用',product_grain_unavailable='所选预算没有商品粒度，不能生成商品量价结构拆解')
    SCENARIO_LABELS = {"base":"基础", "optimistic":"乐观", "cautious":"谨慎", "custom":"自定义"}
    FIELD_NAMES.update(kind="数据性质", is_available="期间可计算", method="预测方法", n="配对验证月份数", mae="MAE（元）", wape="WAPE", bias="平均偏差（元）", horizon="预测步长（月）", origin="历史截止月", target_month="验证月份", scenario="情景", cutoff_month="实际截止月", forecast_run_id="预测版本")
    FIELD_NAMES.update(net_unit_price="预测均价（元/件）",unit_cost="预测单位成本（元/件）",channel_scope="费用渠道归属",region_scope="费用区域归属")
    VALUE_NAMES.update(METHOD_LABELS, **SCENARIO_LABELS, actual="实际", forecast="预测")

    def remember_theme():
        st.session_state["ui_theme_saved"] = save_preference(st.session_state["ui_theme"])


    def clear_snapshot():
        st.session_state["_source_loading"] = True
        st.session_state.pop("ui_workspace", None)
        for key in ("engine", "snapshot_identity", "loaded_at", "pack_cache", "driver_cache", "month", "budget_version", "product_filter", "channel_filter", "region_filter", "trend_start", "db_host", "db_port", "db_user", "db_name", "db_password", "clear_password_next", "source_error"):
            st.session_state.pop(key, None)
        for state_key in list(st.session_state):
            if state_key.startswith(("forecast_","report_","dimension_","_dimension_","dim_value_","finance_","budget_","issue_","control_","history_","_history_","_filter_")):
                st.session_state.pop(state_key,None)


    def clear_results():
        for key in ("engine", "snapshot_identity", "loaded_at", "pack_cache", "driver_cache", "forecast_cache", "forecast_last_saved", "source_error", "_filter_results"):
            st.session_state.pop(key, None)
        st.session_state.pop("report_generated",None)


    def load_snapshot(profile, identity, password=None):
        desktop_stage('数据读取与校验')
        begin_loading()
        connection = None
        try:
            if profile["source"]["kind"] == "mysql":
                connection = db_engine(profile["source"]["connection"], password="" if password is None else password)
            facts = load_facts(profile, connection)
            fresh_engine=FinancialEngine(facts)
            clear_results()
            st.session_state["engine"] = fresh_engine
            try:
                st.session_state['dimension_preview']=inspect_profile(profile,connection)
            except Exception:
                st.session_state.pop('dimension_preview',None)
            st.session_state["snapshot_identity"] = identity
            st.session_state["loaded_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
            st.session_state["pack_cache"] = {}
        except Exception as error:
            # 不展示可能含密码、原始业务行或连接细节的异常堆栈。
            message = "数据校验未通过，请核对字段映射、日期、金额、唯一键及覆盖范围。" if isinstance(error, ValueError) else "无法读取数据，请核对文件或MySQL连接地址、账号与权限。"
            st.session_state["source_error"] = message
        finally:
            if connection is not None:
                connection.dispose()


    def resolve_profile(profile):
        try:
            resolved=DimensionStore().confirmed_profile(profile)
        except (ValueError,KeyError,TypeError):
            st.session_state['dimension_notice']='本机分类映射已失效，请重新确认；原文件仍保留。'
            resolved=profile
        override=st.session_state.get('mapping_overrides',{}).get(profile_key(profile),{})
        return override['profile'] if override.get('base_signature')==mapping_signature(profile) else resolved


    def scan_dimensions(profile,password=None):
        connection=None
        try:
            if profile['source']['kind']=='mysql':
                connection=db_engine(profile['source']['connection'],password=password or '')
            return inspect_profile(profile,connection)
        finally:
            if connection is not None:
                connection.dispose()


    def confirm_dimensions(candidate,password=None):
        begin_loading()
        connection=None
        try:
            if candidate['source']['kind']=='mysql':
                connection=db_engine(candidate['source']['connection'],password=password or '')
            # Validate the complete snapshot before replacing a working mapping.
            fresh=FinancialEngine(load_facts(candidate,connection))
        finally:
            if connection is not None:
                connection.dispose()
        store=DimensionStore()
        try:
            candidate=store.confirm(candidate,candidate['dimensions'],base_profile=base_profile)
        except ValueError:
            st.session_state['dimension_notice']=store.warning or '当次已生效，但无法保存映射。'
        st.session_state.setdefault('mapping_overrides',{})[profile_key(candidate)]={'profile':candidate,'base_signature':mapping_signature(base_profile)}
        clear_results()
        st.session_state['engine']=fresh
        st.session_state['snapshot_identity']=file_identity(candidate)
        st.session_state['loaded_at']=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
        for state_key in list(st.session_state):
            if state_key.startswith(('dim_value_','dimension_slot_')) or state_key in ('product_filter','channel_filter','region_filter','_dimension_scope'):
                st.session_state.pop(state_key,None)


    def human_table(frame):
        # 展示仅格式化，CSV使用原始精确金额；所有原始文本交给安全控件渲染。
        result = frame.copy()
        result.attrs = {}
        for column in result:
            if column in DIM_LABELS and 'engine' in globals():
                result[column]=result[column].map(lambda value:engine.dimension_text(column,value) if value is not None and pd.notna(value) else '未归属')
            if column.endswith("_rate") or column in ("variance_rate", "completion_rate", "negative_contribution_share", "wape"):
                result[column] = result[column].map(percent_text)
                continue
            if column == "metric":
                result[column] = result[column].map(lambda value: LABELS.get(value, value))
            elif column in ("scope", "direction", "comparison_status", "rate_unavailable_reason", "expense_category", "method", "kind", "scenario"):
                result[column] = result[column].map(lambda value: VALUE_NAMES.get(value, value))
            result[column] = result[column].map(lambda value: "—" if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)) else format(value, "f") if isinstance(value, Decimal) else str(value) if isinstance(value, (list, dict, tuple)) else value)
        return result.rename(columns=FIELD_NAMES)


    def download(frame, kind, label, company=False, start=None):
        scope = Filters() if company else filters
        name_kind = kind
        if frame.attrs.get("source_available") is False:
            name_kind += "_来源未提供"
        elif frame.attrs.get("period_is_complete") is False:
            name_kind += "_期间不完整"
        filename = safe_export_name(engine.entity_id, start or month, name_kind, scope, end=month if start else None, version=version if "预算" in kind else None, fingerprint=engine.metadata.get("source_fingerprint"))
        export_artifact(label, data=csv_bytes(frame), file_name=filename, mime="text/csv", key="download_"+kind, on_click="ignore", width="stretch")


    def chart_layout(fig, unit_label="元", height=330):
        fig.update_layout(height=height, margin=dict(l=20, r=20, t=20, b=20), paper_bgcolor=THEME.surface, plot_bgcolor=THEME.surface, font=dict(family="Arial, Microsoft YaHei, sans-serif", color=THEME.muted), colorway=[THEME.primary, THEME.secondary, THEME.tertiary], hoverlabel=dict(bgcolor=THEME.surface,font_color=THEME.text,bordercolor=THEME.border), legend=dict(orientation="h", y=1.13, x=0), yaxis_title=unit_label, xaxis_title=None, hovermode="x unified")
        fig.update_yaxes(gridcolor=THEME.border, zerolinecolor=THEME.muted)
        return fig


    def plot_trend(frame, fields=("net_revenue", "gross_margin")):
        values = chart_frame(frame)
        divisor = 10000 if unit == "万元" else 1
        figure = go.Figure()
        month_labels = [str(value)[:7] for value in values["month"]]
        for field, color in zip(fields, (THEME.primary, THEME.secondary, THEME.tertiary)):
            figure.add_trace(go.Scatter(x=month_labels, y=[None if pd.isna(value) else value/divisor for value in values[field]], name=LABELS[field], mode="lines+markers", connectgaps=False, line=dict(color=color, width=3), marker=dict(size=5), hovertemplate="%{x}<br>%{y:,.2f}"+unit+"<extra>%{fullData.name}</extra>"))
        if len(fields) == 1:
            rgb = ",".join(str(int(THEME.primary[i:i+2], 16)) for i in (1, 3, 5))
            figure.update_traces(fill="tozeroy", fillcolor=f"rgba({rgb},0.07)")
            figure.update_layout(showlegend=False)
        figure.update_xaxes(type="category", categoryorder="array", categoryarray=month_labels)
        st.plotly_chart(chart_layout(figure, unit), width="stretch", config={"displaylogo": False})


    def metric_cards(summary, keys, changes=None):
        columns = st.columns(len(keys))
        for column, key in zip(columns, keys):
            value = percent_text(summary[key]) if key.endswith("_rate") else str(summary[key]) if key in ("confirmed_orders", "sales_quantity") and summary[key] is not None else money_text(summary[key], unit)
            delta = None
            if changes and changes.get(key, {}).get("change_rate") is not None:
                delta = "环比 " + percent_text(changes[key]["change_rate"])
            column.metric(LABELS[key], value, delta=delta, delta_color="off")


    def render_bridge(title, model, kind, company_scope=False):
        st.markdown("#### "+title)
        if model["status"] != "complete":
            st.info("暂不能拆解："+BRIDGE_REASONS.get(model["reason"], "数据条件尚未满足")+"。已知金额仍可在上方预算表核对。")
            return
        components = model["components"]
        short_labels = {"volume": "销量", "mix": "结构", "price": "均价", "new_product": "新成交", "no_sales_product": "未成交", "product_volume": "商品销量", "unit_cost": "单位成本", "refund": "退款", "cost_reversal": "成本转回", "expense": "费用"}
        labels = ["预算"]+[short_labels[row["factor"]] for row in components]+["实际"]
        divisor = 10000 if unit == "万元" else 1
        amounts = [float(model["budget"])/divisor]+[float(row["amount"])/divisor for row in components]+[float(model["actual"])/divisor]
        figure = go.Figure(go.Waterfall(x=labels, y=amounts, measure=["absolute"]+["relative"]*len(components)+["total"],
            connector={"line": {"color": THEME.muted}}, increasing={"marker": {"color": THEME.success}}, decreasing={"marker": {"color": THEME.danger}}, totals={"marker": {"color": THEME.primary}},
            text=[money_text(model["budget"], unit)]+[money_text(row["amount"], unit) for row in components]+[money_text(model["actual"], unit)], textposition="none", hovertemplate="%{x}<br>%{text}"+unit+"<extra></extra>", name=title))
        running, positions = model["budget"], []
        for row in components:
            running += row["amount"]
            positions.append(float(running)/divisor)
        # Scatter圆点提供明确可点击的选择事件；瀑布柱继续承担金额桥展示。
        figure.add_trace(go.Scatter(x=labels[1:-1], y=positions, customdata=[[row["factor"]] for row in components], mode="markers", marker={"size": 11, "color": THEME.primary, "line": {"color": THEME.surface, "width": 1}}, showlegend=False, hovertemplate="点击查看 %{x} 明细<extra></extra>"))
        figure = chart_layout(figure, unit, 460)
        figure.update_layout(showlegend=False, clickmode="event+select", margin={"l": 30, "r": 30, "t": 40, "b": 100})
        figure.update_xaxes(tickangle=-35)
        identity = hashlib.sha256(repr((key, company_scope)).encode()).hexdigest()[:12]
        event = st.plotly_chart(figure, width="stretch", key=f"bridge_chart_{kind}_{identity}", on_select="rerun", selection_mode="points", config={"displaylogo": False})
        st.caption(f"预算 {money_text(model['budget'], unit)} → 实际 {money_text(model['actual'], unit)}；差额 {money_text(model['variance'], unit)} {unit}。")
        st.caption("点击图中圆点查看因素明细，也可使用下方选择框。图表与卡片采用"+unit+"，明细与下载采用元；模型原值精确勾稽。")
        summary_rows = [{"因素": row["factor_label"], "贡献金额（元）": money_text(row["amount"])} for row in components]
        shown_total = sum((Decimal(row["贡献金额（元）"].replace(",", "")) for row in summary_rows), Decimal(0))
        display_difference = Decimal(money_text(model["variance"]).replace(",", ""))
        if display_difference != shown_total:
            summary_rows.append({"因素": "显示舍入尾差（非经营因素）", "贡献金额（元）": money_text(display_difference-shown_total)})
        st.dataframe(pd.DataFrame(summary_rows), hide_index=True, width="stretch")
        choices = ["all"]+[row["factor"] for row in components]
        select_key = f"factor_{kind}_{identity}"
        points = event.get("selection", {}).get("points", [])
        token = repr(points)
        token_key = f"selection_{kind}_{identity}"
        if points and token != st.session_state.get(token_key):
            value = points[-1].get("customdata")
            target = value[0] if isinstance(value, (list, tuple)) and value else value
            if target in choices:
                st.session_state[select_key] = target
        st.session_state[token_key] = token
        factor = st.selectbox("查看因素明细 · "+title, choices, format_func=lambda value: "全部因素" if value == "all" else FACTOR_LABELS[value], key=select_key)
        rows = [row for row in model["details"] if factor == "all" or row["factor"] == factor]
        detail = pd.DataFrame(rows, dtype=object)
        if not detail.empty:
            display = detail.copy()
            display["amount"] = display["amount"].map(money_text)
            st.dataframe(human_table(display).rename(columns={"费用金额（元）": "贡献金额（元）"}), hide_index=True, width="stretch")
        st.caption("显示金额四舍五入至分；商品贡献与公司费用行分开，单项为0仍保留。原值及表示尾差见JSON。")
        factor_name = "全部因素" if factor == "all" else FACTOR_LABELS[factor]
        download(detail, kind+"_"+factor_name+"预算差异明细", "下载"+title+"明细（精确元）", company=company_scope)


    with st.sidebar:
        st.markdown('<div class="fb-brand"><div class="fb-brand-symbol"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M4 20v-5m5 5v-8m5 8V9m5 11V5M3 10l6-5 5 2 7-6"/></svg></div><div class="fb-brand-name">FinanceBP<small>财务经营分析工作台</small></div></div>', unsafe_allow_html=True)
        with st.popover("外观配色 · " + THEME.name, icon=":material/palette:", width="stretch"):
            st.radio("选择界面颜色", list(PALETTES), format_func=lambda key: PALETTES[key].name,
                     index=list(PALETTES).index(st.session_state["ui_theme"]), key="ui_theme", on_change=remember_theme,
                     captions=["稳重专业", "清爽理性", "稳重精致"])
            if st.session_state.get("ui_theme_saved") is False:
                st.caption("已在本次使用中生效；项目目录不可写，暂无法记住选择。")
            else:
                st.caption("切换立即生效，并记住这台电脑的选择。")
        workspace = st.empty()
        workspace.markdown(st.session_state.get("ui_workspace", '<div class="workspace"><span class="workspace-icon">星</span><div>分析工作空间<small>正在准备数据</small></div></div>'), unsafe_allow_html=True)
        page = render_navigation()
        st.divider()
        source = st.selectbox("数据来源", [*PRESETS, "自定义配置"], key="source", on_change=clear_snapshot)
        uploaded = import_artifact("选择数据源配置", type="json", key="profile_upload") if source == "自定义配置" else None

    try:
        profile = selected_profile(source, uploaded)
    except Exception:
        clear_results()
        st.error("配置无法读取。请使用阶段5的连接与字段映射模板，密码不要写入配置。")
        st.stop()

    if profile is None:
        clear_results()
        st.info("请在左侧选择已准备好的JSON配置。连接、映射与口径确认后，页面会预览标准数据。")
        st.stop()

    # Stable UI identity for an evolving list of monthly files; CLI v1 is unchanged.
    if profile['source']['kind']=='files' and not profile.get('profile_id'):
        config_name=PRESETS.get(source,getattr(uploaded,'name','custom-profile'))
        profile['profile_id']='files-'+hashlib.sha256(str(config_name).encode()).hexdigest()[:24]
    base_profile=deepcopy(profile)
    is_mysql = profile["source"]["kind"] == "mysql"
    if is_mysql:
        if st.session_state.pop("clear_password_next", False):
            st.session_state.pop("db_password", None)
        settings = profile["source"]["connection"]
        if st.session_state.get('_mysql_source')!=profile_key(profile):
            st.session_state['_mysql_source']=profile_key(profile)
            for name,value in {'db_host':settings.get('host','127.0.0.1'),'db_port':int(settings.get('port',3306)),'db_name':settings['database'],'db_user':settings['user'],'db_password':''}.items():
                st.session_state[name]=value
        with st.sidebar.form("mysql_connection"):
            st.markdown("**数据库连接**")
            host = st.text_input("主机地址", value=settings.get("host", "127.0.0.1"), key="db_host")
            port = st.number_input("端口", min_value=1, max_value=65535, value=int(settings.get("port",3306)), key="db_port")
            database_name = st.text_input("数据库", value=settings["database"], key="db_name")
            user = st.text_input("用户名", value=settings["user"], key="db_user")
            password = st.text_input("密码（仅本次读取）", type="password", key="db_password")
            submitted = st.form_submit_button("读取 / 刷新数据库", width="stretch")
            scan_submitted = st.form_submit_button("识别分类（不加载）", width="stretch")
        active_profile = deepcopy(profile)
        active_profile["source"]["connection"].update(host=host, port=int(port), database=database_name, user=user)
        base_profile=deepcopy(active_profile)
        active_profile = resolve_profile(active_profile)
        identity = file_identity(active_profile)
        if scan_submitted:
            try:
                st.session_state['dimension_preview']=scan_dimensions(active_profile,password)
                st.session_state['dimension_draft_profile']=deepcopy(active_profile)
                st.session_state['dimension_setup_open']=True
            except Exception:
                st.session_state['source_error']='无法识别分类，请核对连接、密码与读取权限。'
            st.session_state['clear_password_next']=True
            st.rerun()
        if submitted:
            with st.spinner("正在读取并核对数据…"):
                load_snapshot(active_profile, identity, password)
            # 下次运行重建密码控件，不把凭据留在结果或缓存中。
            st.session_state["clear_password_next"] = True
            st.session_state['_filter_loading'] = True
            st.rerun()
        if "engine" in st.session_state and st.session_state.get("snapshot_identity") != identity:
            clear_results()
        st.sidebar.caption("只读取来源表，不建库、不导入或改写业务数据。")
    else:
        profile = resolve_profile(profile)
        active_profile = profile
        try:
            identity = file_identity(profile)
        except Exception:
            clear_results()
            st.error("找不到来源文件，请确认配置中的路径及完整模拟文件。")
            st.stop()
        refresh = st.sidebar.button("刷新文件数据", width="stretch", key="refresh_files")
        if refresh or st.session_state.get("snapshot_identity") != identity:
            with st.spinner("正在核对数据并准备看板…"):
                load_snapshot(profile, identity)

    if st.sidebar.button('分类识别与映射',key='open_dimension_setup',width='stretch',icon=':material/tune:'):
        st.session_state['dimension_setup_open']=True
        st.session_state['dimension_draft_profile']=deepcopy(active_profile)
        st.session_state.pop('dimension_edit_specs',None)
    render_setup(active_profile,scan_dimensions,confirm_dimensions)

    if st.session_state.get("source_error"):
        st.error(st.session_state["source_error"])
        st.stop()
    if "engine" not in st.session_state:
        st.info("在左侧填写连接信息，然后点击“读取 / 刷新数据库”。")
        st.stop()

    engine = st.session_state["engine"]
    finance_store=WorkspaceStore()
    finance_context=profile_key(active_profile)
    try:
        local_budgets=finance_store.budgets(finance_context,published_only=True)
        overlay_key=(engine.metadata.get('source_fingerprint'),finance_context,content_digest(local_budgets))
        cached_overlay=st.session_state.get('finance_overlay')
        if not cached_overlay or cached_overlay[0]!=overlay_key:
            cached_overlay=(overlay_key,budget_overlay(engine,local_budgets))
            st.session_state['finance_overlay']=cached_overlay
        engine=cached_overlay[1]
    except WorkspaceError as error:
        st.warning(str(error)+'；本机预算未加载，来源预算和实际仍可查看。')
    DIM_LABELS = engine.dimension_labels
    FIELD_NAMES.update({key:label for key,label in DIM_LABELS.items()})
    coverage = engine.metadata["coverage"]
    versions = sorted(set(engine.tables["sales_budget"]["budget_version"]) | set(engine.tables["expense_budget"]["budget_version"]))
    last_actual = month_date(coverage["complete_end"][:7])
    month_candidates = [month_date(coverage["complete_start"]), last_actual]
    for name, field in (("sales_budget", "month"), ("expense_budget", "month")):
        if not engine.tables[name].empty:
            month_candidates.extend(engine.tables[name][field])
    if coverage.get("boundary_event_end"):
        month_candidates.append(month_date(coverage["boundary_event_end"][:7]))
    months = [value.strftime("%Y-%m") for value in month_range(min(month_candidates), max(month_candidates))]
    default_month = last_actual.strftime("%Y-%m")
    heading = html.escape(profile.get("display_name", "星辰优选" if engine.entity_id.startswith("XCYX") else engine.entity_id))
    st.session_state["ui_workspace"] = f'<div class="workspace"><span class="workspace-icon">星</span><div>{heading}<small>{html.escape(engine.entity_id)} · {html.escape(source)}</small></div></div>'
    workspace.markdown(st.session_state["ui_workspace"], unsafe_allow_html=True)
    st.markdown(f'<div class="topbar"><span>工作台 <b>/</b> {group_for(page)}</span><span>{heading}</span></div>', unsafe_allow_html=True)
    title_column, action_column = st.columns([4, 1], vertical_alignment="center")
    with title_column:
        hero_note={'预算工作台':'编制、校验、发布预算，保留每一次调整依据。','对账与跟进':'核对财务数据，确认完整月份，跟进经营异常。'}.get(page,'从经营结果出发，定位差异，支持下一步决策。')
        st.markdown(f'<div class="hero-title">{page}</div><div class="hero-note">{hero_note}</div>', unsafe_allow_html=True)
    with action_column:
        if page != "点评与月报":
            st.button("查看月报", icon=":material/summarize:", type="primary", width="stretch", key="open_report", on_click=navigate, args=("点评与月报",))
    filter_bar = st.container(key="filter_bar")
    initialize_filters(engine,active_profile,months,versions or ['无预算数据'],default_month,
                       '万元' if source=='完整模拟数据' else '元',page)
    with filter_bar:
        render_controls(engine,active_profile,page,months,versions or ['无预算数据'],default_month,
                        '万元' if source=='完整模拟数据' else '元')
    if st.session_state.get('_filter_invalid'):
        st.info('请先在上方核对并应用筛选，再查看分析和下载。')
        st.stop()
    applied,filters,scope_text=applied_scope(engine)
    month,version,unit=applied['month'],applied['version'],applied['unit']
    actual_version=version if versions else 'B2026_V1'
    group_by=tuple(applied['layout']['group_by'])
    st.markdown(f'<div class="scope-note"><span><i></i> 数据完整截至 {coverage["complete_end"]}</span><span>已应用：{month} · {html.escape(engine.metadata.get("budget_labels",{}).get(version,version))} · {unit} · {html.escape(scope_text)} · 人民币不含税 · 销量：件</span></div>', unsafe_allow_html=True)
    st.sidebar.caption(f"企业：{engine.entity_id}\n\n口径：自营商品销售 v1\n\n读取时间：{st.session_state['loaded_at']}")
    st.sidebar.caption("演示来源均为模拟数据。自定义来源以配置和首次接入核对为准。")

    key = (engine.entity_id, engine.metadata["rule_version"], engine.metadata.get("source_fingerprint"), month, filters, actual_version)
    cache = st.session_state.setdefault("pack_cache", {})
    if key not in cache:
        with st.spinner("正在计算当前范围…"):
            if len(cache) >= 12:
                cache.clear()
            desktop_stage('首屏分析计算')
            cache[key] = analysis_pack(engine, month, filters, actual_version)
    pack = cache[key]
    selected, company = pack["selected_scope"], pack["company_scope"]
    if not selected["is_complete"]:
        st.warning("该月份没有完整实际数据，常规指标和完成率暂不显示。已知交易仅供明细核对。")
        if selected["actual_status"] == "partial":
            with st.expander("查看已观察到的事件金额（仅核对，非完整实际）"):
                observed = selected["observed_metrics"]
                st.dataframe(pd.DataFrame([{"指标": LABELS[field], "已观察金额（"+unit+"）": money_text(observed[field], unit)} for field in ("sales_revenue", "refund_amount", "net_revenue", "gross_margin")]), hide_index=True, width="stretch")
    elif not selected["has_activity"]:
        st.info("当前完整月份在此筛选范围没有交易，收入与毛利为0。")
    for issue in set(selected["data_issues"] + company["data_issues"]):
        st.warning(ISSUES.get(issue, "当前来源不足以支持部分指标。"))

    if page == "经营总览":
        st.markdown('<style>.st-key-primary_metrics{--fb-money-unit:"' + unit + '";}</style>', unsafe_allow_html=True)
        with st.container(key="primary_metrics"):
            cards = st.columns(4)
            for column, summary, field in ((cards[0], selected, "net_revenue"), (cards[1], selected, "gross_margin"), (cards[2], company, "operating_profit"), (cards[3], selected, "gross_margin_rate")):
                with column:
                    value = percent_text(summary[field]) if field.endswith("_rate") else money_text(summary[field], unit)
                    st.metric(LABELS[field], value)
                    if field == "operating_profit":
                        st.caption("公司全口径 · 费用未分摊")
                    elif field == "gross_margin_rate":
                        revenue_budget = pack["selected_budget"]["totals"]["net_revenue"]["budget"]
                        margin_budget = pack["selected_budget"]["totals"]["gross_margin"]["budget"]
                        if summary[field] is not None and revenue_budget is not None and revenue_budget > 0 and margin_budget is not None:
                            points = (summary[field] - margin_budget / revenue_budget) * 100
                            direction = "negative" if points < 0 else "positive"
                            st.markdown(f'<div class="kpi-change {direction}">较预算 {points:+.2f} 个百分点</div>', unsafe_allow_html=True)
                        else:
                            st.caption("预算毛利率差异未知")
                    else:
                        completion = pack["selected_budget"]["totals"][field]["completion_rate"]
                        st.caption("预算完成 " + percent_text(completion))
        left, right = st.columns([1.7, 1])
        with left, st.container(key="overview_trend"):
            st.markdown("#### 净收入走势")
            st.caption("实际 · " + unit + " · 当前销售范围")
            trend_start=max(month_date(coverage['complete_start']),month_date(month[:4]+'-01'))
            plot_trend(cached_result(engine,'monthly_trend',(trend_start,month,filters),lambda:monthly_trend(engine,trend_start,month,filters)), ('net_revenue',))
        with right, st.container(key="overview_budget"):
            st.markdown("#### 预算执行")
            budget = pack["selected_budget"]["totals"]
            rows = [{"指标": LABELS[field], "实际（"+unit+"）": money_text(budget[field]["actual"], unit), "预算（"+unit+"）": money_text(budget[field]["budget"], unit), "差额（"+unit+"）": money_text(budget[field]["variance"], unit)} for field in ("net_revenue", "gross_margin")]
            for label, comparison in (("净收入", budget["net_revenue"]), ("毛利", budget["gross_margin"]), ("经营利润 · 公司", pack["company_budget"]["operating_profit"])):
                rate = comparison["completion_rate"]
                st.markdown(f'<div class="budget-label"><span>{label}</span><strong>{percent_text(rate)}</strong></div>', unsafe_allow_html=True)
                st.progress(max(0.0, min(1.0, float(rate))) if rate is not None else 0.0)
                st.caption(f"实际 {money_text(comparison['actual'], unit)} / 预算 {money_text(comparison['budget'], unit)} {unit}" if rate is not None else "预算或实际数据不足，完成率未知")
            if pack["selected_budget"]["status"] != "complete":
                st.caption("当前范围缺少完整销售预算，合计预算和完成率保留为空。")
            st.caption(f"确认订单 {selected['confirmed_orders'] if selected['confirmed_orders'] is not None else '—'} 个 · 成交件数 {selected['sales_quantity'] if selected['sales_quantity'] is not None else '—'} 件")
            st.caption("同比收入："+percent_text(pack["selected_trends"]["yoy"]["net_revenue"]["change_rate"]))
        with st.expander("查看实际与预算金额"):
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown("#### 成本与公司经营")
        st.caption("费用与经营利润包含公司全部业务，共同费用未分摊；不随上方商品、渠道或区域筛选变化。")
        metric_cards({**company, "net_cost": selected["net_cost"]}, ("net_cost", "expenses", "operating_margin_rate"))
        st.markdown("#### 本年累计 · 当前范围")
        ytd = pack["selected_ytd"]["current"]
        metric_cards(ytd, ("net_revenue", "gross_margin", "gross_margin_rate"))
        if not ytd["is_complete"]:
            st.caption("本年1月至当前月尚有未完整载入月份，累计数保留为空。")
        with st.expander("当前指标包下载"):
            payload = json.dumps(pack, ensure_ascii=False, indent=2, default=encode, allow_nan=False).encode("utf-8")
            export_artifact("下载当前结果包（JSON）", payload, file_name=safe_export_name(engine.entity_id, month, "指标包", filters, version=version, fingerprint=engine.metadata.get("source_fingerprint")).replace(".csv", ".json"), mime="application/json", key="download_metrics", on_click="ignore")

    elif page == "月度趋势":
        start_options = [value for value in months if value <= month]
        if st.session_state.get("trend_start") not in start_options:
            st.session_state.pop("trend_start", None)
        start = st.selectbox("趋势起始月份", start_options, key="trend_start", index=max(0, len(start_options)-12))
        trend = cached_result(engine,'monthly_trend',(month_date(start),month,filters),lambda:monthly_trend(engine,start,month,filters))
        plot_trend(trend)
        metrics = ["net_revenue", "gross_margin", "net_cost"]
        rows = []
        for field in metrics:
            rows.append({"指标": LABELS[field], "当前值（"+unit+"）": money_text(selected[field], unit), "环比": percent_text(pack["selected_trends"]["mom"][field]["change_rate"]), "同比": percent_text(pack["selected_trends"]["yoy"][field]["change_rate"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("环比比较上一个自然月，同比比较上年同月；缺基期或基期≤0时不展示常规增长率。图中空缺代表数据未知。")
        fields = ["month", "net_revenue", "net_cost", "gross_margin", "gross_margin_rate", "sales_quantity", "confirmed_orders", "is_complete"]
        st.dataframe(human_table(trend[fields]), hide_index=True, width="stretch")
        download(trend[fields], "月度趋势", "下载当前范围月度趋势（精确元）", start=start)
        historical_panel(engine,month,filters,group_by,THEME)

    elif page == "维度分析":
        grouping=group_by
        frame=pd.DataFrame(cached_result(engine,'dimensions',(month,grouping,filters),lambda:engine.dimensions(month,by=grouping,filters=filters))) if grouping else pd.DataFrame()
        if not grouping:
            st.info('请选择至少一个分组维度；分组选择独立于上方筛选范围。')
        elif frame.empty:
            st.info('当前范围没有可分组的销售或退款记录。')
        else:
            order=st.radio('排序依据',['net_revenue','gross_margin'],format_func=lambda name:LABELS[name],horizontal=True,key='dimension_sort')
            frame=frame.sort_values(order,ascending=False,na_position='last')
            plotted=chart_frame(frame.head(20))
            divisor=10000 if unit=='万元' else 1
            figure=go.Figure()
            names=[' / '.join(engine.dimension_text(field,row[field]) for field in grouping) for row in plotted.to_dict('records')]
            for field,color in (('net_revenue',THEME.primary),('gross_margin',THEME.secondary)):
                figure.add_trace(go.Bar(x=names,y=[None if pd.isna(value) else value/divisor for value in plotted[field]],name=LABELS[field],marker_color=color))
            st.plotly_chart(chart_layout(figure,unit),width='stretch',config={'displaylogo':False})
            st.caption(f'共{len(frame)}组，图表最多显示前20组；下方结果与下载保留全部分组。')
            fields=[*grouping,'net_revenue','net_cost','gross_margin','gross_margin_rate','sales_quantity','confirmed_orders']
            st.dataframe(human_table(frame[fields]),hide_index=True,width='stretch')
            st.caption('分组顺序决定列顺序；毛利率按各组收入与毛利重算。各组订单分别去重，跨组订单数不能直接相加。公司费用未分摊。金额单位为元。')
            download(frame[fields],'维度分析','下载当前维度分析（精确元）')

    elif page == "预算比较":
        budget = pack["selected_budget"]
        st.markdown("#### 销售预算 · 当前范围")
        rows = []
        for field in ("net_revenue", "net_cost", "gross_margin"):
            value = budget["totals"][field]
            rows.append({"指标": LABELS[field], "实际（"+unit+"）": money_text(value["actual"], unit), "预算（"+unit+"）": money_text(value["budget"], unit), "差额（"+unit+"）": money_text(value["variance"], unit), "差异率": percent_text(value["variance_rate"]), "完成率": percent_text(value["completion_rate"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if budget["status"] != "complete":
            st.info("当前筛选维度在所选预算中不可比或覆盖不足。实际仍展示，预算、完成率与差异保持不可用，不进行分摊。")
        if budget["cost_status"] == "missing_unit_cost":
            st.warning("预算缺少单位成本，收入预算仍可用，成本与毛利预算暂不可计算。")
        if budget["missing_keys"]:
            with st.expander("查看缺预算的实际维度"):
                st.dataframe(human_table(pd.DataFrame(budget["missing_keys"])), hide_index=True, width="stretch")
        st.markdown("#### 费用与经营利润预算 · 公司全口径")
        company_rows = []
        for label, value in (("公司费用", pack["company_budget"]["expenses"]["total"]), ("公司经营利润", pack["company_budget"]["operating_profit"])):
            company_rows.append({"指标": label, "实际（"+unit+"）": money_text(value["actual"], unit), "预算（"+unit+"）": money_text(value["budget"], unit), "差额（"+unit+"）": money_text(value["variance"], unit), "预算方向": {"favorable": "有利", "unfavorable": "不利", "on_budget": "持平", "unknown": "无法比较"}[value["direction"]]})
        st.dataframe(pd.DataFrame(company_rows), hide_index=True, width="stretch")
        st.caption("费用高于预算表示不利；零预算保留金额差异，完成率为空。方向表示数字偏差，业务原因仍需核实。")
        detail = budget_rows(budget)
        with st.expander("销售预算明细（精确元）"):
            st.dataframe(human_table(detail), hide_index=True, width="stretch")
        download(detail, "销售预算比较", "下载当前范围销售预算比较（精确元）")
        driver_cache = st.session_state.setdefault("driver_cache", {})
        if key not in driver_cache:
            if len(driver_cache) >= 12:
                driver_cache.clear()
            driver_cache[key] = variance_pack(engine, month, filters, actual_version)
        drivers = driver_cache[key]
        st.divider()
        st.markdown("### 预算差异从哪里来")
        if st.session_state.get('variance_dimension') not in DIM_LABELS:
            st.session_state.pop('variance_dimension',None)
        ranking_dimension = st.selectbox("定位差异的维度", list(DIM_LABELS), format_func=lambda name: DIM_LABELS[name], key="variance_dimension")
        ranking = pd.DataFrame(drivers["selected"]["rankings"][ranking_dimension])
        st.dataframe(human_table(ranking), hide_index=True, width="stretch")
        st.caption("按净收入不利差额优先排序；不利贡献占比以所有负向金额绝对值之和为分母，避免正负抵消。缺预算时未知合计与贡献占比保持为空。")
        st.caption("PVM先按共同商品的总销量→商品结构→均价拆解；预算销量为0/本期未成交商品单列。均价含折扣及渠道、区域成交结构，金额贡献不能单独证明业务原因。")
        bridge_tabs = st.tabs(["净收入差异桥", "毛利差异桥", "公司经营利润差异桥"])
        with bridge_tabs[0]:
            render_bridge("净收入差异桥", drivers["selected"]["revenue_bridge"], "净收入")
        with bridge_tabs[1]:
            st.caption("共同商品销量已包含结构变化，不再加入收入桥的结构金额。")
            render_bridge("毛利差异桥", drivers["selected"]["gross_margin_bridge"], "毛利")
        with bridge_tabs[2]:
            st.caption("此桥为公司全部业务，不随上方商品、渠道、区域筛选变化。")
            render_bridge("公司经营利润差异桥", drivers["company_operating_bridge"], "公司利润", True)
            st.dataframe(human_table(pd.DataFrame(drivers["expense_ranking"])), hide_index=True, width="stretch")
        with st.expander("商品输入与平均单价（下载保留原始精度）"):
            inputs = pd.DataFrame(drivers["selected"]["products"])
            shown = inputs.copy()
            for column in shown:
                if column.startswith(("price_", "unit_cost_")):
                    shown[column] = shown[column].map(money_text)
            if "product_state" in shown:
                shown["product_state"] = shown["product_state"].map({"common": "共同成交", "actual_only": "预算无销量、本期成交", "budget_only": "预算有销量、本期未成交", "no_sales": "双方无成交"})
            st.dataframe(human_table(shown), hide_index=True, width="stretch")
            download(inputs, "预算拆解商品输入", "下载商品拆解输入（精确元）")
        export_artifact("下载预算驱动分析包（JSON）", json.dumps(drivers, ensure_ascii=False, indent=2, default=encode, allow_nan=False).encode("utf-8"), file_name=safe_export_name(engine.entity_id, month, "预算驱动分析包", filters, version=version, fingerprint=engine.metadata.get("source_fingerprint")).replace(".csv", ".json"), mime="application/json", key="download_variance_pack", on_click="ignore")

    elif page == "预测与情景":
        if not engine.is_complete(month):
            st.info("已应用月份没有完整实际数据。请在顶部选择完整月份并应用后进行预测。")
            st.stop()
        st.markdown("### 截至时点的滚动预测")
        st.caption("本次模型只使用"+month+"及此前完整实际。全年预测＝年初至截止月实际＋剩余月份预测，预算保留所选原版本。情景参数作用于公司全部业务；商品、渠道、区域筛选用于查看其中一部分，公司费用与利润采用公司全口径。")
        model_columns=st.columns(3)
        method=model_columns[0].selectbox("预测方法",["auto",*METHODS],format_func=lambda value:"自动（按回测WAPE）" if value=="auto" else METHOD_LABELS[value],key="forecast_method")
        window=model_columns[1].selectbox("近期窗口（月）",[3,1,6],key="forecast_window")
        objective=model_columns[2].selectbox("回测选型指标",["net_revenue","gross_margin","operating_profit"],format_func=lambda field:"公司"+LABELS[field],key="forecast_objective")
        base_key=(engine.entity_id,engine.metadata["rule_version"],engine.metadata.get("source_fingerprint"),month,method,window,actual_version,objective)
        forecast_cache=st.session_state.setdefault("forecast_cache",{})
        if base_key not in forecast_cache:
            with st.spinner("正在按历史截止点回测并准备预测，首次计算需稍候…"):
                if len(forecast_cache)>=4:
                    forecast_cache.clear()
                try:
                    forecast_cache[base_key]=forecast_base(engine,month,method,window,actual_version,objective)
                except ValueError:
                    st.info("当前来源或截止月不足以支持预测，请核对完整覆盖、件数口径和预算版本。")
                    st.stop()
        base=forecast_cache[base_key]
        st.info("当前使用："+METHOD_LABELS[base["metadata"]["method"]]+"。回测按公司全口径、相同验证月份比较；收入、毛利和利润的最优方法可能不同。")
        st.markdown("#### 自定义未来假设")
        adjustment_labels={"quantity_change":"销量调整（%）","price_change":"均价调整（%）","unit_cost_change":"单位成本调整（%）","refund_rate_change":"退款强度调整（%）","cost_reversal_change":"成本转回额外调整（%）","marketing_change":"营销费用调整（%）","expense_change":"全部费用额外调整（%）"}
        adjustment_columns=st.columns(3)
        changes={name:Decimal(str(adjustment_columns[index%3].number_input(label,min_value=-100.0,max_value=100.0,value=0.0,step=1.0,key="forecast_"+name)))/100 for index,(name,label) in enumerate(adjustment_labels.items())}
        forecast=cached_result(engine,'forecast_pack',(base_key,filters,tuple(changes.items())),lambda:forecast_pack(base,filters,Assumptions(**changes)))
        scenario_name=st.selectbox("查看情景",list(SCENARIO_LABELS),format_func=lambda value:SCENARIO_LABELS[value],key="forecast_scenario")
        scenario=forecast["scenarios"][scenario_name]
        st.caption("销量按件四舍五入；均价与销量相乘，不自动估计提价后的销量变化。退款与转回随预计收入暴露缩放，再应用单独调整；佣金随收入、物流随件数、营销按单独费用假设变动。")
        if not forecast["metadata"]["selected_scope_known"]:
            st.warning("所选编码在截止月前未被观察到，该销售范围预测保持未知。新商品需另建有依据的业务计划。")
        if any(not row["is_available"] for row in forecast["actual_company_monthly"]):
            st.warning("年初至截止月仍有未完整载入月份，累计实际和全年合计保持未知；未来预测不会补写过去的实际。")
        elif any(row["net_cost"] is None for row in forecast["actual_company_monthly"]) and engine.available["refunds"]:
            st.warning("累计实际包含缺失成本，未来成本估算不能修复过去，全年毛利和利润可能仍未知。")
        if any(not period["available"] for period in base["forecast_periods"]):
            st.warning("部分未来月份缺模型所需历史，不能填0。完整模拟来源支持全部三种方法；小样本可选择近期均值、窗口1学习月度预测，但缺全年实际仍不能得到正常全年合计。")
        if any(row["sales_quantity"]>0 and row["unit_cost"] is None for period in base["forecast_periods"] for row in period["sales"]):
            st.warning("部分预测成交缺单位成本假设，相关成本、毛利与利润保持未知。")
        st.markdown("#### 全年销售预测 · 当前范围")
        metric_cards(scenario["selected_annual"],("net_revenue","gross_margin"))
        st.markdown("#### 全年费用与经营利润 · 公司全口径")
        metric_cards(scenario["company_annual"],("expenses","operating_profit"))
        summary_rows=[]
        for label,ytd,remaining,annual in (("当前范围净收入",scenario["selected_ytd"]["net_revenue"],scenario["selected_remaining"]["net_revenue"],scenario["selected_annual"]["net_revenue"]),("当前范围毛利",scenario["selected_ytd"]["gross_margin"],scenario["selected_remaining"]["gross_margin"],scenario["selected_annual"]["gross_margin"]),("公司经营利润",scenario["company_ytd"]["operating_profit"],scenario["company_remaining"]["operating_profit"],scenario["company_annual"]["operating_profit"])):
            summary_rows.append({"指标":label,"截止累计实际（"+unit+"）":money_text(ytd,unit),"剩余预测（"+unit+"）":money_text(remaining,unit),"全年预测（"+unit+"）":money_text(annual,unit)})
        st.dataframe(pd.DataFrame(summary_rows),hide_index=True,width="stretch")
        annual_budget_rows=[]
        for label,value in (("当前范围净收入",scenario["selected_budget_comparison"]["net_revenue"]),("当前范围毛利",scenario["selected_budget_comparison"]["gross_margin"]),("公司经营利润",scenario["company_budget_comparison"]["operating_profit"])):
            annual_budget_rows.append({"指标":label,"全年预算（"+unit+"）":money_text(value["budget"],unit),"预测减预算（"+unit+"）":money_text(value["variance"],unit),"预计完成率":percent_text(value["completion_rate"])})
        st.dataframe(pd.DataFrame(annual_budget_rows),hide_index=True,width="stretch")
        reference=forecast["budget_reference"]
        if reference["selected"]["net_revenue"] is None:
            st.info("当前范围没有完整全年销售预算，预算合计和完成率保持未知。")
        elif reference["selected"]["gross_margin"] is None:
            st.info("全年预算缺单位成本；收入预算可用，毛利与利润预算保持未知。")
        if reference["company"]["expenses"] is None:
            st.info("公司全年费用预算不完整，不能以部分费用预算计算公司利润预算。")
        st.caption("预算缺月或缺适用维度时，全年预算与完成率为空。回测和模型拟合不读取未来预算或模拟预设。")
        timeline=forecast["actual_selected_monthly"]+scenario["selected_monthly"]
        figure=go.Figure()
        divisor=10000 if unit=="万元" else 1
        for kind,label,color,dash in (("actual","已知实际",THEME.primary,"solid"),("forecast","未来预测",THEME.secondary,"dash")):
            plotted=[row for row in timeline if row["kind"]==kind]
            if kind=="forecast" and plotted and forecast["actual_selected_monthly"]:
                plotted=[forecast["actual_selected_monthly"][-1]]+plotted
            figure.add_trace(go.Scatter(x=[str(row["month"])[:7] for row in plotted],y=[None if row["net_revenue"] is None else float(row["net_revenue"])/divisor for row in plotted],mode="lines+markers",name=label,line={"color":color,"dash":dash},connectgaps=False))
        figure.update_xaxes(type="category",categoryorder="array",categoryarray=[str(row["month"])[:7] for row in timeline])
        st.plotly_chart(chart_layout(figure,unit,390),width="stretch",config={"displaylogo":False})
        timeline_display=pd.DataFrame(timeline,dtype=object)[["month","kind","is_available","sales_quantity","net_revenue","net_cost","gross_margin"]]
        timeline_display["sales_quantity"]=timeline_display["sales_quantity"].map(lambda value:"—" if pd.isna(value) else str(int(value)))
        for field in ("net_revenue","net_cost","gross_margin"):
            timeline_display[field]=timeline_display[field].map(money_text)
        st.dataframe(human_table(timeline_display),hide_index=True,width="stretch")
        st.caption("月度表金额为元，显示至分；实际与预测分别标记。分析包及专用下载保留原始精度。")
        st.markdown("#### 基础／乐观／谨慎／自定义比较")
        scenario_rows=[{"情景":SCENARIO_LABELS[name],"当前范围全年净收入（"+unit+"）":money_text(item["selected_annual"]["net_revenue"],unit),"当前范围全年毛利（"+unit+"）":money_text(item["selected_annual"]["gross_margin"],unit),"公司全年利润（"+unit+"）":money_text(item["company_annual"]["operating_profit"],unit)} for name,item in forecast["scenarios"].items()]
        st.dataframe(pd.DataFrame(scenario_rows),hide_index=True,width="stretch")
        with st.expander("查看情景假设与回测证据"):
            st.dataframe(pd.DataFrame([{"情景":SCENARIO_LABELS[name],**{adjustment_labels[field]:percent_text(value) for field,value in item["assumptions"].items()}} for name,item in forecast["scenarios"].items()]),hide_index=True,width="stretch")
            scores_display=pd.DataFrame(base["backtest"]["scores"])
            for field in ("mae","bias"):
                scores_display[field]=scores_display[field].map(money_text)
            st.dataframe(human_table(scores_display),hide_index=True,width="stretch")
            st.caption(f"{len(base['backtest']['origins'])}个历史截止点，每次预测后续1—3个月；每个模型使用相同验证月份。WAPE＝绝对误差总和÷实际绝对值总和，实际全0时为空。自动选型至少需要6个配对月份，不足时采用近期均值作为未验证的备用方法。")
            errors=[{"origin":row["origin"],"target_month":row["target_month"],"horizon":row["horizon"],"method":row["method"],"指标":LABELS[field],"实际（元）":money_text(row[field]["actual"]),"预测（元）":money_text(row[field]["forecast"]),"误差（元）":money_text(row[field]["error"])} for row in base["backtest"]["details"] for field in ("net_revenue","gross_margin","operating_profit")]
            st.dataframe(human_table(pd.DataFrame(errors)),hide_index=True,width="stretch")
        draft_id="FC9_"+content_digest(forecast)[:24]
        unsupported_forecast=sorted({field for period in scenario['future_periods'] for field in period.get('unavailable_dimensions',[]) if dict(filters.items).get(field)})
        if unsupported_forecast:
            st.warning('当前细分类别的预测不可用：'+ '、'.join(DIM_LABELS[field] for field in unsupported_forecast)+'的历史归属不完整或不在固定建模粒度中。当前筛选已保留，未套用公司预测。')
        future_rows=[row for period in scenario['future_periods'] for row in period['sales'] if not any(values and field in period.get('unavailable_dimensions',[]) for field,values in filters.items)]
        sales_frame=pd.DataFrame(future_rows,columns=["month",*DIM_LABELS,"sales_quantity","net_unit_price","unit_cost","sales_revenue","sales_cost","refund_amount","cogs_reversal_amount"])
        sales_frame=filter_dimensions(sales_frame,filters)
        with st.expander("查看当前情景未来销量、均价与费用"):
            sales_display=sales_frame.copy()
            for field in ("net_unit_price","unit_cost","sales_revenue","sales_cost","refund_amount","cogs_reversal_amount"):
                sales_display[field]=sales_display[field].map(money_text)
            st.dataframe(human_table(sales_display),hide_index=True,width="stretch")
            fee_rows=[row for period in scenario["future_periods"] for row in period["expense_rows"]]
            fee_frame=pd.DataFrame(fee_rows,columns=["month","expense_category","department","channel_scope","region_scope","amount"])
            fee_display=fee_frame.copy()
            fee_display["amount"]=fee_display["amount"].map(money_text)
            st.dataframe(human_table(fee_display),hide_index=True,width="stretch")
            export_artifact("下载当前情景公司费用（精确元）",csv_bytes(fee_frame),file_name=safe_export_name(engine.entity_id,month,"公司费用预测_"+scenario_name,Filters(),version=draft_id,fingerprint=base["metadata"]["training_fingerprint"]),mime="text/csv",key="forecast_download_expenses",on_click="ignore")
        if group_by:
            unavailable_groups=set(group_by)-set(base['metadata'].get('model_dimensions',engine.dimension_ids))
            if unavailable_groups or any(set(group_by)&set(period.get('unavailable_dimensions',[])) for period in scenario['future_periods']):
                st.info('当前联合分组的细分预测历史或模型粒度不完整，分组预测汇总不可用。')
            elif not sales_frame.empty:
                future_groups=forecast_groups(sales_frame,group_by)
                with st.expander('未来销售 · 当前联合分组'):
                    st.dataframe(human_table(future_groups),hide_index=True,width='stretch')
                    download(future_groups,'预测分类汇总','下载预测分类汇总（精确元）')
        export_artifact("下载当前情景未来销售（精确元）",csv_bytes(sales_frame),file_name=safe_export_name(engine.entity_id,month,"未来销售预测_"+scenario_name,filters,version=draft_id,fingerprint=base["metadata"]["training_fingerprint"]),mime="text/csv",key="forecast_download_sales",on_click="ignore")
        export_artifact("下载当前预测分析包（JSON）",json.dumps(forecast,ensure_ascii=False,indent=2,default=encode,allow_nan=False).encode("utf-8"),file_name=draft_id+".json",mime="application/json",key="forecast_download_pack",on_click="ignore")
        if st.button("保存当前预测版本",key="forecast_save"):
            try:
                st.session_state["forecast_last_saved"]=save_forecast(forecast)
            except (OSError,ValueError):
                st.error("版本保存失败，请核对项目输出目录权限及已有版本完整性；当前分析仍可下载。")
        saved=st.session_state.get("forecast_last_saved")
        if saved and saved["run_id"]==draft_id:
            st.success("已保存不可覆盖版本："+saved["run_id"]+("（内容相同，复用已有版本）" if saved["reused"] else ""))
        with st.expander("已保存预测版本（本地文件）"):
            archives=saved_forecasts(engine.entity_id)
            if archives:
                options={row["run_id"]:row for row in archives}
                if st.session_state.get("forecast_archive") not in options:
                    st.session_state.pop("forecast_archive",None)
                chosen_run=st.selectbox("选择已保存版本",list(options),key="forecast_archive")
                archive=load_forecast(options[chosen_run]["path"])
                frozen=archive["result"]
                st.caption(f"保存时间 {archive['created_at']}；截止 {frozen['metadata']['cutoff_month']}；方法 {METHOD_LABELS[frozen['metadata']['method']]}；预算 {frozen['metadata']['budget_version']}。保存的是当次销售筛选及公司全口径结果。")
                st.dataframe(pd.DataFrame([{"情景":SCENARIO_LABELS[name],"保存的销售范围全年收入（元）":money_text(item["selected_annual"]["net_revenue"]),"保存的公司全年利润（元）":money_text(item["company_annual"]["operating_profit"])} for name,item in frozen["scenarios"].items()]),hide_index=True,width="stretch")
                export_artifact("下载已保存版本（JSON）",Path(options[chosen_run]["path"]).read_bytes(),file_name=chosen_run+".json",mime="application/json",key="forecast_download_archive",on_click="ignore")
            else:
                st.info("尚无可复核的已保存版本；调整完成后点击保存。")

    elif page == '预算工作台':
        try:
            budget_workbench(engine,finance_store,finance_context,month)
        except WorkspaceError as error:
            st.error(str(error))

    elif page == '对账与跟进':
        try:
            finance_workbench(engine,finance_store,finance_context,month,filters,actual_version,group_by)
        except WorkspaceError as error:
            st.error(str(error))

    elif page == "点评与月报":
        st.markdown("### 经营点评与月报")
        st.caption("固定模板引用已计算事实，调查建议单列。月报是当前月份、销售筛选和预测设置的结果快照；调整后重新生成。公司费用与经营利润保留公司全口径。")
        st.caption("月报预测设置在本页单独选择；与预测页对照时，保持方法、窗口、选型指标和自定义假设一致。")
        with st.form("report_generation"):
            controls=st.columns(3)
            report_method=controls[0].selectbox("月报预测方法",["auto",*METHODS],format_func=lambda value:"自动（按回测WAPE）" if value=="auto" else METHOD_LABELS[value],key="report_method")
            report_window=controls[1].selectbox("月报近期窗口（月）",[3,1,6],key="report_window")
            report_objective=controls[2].selectbox("月报回测选型指标",["net_revenue","gross_margin","operating_profit"],format_func=lambda field:"公司"+LABELS[field],key="report_objective")
            with st.expander("设置月报自定义情景"):
                st.caption("参数作用于公司全部业务，单位为%。四种情景会同时导出，Excel内展示本次计算快照。")
                adjustment_columns=st.columns(3)
                report_changes={field:Decimal(str(adjustment_columns[index%3].number_input(label+"（%）",min_value=-100.0,max_value=100.0,value=0.0,step=1.0,key="report_"+field)))/Decimal(100) for index,(field,label) in enumerate(ADJUSTMENTS.items())}
            generate=st.form_submit_button("生成点评与Excel月报",type="primary")
        report_origin="个人模拟数据" if source in PRESETS else "用户提供来源（属性及完整性以接入确认为准）"
        try:
            finance_snapshot=workflow_snapshot(finance_store,finance_context,engine,month)
        except WorkspaceError as error:
            st.warning(str(error)+'；本次月报不含本机跟进记录。')
            finance_snapshot=None
        history_mode=st.session_state.get('_history_mode','mom')
        report_history=cached_result(engine,'historical',(month,filters,history_mode,group_by),lambda:historical_variance(engine,month,filters,history_mode,group_by))
        report_key=(key,report_method,report_window,report_objective,tuple(report_changes.items()),report_origin,group_by,content_digest(finance_snapshot),history_mode)
        if generate:
            try:
                with st.spinner("正在核对事实、计算预测并生成月报…"):
                    driver_cache=st.session_state.setdefault("driver_cache",{})
                    if key not in driver_cache:
                        if len(driver_cache)>=12:
                            driver_cache.clear()
                        driver_cache[key]=variance_pack(engine,month,filters,actual_version)
                    report_base=None
                    if engine.is_complete(month) and engine.metadata.get("semantics",{}).get("quantity_unit")=="件":
                        base_key=(engine.entity_id,engine.metadata["rule_version"],engine.metadata.get("source_fingerprint"),month,report_method,report_window,actual_version,report_objective)
                        bases=st.session_state.setdefault("forecast_cache",{})
                        if base_key not in bases:
                            if len(bases)>=4:
                                bases.clear()
                            bases[base_key]=forecast_base(engine,month,report_method,report_window,actual_version,report_objective)
                        report_base=bases[base_key]
                    report=build_report(engine,month,filters,actual_version,method=report_method,window=report_window,objective=report_objective,assumptions=Assumptions(**report_changes),data_origin=report_origin,analysis=pack,drivers=driver_cache[key],base=report_base,group_by=group_by,workflow=finance_snapshot,historical=report_history)
                    payload=excel_bytes(report)
                    st.session_state["report_generated"]={"key":report_key,"report":report,"excel":payload}
            except Exception:
                st.session_state.pop("report_generated",None)
                st.error("月报生成失败。请核对来源、月份、预算版本与Excel依赖；旧报告不会继续显示。")
        generated=st.session_state.get("report_generated")
        if generated is None or generated["key"]!=report_key:
            st.info("选择好月份、范围和预测设置后，点击生成。修改条件后需重新生成对应月报。")
        else:
            report=generated["report"]
            st.success("月报已生成，点评事实与计算来源核对通过。")
            st.caption(f"报告月份 {month}；预算 {actual_version}；销售范围 {scope_text}。"+report["metadata"]["forecast_status"]+"。")
            metric_cards(selected,("net_revenue","gross_margin"))
            metric_cards(company,("expenses","operating_profit"))
            current_section=None
            for row in report["commentary"]["statements"]:
                if row["section"]!=current_section:
                    st.markdown("#### "+row["section"])
                    current_section=row["section"]
                st.write(row["text"])
            with st.expander("查看点评事实与版本"):
                fact_rows=[{"事实ID":item["fact_id"],"范围":item["scope"],"报告月":item["period"],"数值":percent_text(item["value"]) if item["unit"]=="ratio" else money_text(item["value"]),"单位":"比例" if item["unit"]=="ratio" else "元"} for item in report["commentary"]["facts"]]
                st.dataframe(pd.DataFrame(fact_rows),hide_index=True,width="stretch")
                st.caption("报告版本 "+report["report_id"]+"；预测内容 "+(report["forecast_content_id"] or "不可用")+"。内容身份对应当次假设与来源。")
            filename=safe_export_name(engine.entity_id,month,"经营月报",filters,version=report["report_id"],fingerprint=engine.metadata.get("source_fingerprint")).removesuffix(".csv")
            export_artifact("下载Excel经营月报",generated["excel"],file_name=filename+".xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",key="report_download_excel",on_click="ignore")
            export_artifact("下载经营点评（Markdown）",markdown_report(report).encode("utf-8"),file_name=filename+".md",mime="text/markdown",key="report_download_markdown",on_click="ignore")
            export_artifact("下载月报分析包（精确JSON）",json.dumps(report,ensure_ascii=False,indent=2,default=encode,allow_nan=False).encode("utf-8"),file_name=filename+".json",mime="application/json",key="report_download_json",on_click="ignore")
            st.caption("Excel金额与比率为数值单元格，受Excel15位有效数字限制；精确金额与逐句依据保存在配套JSON。当前未接外部大模型，生成不需要API账号。")

    else:
        st.markdown("#### 来源与口径")
        st.caption(f"企业 {engine.entity_id} · 已确认实际范围 {coverage['complete_start']} 至 {coverage['complete_end']} · 本次读取 {st.session_state['loaded_at']}")
        st.caption("销售确认月与退款确认月分别统计。下面销售与退款跟随当前筛选，公司费用保留全公司范围；下载金额始终为元。")
        details = detail_tables(engine, month, filters)
        scope_metadata = {"entity_id": engine.entity_id, "source_fingerprint": engine.metadata.get("source_fingerprint"), "rule_version": engine.metadata["rule_version"], "month": month, "coverage": coverage, "amount_unit": "CNY excluding tax yuan", "sales_filters": filters.as_dict(), "group_by": list(group_by), "dimension_registry": engine.registry, "details": {name: {"row_count": len(frame), "source_available": frame.attrs.get("source_available"), "period_is_complete": frame.attrs.get("period_is_complete"), "scope": frame.attrs.get("scope")} for name, frame in details.items()}}
        export_artifact("下载明细范围与完整性说明（JSON）", data=json.dumps(scope_metadata, ensure_ascii=False, indent=2, default=encode).encode("utf-8"), file_name=safe_export_name(engine.entity_id, month, "明细范围说明", filters, fingerprint=engine.metadata.get("source_fingerprint")).replace(".csv", ".json"), mime="application/json", key="download_scope_metadata", on_click="ignore")
        if group_by:
            grouped=cached_result(engine,'dimensions',(month,group_by,filters),lambda:engine.dimensions(month,by=group_by,filters=filters))
            with st.expander('当前分类汇总（完整结果）'):
                st.dataframe(human_table(grouped[[*group_by,'net_revenue','net_cost','gross_margin','gross_margin_rate','confirmed_orders']]),hide_index=True,width='stretch')
                download(grouped,'分类汇总','下载当前分类汇总（精确元）')
        st.dataframe(pd.DataFrame([{'维度':entry['label'],'稳定编号':entry['id'],'缺失销售行':entry.get('missing_sales',0),'来源':str(entry.get('bindings','内置分类'))} for entry in engine.registry]),hide_index=True,width='stretch')
        tabs = st.tabs(["销售明细", "退款明细", "公司费用", "字段映射与校验"])
        for tab, kind, label in zip(tabs[:3], ("sales", "refunds", "company_expenses"), ("销售", "退款", "公司费用")):
            with tab:
                frame = details[kind]
                st.caption(f"{len(frame)}条记录" + (" · 公司全口径" if kind == "company_expenses" else " · 当前筛选范围"))
                if not selected["is_complete"]:
                    st.info("这是当前已知明细，不代表该月完整实际。文件中保留期间完整性标记。")
                if frame.empty:
                    st.info("此范围没有已知记录；是否为完整零记录请查看上方期间状态。")
                st.dataframe(human_table(frame), hide_index=True, width="stretch")
                download(frame, label+"明细", "下载"+label+"明细（精确元）", company=kind == "company_expenses")
        with tabs[3]:
            object_names = {"sales": "确认销售", "refunds": "退款事件", "expenses": "公司费用", "sales_budget": "销售预算", "expense_budget": "费用预算"}
            counts = pd.DataFrame([{"数据对象": object_names.get(name, name), "记录数": count} for name, count in engine.metadata["row_counts"].items()])
            st.dataframe(counts, hide_index=True, width="stretch")
            availability = engine.metadata.get("data_availability", {})
            st.caption("标准数据已完成唯一键、引用、日期、金额及退款累计检查。覆盖范围由首次接入确认，系统不会按日期表自动推断。")
            maps = [{"对象": name, "标准字段": field, "原始字段": original} for name, setting in profile["tables"].items() for field, original in setting.get("mapping", {}).items()]
            if maps:
                st.dataframe(pd.DataFrame(maps), hide_index=True, width="stretch")
            else:
                st.info("当前使用订单模型：数量×单价−明细折扣计算退款前收入，数量×历史成本计算成交成本。")
            st.caption("币种人民币、不含税、元、件；退款为独立正金额事件。缺来源和已知零记录分别处理。复杂行业口径需单独适配。")

except Exception:
    desktop_stage('页面处理','error','当前操作未完成，请查看页面提示或重新加载。')
    raise
finally:
    if sys.exc_info()[0] is None:
        desktop_stage('页面就绪','ready')
    elif getattr(sys.exc_info()[0],'__name__','')=='StopException':
        desktop_stage('页面提示','attention','请按页面提示核对来源或筛选。')
    loading_placeholder.markdown('<div class="fb-loading" data-active="false" aria-hidden="true"></div>',unsafe_allow_html=True)
