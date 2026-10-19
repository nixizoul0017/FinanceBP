"""Owned export queue. Only the native save dialog selects a destination path."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .events import atomic_json,session_dir

MAX_BYTES=250*1024*1024


def safe_name(value):
    name=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',str(value)).strip(' .')[:180]
    if not name: name='FinanceBP导出'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:
        name='FinanceBP_'+name
    return name


def submit(data,name,mime='application/octet-stream',folder=None):
    folder=Path(folder) if folder is not None else session_dir()
    if folder is None: raise ValueError('桌面保存服务未就绪，请重启应用')
    if hasattr(data,'getvalue'): data=data.getvalue()
    if isinstance(data,str): data=data.encode('utf-8')
    data=bytes(data)
    if len(data)>MAX_BYTES: raise ValueError('导出超过250MB，请缩小范围后分批导出')
    job=uuid.uuid4().hex
    target=folder/'exports'
    target.mkdir(parents=True,exist_ok=True)
    blob=target/(job+'.bin')
    with blob.open('xb') as stream: stream.write(data)
    atomic_json(target/(job+'.json'),{'id':job,'name':safe_name(name),'mime':mime,
                                     'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    return job


def read_request(path):
    path=Path(path)
    if not re.fullmatch(r'[0-9a-f]{32}\.json',path.name) or path.is_symlink():
        raise ValueError('无效导出请求')
    request=json.loads(path.read_text(encoding='utf-8'))
    if request.get('id')!=path.stem or request.get('name')!=safe_name(request.get('name','')):
        raise ValueError('无效导出文件名')
    blob=path.with_suffix('.bin')
    if blob.is_symlink() or blob.stat().st_size>MAX_BYTES:
        raise ValueError('无效导出内容')
    data=blob.read_bytes()
    if len(data)!=request.get('bytes') or hashlib.sha256(data).hexdigest()!=request.get('sha256'):
        raise ValueError('导出内容校验失败，请重新导出')
    return request,data


def save_request(path,destination):
    request,data=read_request(path)
    destination=Path(destination)
    suffix=Path(request['name']).suffix.lower()
    if not destination.suffix and suffix in ('.xlsx','.csv','.json','.md','.zip'):
        destination=destination.with_suffix(suffix)
    if not destination.parent.is_dir(): raise ValueError('保存文件夹不存在')
    temporary=destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    finish_request(path,'saved')
    return destination


def finish_request(path,state):
    path=Path(path)
    atomic_json(path.with_suffix('.result'),{'state':state})
    path.with_suffix('.bin').unlink(missing_ok=True)
    path.unlink(missing_ok=True)
