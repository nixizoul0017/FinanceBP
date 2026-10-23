"""Native file selection in desktop mode; retain Streamlit uploads in source mode."""
from io import BytesIO
import json
from pathlib import Path
import uuid

import streamlit as st
from desktop.paths import is_desktop
from desktop.events import session_dir, atomic_json


class SelectedFile(BytesIO):
    def __init__(self,data,name,source_path):
        super().__init__(data)
        self.name,self.source_path,self.size=name,source_path,len(data)


@st.fragment(run_every=1)
def _native_upload(label,types,key,limit,multiple=False):
    folder=session_dir()/'uploads'
    folder.mkdir(parents=True,exist_ok=True)
    pending_key='_native_pending_'+key
    value_key='_native_value_'+key
    job=st.session_state.get(pending_key)
    if job:
        result=folder/(job+'.result')
        if result.exists():
            value=json.loads(result.read_text(encoding='utf-8'))
            del st.session_state[pending_key]
            result.unlink(missing_ok=True)
            if value['state']=='selected':
                if multiple:
                    chosen=[]
                    for index,item in enumerate(value.get('files',[])):
                        blob=folder/(job+'_'+str(index)+'.bin')
                        try: chosen.append(SelectedFile(blob.read_bytes(),item['name'],item['source_path']))
                        finally: blob.unlink(missing_ok=True)
                    st.session_state[value_key]=chosen
                else:
                    blob=folder/(job+'.bin')
                    try:
                        st.session_state[value_key]=SelectedFile(blob.read_bytes(),value['name'],value['source_path'])
                    finally: blob.unlink(missing_ok=True)
                st.rerun()
            elif value['state']=='error': st.error(value['message'])
            else: st.toast('已取消选择，原文件保持不变。')
    if st.button(label+'…',key=key,disabled=bool(st.session_state.get(pending_key))):
        job=uuid.uuid4().hex
        atomic_json(folder/(job+'.json'),{'id':job,'types':types,'limit':limit,'multiple':bool(multiple)})
        st.session_state[pending_key]=job
        st.caption('请在系统文件窗口中选择文件。')
    current=st.session_state.get(value_key,[] if multiple else None)
    if current: st.caption('已选择：'+('、'.join(item.name for item in current) if multiple else current.name))
    return current


def import_artifact(label,*,type=None,key=None,max_upload_size=20,**kwargs):
    if not is_desktop():
        # Older browser versions use the configured server upload limit.
        return st.file_uploader(label,type=type,key=key,max_upload_size=max_upload_size,**kwargs)
    types=[type] if isinstance(type,str) else list(type or [])
    multiple=bool(kwargs.pop('accept_multiple_files',False))
    return _native_upload(label,types,key or label,int(max_upload_size)*1024*1024,multiple)
