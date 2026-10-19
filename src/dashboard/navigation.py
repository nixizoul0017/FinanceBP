"""Grouped native navigation, with stable session keys for page state."""
import streamlit as st

GROUPS = (
    ("经营分析", (("经营总览", "space_dashboard"), ("月度趋势", "show_chart"), ("维度分析", "layers"))),
    ("预算与预测", (("预算工作台", "edit_document"), ("预算比较", "bar_chart"), ("预测与情景", "account_tree"))),
    ("报告与数据", (("对账与跟进", "fact_check"), ("点评与月报", "description"), ("数据与下载", "database"))),
)
PAGES = tuple(name for _, items in GROUPS for name, _ in items)


def navigate(page):
    if page != st.session_state.get('page'):
        from .dimension_ui import discard_draft
        discard_draft()
        st.session_state['_filter_loading'] = True
    st.session_state["page"] = page


def render_navigation():
    if st.session_state.get("page") not in PAGES:
        st.session_state["page"] = PAGES[0]
    current = st.session_state["page"]
    for group, items in GROUPS:
        st.markdown(f'<div class="nav-group">{group}</div>', unsafe_allow_html=True)
        for name, icon in items:
            st.button(name, icon=f":material/{icon}:", key="nav_" + name,
                      type="primary" if current == name else "secondary",
                      width="stretch", on_click=navigate, args=(name,))
    return current


def group_for(page):
    return next(group for group, items in GROUPS if any(name == page for name, _ in items))
