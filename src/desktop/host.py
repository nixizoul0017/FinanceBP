"""Native Windows host: a dedicated WebView2 window with owned local analysis."""
from datetime import datetime
import html
import json
import os
from pathlib import Path
import threading
import time
import uuid

from .controller import Backend,SingleInstance
from .events import atomic_json
from .artifacts import read_request,save_request,finish_request

TITLE='FinanceBP · 财务经营分析工作台'


def boot_html(message='正在准备独立应用窗口…',failed=False):
    actions='<button onclick="window.pywebview.api.restart()">重新启动分析</button><button onclick="window.pywebview.api.open_logs()">打开日志文件夹</button>' if failed else ''
    return '''<!doctype html><meta charset="utf-8"><style>body{margin:0;background:#f3f6fa;color:#192e45;font-family:'Microsoft YaHei',sans-serif;display:grid;place-items:center;height:100vh}.card{background:white;border:1px solid #dee6ef;border-radius:18px;padding:48px;max-width:620px;box-shadow:0 20px 70px #192e4510}h1{font-size:27px;margin:0 0 18px}p{line-height:1.8;color:#64758a}button{border:1px solid #dee6ef;border-radius:7px;background:#234f7b;color:white;padding:12px 20px;margin:12px 12px 0 0;cursor:pointer}.ring{height:28px;width:28px;border:3px solid #dee6ef;border-top-color:#234f7b;border-radius:50%;animation:spin 1s linear infinite;margin:0 0 24px}@keyframes spin{to{transform:rotate(360deg)}}</style><div class="card">'''+('' if failed else '<div class="ring"></div>')+'<h1>'+('应用暂未就绪' if failed else 'FinanceBP 正在启动')+'</h1><p>'+html.escape(message)+'</p><p>本机运行 · 数据保留在你的电脑</p>'+actions+'</div>'


class HostAPI:
    def __init__(self,host): self._host=host
    def restart(self):
        threading.Thread(target=self._host.restart,daemon=True).start()
    def open_logs(self): self._host.open_folder(self._host.paths.logs)


