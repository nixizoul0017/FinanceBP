"""Windows native executable entry, frozen backend dispatch and diagnostic self-test."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT=Path(__file__).resolve().parents[1]
if not getattr(sys,'frozen',False): sys.path.insert(0,str(ROOT/'src'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--backend',action='store_true')
    parser.add_argument('--port',type=int,default=8501)
    parser.add_argument('--self-test',type=Path)
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--mysql-port',type=int)
    args=parser.parse_args()
    os.environ['FINANCEBP_DESKTOP']='1'
    if args.data_dir: os.environ['FINANCEBP_DATA_DIR']=str(args.data_dir.resolve())
    from desktop.paths import AppPaths
    paths=AppPaths.current()
    if args.backend:
        from desktop.controller import run_backend
        run_backend(paths,args.port)
        return 0
    if args.self_test:
        from desktop.selftest import run
        args.self_test.parent.mkdir(parents=True,exist_ok=True)
        try:
            result=run(paths,args.mysql_port)
            args.self_test.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return 0
        except Exception as error:
            import traceback
            args.self_test.write_text(json.dumps({'passed':False,'error':str(error),'traceback':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
            return 1
    paths.ensure()
    # Frozen windowed apps have no stdout; third-party loggers still need a stream.
    log=(paths.logs/'application.log').open('a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    try:
        from desktop.host import run
        return run(paths,Path(__file__).resolve())
    except Exception:
        import traceback
        traceback.print_exc()
        if os.name=='nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,'应用未能启动。请核对WebView2运行组件。\n日志位置：'+str(paths.logs),'FinanceBP：启动未完成',0x10)
        return 1
    finally: log.close()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
