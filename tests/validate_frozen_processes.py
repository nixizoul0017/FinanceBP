"""Real bundled backend lifecycle; all ports/processes belong to this test."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from desktop.controller import Backend,healthy
from desktop.paths import AppPaths
from desktop.events import atomic_json


def wait_until(predicate,seconds=30):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate(): return True
        time.sleep(.2)
    return False


def child(application,data):
    paths=AppPaths(application.parent/'_internal/resources',data);paths.ensure()
    backend=Backend(paths,ROOT/'scripts/windows_app.py')
    with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(application)):
        backend.start()
    if not wait_until(backend.transport_ready): raise RuntimeError('Child backend not ready')
    atomic_json(data/'child-ready.json',{'helper_pid':os.getpid(),'backend_pid':backend.process.pid,'url':backend.url})
    try:
        while True: time.sleep(1)
    finally: backend.stop()


def run(application,data):
    paths=AppPaths(application.parent/'_internal/resources',data);paths.ensure()
    checks=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition: raise AssertionError(name)
    def start(backend):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'executable',str(application)):
            backend.start()
    backend=Backend(paths,ROOT/'scripts/windows_app.py')
    try:
        start(backend)
        check('bundled_backend_owns_loopback_health',wait_until(backend.transport_ready) and backend.url.startswith('http://127.0.0.1:'))
        previous=backend.run_dir;url=backend.url
        backend.stop()
        check('normal_stop_removes_owned_session',not previous.exists())
        check('normal_stop_releases_port',not healthy(url))
        start(backend)
        check('restart_uses_new_session',wait_until(backend.transport_ready) and backend.run_dir!=previous)
        backend.process.kill();backend.process.wait(timeout=10)
        check('abnormal_child_exit_not_ready',not backend.transport_ready())
        backend.stop()
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen()
            port=occupied.getsockname()[1]
            with patch('desktop.controller.free_port',return_value=port): start(backend)
            check('occupied_port_fails_owned_child',backend.process.wait(timeout=30)!=0 and not backend.transport_ready())
            check('occupied_port_listener_not_killed',occupied.getsockname()[1]==port)
            backend.stop()
        helper_data=data/'parent-death';helper_data.mkdir(exist_ok=True)
        helper=subprocess.Popen([sys._base_executable,str(Path(__file__).resolve()),'--child','--application',str(application),'--data',str(helper_data)],
                                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            ready=helper_data/'child-ready.json'
            check('parent_death_fixture_ready',wait_until(ready.exists))
            state=json.loads(ready.read_text(encoding='utf-8'))
            check('parent_handle_matches_test_helper',state['helper_pid']==helper.pid)
            helper.kill();helper.wait(timeout=10)
            check('parent_death_stops_bundled_backend',wait_until(lambda:not healthy(state['url']),15))
        finally:
            if helper.poll() is None: helper.kill();helper.wait(timeout=10)
    finally: backend.stop()
    return {'passed':True,'checks':checks,'application':str(application),'source_databases_accessed':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--application',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    application,data=args.application.resolve(),args.data.resolve()
    if args.child: child(application,data)
    else:
        try: result=run(application,data)
        except Exception as error:
            import traceback
            result={'passed':False,'error':str(error),'traceback':traceback.format_exc()}
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:result[key] for key in ('passed','error') if key in result}))
        raise SystemExit(0 if result['passed'] else 1)