class Host:
    def __init__(self,paths,entry,instance):
        self.paths,self.instance=paths,instance
        self.backend=Backend(paths,entry)
        self.closed=threading.Event()
        self.guard=threading.RLock()
        self.loaded=False
        self.failed=False
        self.last_progress=None
        self.focus_time=0
        self.window=None
        self.download_feedback=False
        self.ready=False

    def configure_downloads(self):
        """Retain native save dialogs for Plotly/dataframe toolbar downloads too."""
        if self.download_feedback: return
        try:
            from System import Action
            def install():
                if self.download_feedback: return
                core=self.window.native.browser.webview.CoreWebView2
                def starting(sender,args):
                    if args.Cancel:
                        self.notify('已取消导出，文件未保存。')
                        return
                    operation=args.DownloadOperation
                    def changed(sender,event):
                        state=str(operation.State)
                        if state=='Completed': self.notify('已保存：'+str(operation.ResultFilePath))
                        elif state=='Interrupted': self.notify('下载未完成，请核对目标文件夹权限或重新导出。')
                    operation.StateChanged+=changed
                core.DownloadStarting+=starting
                self.download_feedback=True
            self.window.native.Invoke(Action(install))
        except Exception:
            import traceback
            traceback.print_exc()

    def notify(self,message):
        # Text only: exported filenames and user-controlled values never become HTML.
        script='''(()=>{let n=document.getElementById('financebp-native-notice');if(n)n.remove();n=document.createElement('div');n.id='financebp-native-notice';n.setAttribute('role','status');n.style.cssText='position:fixed;bottom:24px;right:24px;z-index:999999;background:#192e45;color:white;border-radius:10px;padding:16px 22px;max-width:520px;box-shadow:0 6px 24px #0003;font:14px Microsoft YaHei;line-height:1.6';n.textContent='''+json.dumps(str(message),ensure_ascii=True)+''';document.body.appendChild(n);setTimeout(()=>n.remove(),8000)})()'''
        # Native download events run on the Windows UI thread. Evaluate scripts
        # from a worker so that their completion never blocks the message loop.
        def render():
            try: self.window.evaluate_js(script)
            except Exception: pass
        threading.Thread(target=render,daemon=True).start()

    def open_folder(self,path):
        path=Path(path)
        path.mkdir(parents=True,exist_ok=True)
        if os.name=='nt': os.startfile(path)

    def restart(self):
        with self.guard:
            self.loaded=False;self.failed=False;self.last_progress=None;self.ready=False
            self.window.load_html(boot_html())
            try: self.backend.start()
            except Exception:
                import traceback
                traceback.print_exc()
                self.error('无法启动本机分析进程。请核对程序文件和目录权限，再重试。日志：'+str(self.paths.logs))

    def error(self,message):
        if not self.failed:
            self.failed=True
            self.window.set_title(TITLE+' · 需要处理')
            self.window.load_html(boot_html(message,True))

    def monitor(self):
        try: self.backend.start()
        except Exception:
            import traceback
            traceback.print_exc()
            self.error('无法启动本机分析进程。请核对程序文件和目录权限，再重试。日志：'+str(self.paths.logs))
        while not self.closed.wait(.25):
            with self.guard:
                process=self.backend.process
                if process is None: continue
                focus=self.paths.runtime/'focus.request'
                if focus.exists() and focus.stat().st_mtime_ns!=self.focus_time:
                    self.focus_time=focus.stat().st_mtime_ns
                    self.window.restore();self.window.show()
                if process.poll() is not None:
                    self.error('分析进程已退出。可以重新启动；已保存的数据会继续保留。日志：'+str(self.backend.log_path))
                    continue
                if not self.loaded and not self.failed:
                    if self.backend.transport_ready():
                        self.loaded=True
                        self.window.load_url(self.backend.url)
                    elif time.monotonic()-self.backend.started>90:
                        self.error('90秒内未能启动本机分析服务，请查看日志并重试。')
                if self.loaded and not self.ready and not self.failed and time.monotonic()-self.backend.started>180:
                    self.error('本机服务已经启动，但分析页面在180秒内未就绪。请查看日志，核对数据源后重试。')
                progress=self.backend.progress()
                signature=(progress.get('stage'),progress.get('state'))
                if progress and signature!=self.last_progress:
                    self.last_progress=signature
                    with (self.paths.logs/'startup-timings.jsonl').open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps({'run_id':self.backend.run_dir.name,'stage':signature[0],'state':signature[1],
                                                 'elapsed_seconds':round(time.monotonic()-self.backend.started,3)},ensure_ascii=False)+'\n')
                    if signature[1]=='ready':
                        self.ready=True;self.window.set_title(TITLE)
                    elif signature[1] in ('attention','error'):
                        self.ready=True;self.window.set_title(TITLE+' · 请核对页面提示')
                    elif not self.loaded: self.window.load_html(boot_html(signature[0]+'，请稍候…'))
                if self.loaded and not self.failed:
                    for request in sorted((self.backend.run_dir/'exports').glob('*.json')):
                        self.export(request)
                    for request in sorted((self.backend.run_dir/'uploads').glob('*.json')):
                        self.upload(request)

    def upload(self,path):
        import webview
        try:
            request=json.loads(path.read_text(encoding='utf-8'))
            if uuid.UUID(hex=path.stem).hex!=path.stem or request.get('id')!=path.stem:
                raise ValueError('文件选择请求无效')
            types=request['types']
            if any(value not in ('json','xlsx') for value in types): raise ValueError('不支持的文件类型')
            patterns=';'.join('*.'+value for value in types) or '*.*'
            choice=self.window.create_file_dialog(webview.FileDialog.OPEN,file_types=(f'支持的文件 ({patterns})',))
            if not choice:
                result={'state':'cancelled'}
            else:
                source=Path(choice[0])
                if types and source.suffix.lower().lstrip('.') not in types: raise ValueError('请选择匹配的JSON或Excel文件')
                if source.stat().st_size>min(int(request['limit']),20*1024*1024): raise ValueError('文件超过20MB，请拆分后再导入')
                data=source.read_bytes()
                if len(data)>20*1024*1024: raise ValueError('文件过大')
                path.with_suffix('.bin').write_bytes(data)
                result={'state':'selected','name':source.name,'source_path':str(source.resolve())}
        except Exception as error:
            result={'state':'error','message':'无法读取所选文件：'+str(error)}
        atomic_json(path.with_suffix('.result'),result)
        path.unlink(missing_ok=True)

    def export(self,path):
        import webview
        try:
            request,_=read_request(path)
            suffix=Path(request['name']).suffix.lower()
            types=(f'FinanceBP 文件 (*{suffix})','所有文件 (*.*)') if suffix in ('.xlsx','.csv','.json','.md','.zip') else ()
            destination=self.window.create_file_dialog(webview.FileDialog.SAVE,directory=str(self.paths.exports),save_filename=request['name'],file_types=types)
            if destination:
                target=save_request(path,destination[0] if isinstance(destination,(tuple,list)) else destination)
                self.notify('已保存：'+str(target))
            else:
                finish_request(path,'cancelled');self.notify('已取消导出，文件未保存。')
        except Exception:
            finish_request(path,'error')
            self.notify('文件未保存。请核对目标文件夹权限和文件占用情况，再重新导出。')

    def backup(self):
        import webview
        from .workspace import backup
        choice=self.window.create_file_dialog(webview.FileDialog.SAVE,directory=str(self.paths.backups),save_filename='FinanceBP_备份_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.zip',file_types=('FinanceBP备份 (*.zip)',))
        if not choice: return
        try:
            with self.guard:
                count=backup(self.paths.data,choice[0] if isinstance(choice,(list,tuple)) else choice)
            self.notify(f'备份完成：{count}个数据文件。仅包含已保存内容，不含密码和日志。')
        except Exception: self.notify('备份未完成，请核对保存位置和个人数据文件。')

    def restore(self):
        import webview
        from .workspace import restore
        choice=self.window.create_file_dialog(webview.FileDialog.OPEN,file_types=('FinanceBP备份 (*.zip)',))
        if not choice: return
        if not self.window.create_confirmation_dialog('恢复个人数据','将先自动备份当前数据，再恢复所选备份内的同名记录。未保存的操作及当前筛选会结束，分析页面将重新打开。是否继续？'): return
        try:
            with self.guard:
                self.backend.stop()
                count=restore(self.paths.data,choice[0])
                self.restart()
            self.notify(f'已恢复{count}个数据文件，正在重新读取。')
        except Exception:
            self.restart();self.notify('恢复未完成，原数据保留。请核对备份版本及完整性。')

    def import_old(self):
        import webview
        from .workspace import import_legacy
        choice=self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if not choice: return
        if not self.window.create_confirmation_dialog('导入旧项目数据','请确认选中旧项目根目录。将先备份当前数据，再导入旧项目已保存记录；同名记录以当前数据为准。原目录不删除，未保存操作将结束。是否继续？'): return
        try:
            with self.guard:
                self.backend.stop()
                count=import_legacy(self.paths.data,choice[0])
                self.restart()
            self.notify(f'已导入{count}个数据文件。旧项目文件仍然保留。')
        except Exception:
            self.restart();self.notify('导入未完成，请确认选择的是包含outputs的旧项目根目录，且数据版本兼容。')

    def about(self):
        version=(self.paths.resources/'VERSION').read_text(encoding='utf-8').strip()
        self.window.create_confirmation_dialog('关于 FinanceBP',f'FinanceBP {version} · Windows独立应用\n个人使用与作品展示版 · 未作公开分发代码签名\n财务计算在本机执行，企业数据库只读。\n个人数据：{self.paths.data}\n问题诊断：{self.paths.logs}\n模拟数据仅供学习演示。')


