"""Own the child process and single application instance; never reuse an unrelated service."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler,build_opener
import uuid
import shutil

from .events import atomic_json


def healthy(url):
    try:
        with build_opener(ProxyHandler({})).open(url+'/_stcore/health',timeout=1) as response:
            return response.status==200 and response.read().strip()==b'ok'
    except (OSError,ValueError): return False


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


class SingleInstance:
    def __init__(self,runtime):
        self.runtime=Path(runtime)
        self.runtime.mkdir(parents=True,exist_ok=True)
        self.stream=None

    def acquire(self):
        self.stream=(self.runtime/'application.lock').open('a+b')
        self.stream.seek(0);self.stream.write(b'0');self.stream.flush();self.stream.seek(0)
        if os.name=='nt':
            import msvcrt
            try: msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                self.stream.close();self.stream=None
                atomic_json(self.runtime/'focus.request',{'at':time.time()})
                return False
        return True

    def close(self):
        if self.stream:
            if os.name=='nt':
                import msvcrt
                self.stream.seek(0);msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            self.stream.close();self.stream=None


class Backend:
    def __init__(self,paths,entry):
        self.paths,self.entry=paths,Path(entry)
        self.process=None
        self.run_dir=None
        self.log=None
        self.url=None
        self.started=0
        self.port=None

    def start(self):
        self.stop()
        self.started=time.monotonic()
        self.run_dir=self.paths.runtime/'sessions'/uuid.uuid4().hex
        self.run_dir.mkdir(parents=True)
        self.port=free_port()
        self.url=f'http://127.0.0.1:{self.port}'
        environment=os.environ.copy()
        environment.update(FINANCEBP_DESKTOP='1',FINANCEBP_RUN_DIR=str(self.run_dir),
                           FINANCEBP_DATA_DIR=str(self.paths.data),FINANCEBP_RESOURCES_DIR=str(self.paths.resources),
                           FINANCEBP_HOST_PID=str(os.getpid()),
                           PYTHONUTF8='1',PYTHONUNBUFFERED='1')
        # The frozen executable dispatches --backend itself; it is not a Python CLI.
        command=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(self.entry)])
        command+=['--backend','--port',str(self.port)]
        self.log_path=self.paths.logs/('backend_'+self.run_dir.name+'.log')
        self.log=self.log_path.open('w',encoding='utf-8')
        self.process=subprocess.Popen(command,cwd=self.paths.resources,env=environment,stdin=subprocess.DEVNULL,
                                      stdout=self.log,stderr=subprocess.STDOUT,
                                      creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        atomic_json(self.run_dir/'owner.json',{'pid':self.process.pid,'run_id':self.run_dir.name,'port':self.port})

    def transport_ready(self):
        if not self.process or self.process.poll() is not None: return False
        try:
            marker=json.loads((self.run_dir/'backend.json').read_text(encoding='utf-8'))
            owned=(marker.get('pid')==self.process.pid or marker.get('launcher_pid')==self.process.pid)
            return owned and marker.get('run_id')==self.run_dir.name and healthy(self.url)
        except (OSError,ValueError): return False

    def progress(self):
        try:
            value=json.loads((self.run_dir/'progress.json').read_text(encoding='utf-8'))
            marker=json.loads((self.run_dir/'backend.json').read_text(encoding='utf-8'))
            owned=(marker.get('pid')==self.process.pid or marker.get('launcher_pid')==self.process.pid)
            return value if owned and value.get('pid')==marker.get('pid') and value.get('run_id')==self.run_dir.name else {}
        except (OSError,ValueError,AttributeError): return {}

    def stop(self):
        process=self.process
        if process is not None and process.poll() is None:
            atomic_json(self.run_dir/'stop.request',{'pid':process.pid})
            try: process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=3)
        if self.log: self.log.close();self.log=None
        self.process=None
        # Session blobs may contain financial exports or uploads. Retain diagnostic
        # logs separately, but remove this owned session only after the child exits.
        if self.run_dir and self.run_dir.exists():
            parent=(self.paths.runtime/'sessions').resolve()
            if self.run_dir.parent.resolve()==parent and not self.run_dir.is_symlink() and not self.run_dir.is_junction():
                try: shutil.rmtree(self.run_dir)
                except OSError: pass


def run_backend(paths,port):
    import threading
    from .events import session_dir,stage
    folder=session_dir()
    if folder is None: raise ValueError('缺少桌面会话')
    if sys.stdout is None or sys.stderr is None:
        paths.logs.mkdir(parents=True,exist_ok=True)
        sys.stdout=sys.stderr=(paths.logs/('backend_runtime_'+folder.name+'.log')).open('a',encoding='utf-8',buffering=1)
    stage('组件加载')
    atomic_json(folder/'backend.json',{'pid':os.getpid(),'launcher_pid':os.getppid(),'run_id':folder.name})
    # Parent death also stops the child, including abnormal application termination.
    parent=int(os.environ.get('FINANCEBP_HOST_PID',os.getppid()))
    def watch():
        handle=None
        if os.name=='nt':
            import ctypes
            ctypes.windll.kernel32.OpenProcess.restype=ctypes.c_void_p
            handle=ctypes.windll.kernel32.OpenProcess(0x100000,False,parent)
        while True:
            dead=(ctypes.windll.kernel32.WaitForSingleObject(ctypes.c_void_p(handle),0)==0) if handle else os.getppid()!=parent
            if (folder/'stop.request').exists() or dead:
                try:
                    from streamlit.runtime import get_instance
                    get_instance().stop()
                except Exception: pass
                time.sleep(1)
                os._exit(0)
            time.sleep(.25)
    threading.Thread(target=watch,daemon=True).start()
    from streamlit.web import cli
    stage('服务启动')
    sys.argv=['streamlit','run',str(paths.resources/'app.py'),'--server.address=127.0.0.1',f'--server.port={port}',
              '--global.developmentMode=false',
              '--server.headless=true','--server.fileWatcherType=none','--browser.gatherUsageStats=false',
              '--server.runOnSave=false']
    cli.main()
