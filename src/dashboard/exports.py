"""One export interface: browser downloads or a native desktop save dialog."""
import streamlit as st
from desktop.paths import is_desktop
from desktop.artifacts import submit


@st.fragment
def _desktop_export(label,data,file_name,mime,key,width,disabled,icon):
    if st.button(label,key=key,width=width,disabled=disabled,icon=icon):
        try:
            submit(data,file_name,mime)
            st.toast('请选择系统保存窗口中的位置；完成后会显示保存结果。')
        except (OSError,ValueError,TypeError):
            st.error('无法准备导出文件，请检查个人数据目录权限，或缩小范围后重试。')


def export_artifact(label,*positional,data=None,file_name=None,mime=None,key=None,on_click='ignore',width='content',disabled=False,icon=None,**kwargs):
    if positional:
        if len(positional)!=1 or data is not None: raise TypeError('data must be supplied once')
        data=positional[0]
    if not is_desktop():
        options=dict(file_name=file_name,mime=mime,key=key,on_click=on_click,width=width,disabled=disabled,icon=icon,**kwargs)
        # Keep the original calling convention for source clients and wrappers.
        return st.download_button(label,data,**options) if positional else st.download_button(label,data=data,**options)
    return _desktop_export(label,data,file_name or 'FinanceBP导出',mime or 'application/octet-stream',key,width,disabled,icon)
