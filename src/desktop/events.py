"""Small atomic messages for an owned desktop session; never contain business rows."""
import json
import os
from pathlib import Path
import time
import uuid


def atomic_json(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def session_dir():
    value=os.environ.get('FINANCEBP_RUN_DIR')
    return Path(value).resolve() if value else None


def stage(name,state='running',message=''):
    folder=session_dir()
    if folder:
        atomic_json(folder/'progress.json',{'stage':name,'state':state,'message':message,'at':time.time(),
                                          'pid':os.getpid(),'run_id':folder.name})