def run(paths,entry):
    instance=SingleInstance(paths.runtime)
    if not instance.acquire(): return 0
    import webview
    from webview.menu import Menu,MenuAction
    host=Host(paths,entry,instance)
    window=webview.create_window(TITLE,html=boot_html(),js_api=HostAPI(host),width=1280,height=900,
                                 min_size=(900,650),background_color='#F3F6FA')
    host.window=window
    window.events.closed+=lambda:host.closed.set()
    window.events.loaded+=host.configure_downloads
    menu=[Menu('文件',[MenuAction('备份个人数据…',host.backup),MenuAction('恢复备份…',host.restore),
                      MenuAction('导入旧项目数据…',host.import_old),MenuAction('打开导出文件夹',lambda:host.open_folder(paths.exports)),
                      MenuAction('打开个人数据文件夹',lambda:host.open_folder(paths.data))]),
          Menu('帮助',[MenuAction('重新加载分析',host.restart),MenuAction('打开诊断日志',lambda:host.open_folder(paths.logs)),MenuAction('关于',host.about)])]
    webview.settings['ALLOW_DOWNLOADS']=True
    webview.settings['ALLOW_FILE_URLS']=False
    try:
        webview.start(host.monitor,gui='edgechromium',debug=False,menu=menu,private_mode=True,
                      storage_path=str(paths.runtime/'webview'),icon=str(paths.resources/'docs/assets/financebp.ico'))
    finally:
        host.closed.set()
        with host.guard: host.backend.stop()
        instance.close()
    return 0
