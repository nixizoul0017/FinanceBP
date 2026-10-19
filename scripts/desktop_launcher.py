"""One-click desktop entry: progress, actionable errors, readiness and browser."""
from pathlib import Path
import argparse
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import traceback
from urllib.request import ProxyHandler, build_opener
import venv
import webbrowser

import manage

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
RUNTIME = ROOT / 'outputs/runtime'
STATE = RUNTIME / 'desktop_service.json'
SUPPORTED = {(3, 13), (3, 14)}


class StartupError(RuntimeError):
    def __init__(self, stage, reason, solution):
        self.stage, self.reason, self.solution = stage, reason, solution
        super().__init__(reason)


def native_error(message):
    """Fallback alert when Tk itself is absent; arguments never enter shell code."""
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, '财务分析：启动未完成', 0x10)
    elif sys.platform == 'darwin':
        script = 'on run argv\ndisplay alert "财务分析：启动未完成" message (item 1 of argv) as critical\nend run'
        subprocess.run(['osascript', '-e', script, message], check=False)
    else:
        print(message, file=sys.stderr)


def healthy(url):
    try:
        # Loopback never goes through a machine's corporate/VPN HTTP proxy.
        with build_opener(ProxyHandler({})).open(url + '/_stcore/health', timeout=2) as response:
            return response.status == 200 and response.read().strip() == b'ok'
    except (OSError, ValueError):
        return False


def matching_process(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == 'nt':
            command = ['powershell.exe', '-NoProfile', '-Command',
                       '[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); '
                       f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine']
        else:
            command = ['ps', '-p', str(pid), '-o', 'command=']
        output = subprocess.check_output(command, timeout=10, **hidden_process_options()).decode(errors='replace')
        return str(ROOT / 'app.py') in output and 'streamlit' in output
    except (OSError, subprocess.SubprocessError):
        return False


def hidden_process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def existing_service():
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        port = state['port']
        if state.get('project') != str(ROOT) or not isinstance(port, int) or not 1024 <= port <= 65535:
            return None
        url = f'http://127.0.0.1:{port}'
        if matching_process(state.get('pid')) and healthy(url):
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class Controller:
    def __init__(self, notify, port=8501, no_browser=False):
        self.notify, self.port, self.no_browser = notify, port, no_browser
        self.cancelled = threading.Event()
        self.process = None
        self.url = None
        self.log = None
        self.log_path = RUNTIME / f'launcher_{time.time_ns()}.log'

    def command(self, args, stage, reason, solution, timeout=180):
        if self.cancelled.is_set():
            raise InterruptedError()
        process = subprocess.Popen([str(x) for x in args], cwd=ROOT, stdout=self.log,
                                   stderr=subprocess.STDOUT, **hidden_process_options())
        self.process = process
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.stop_child()
            raise StartupError(stage, reason + '（等待超时）', solution)
        finally:
            if process.poll() is not None:
                self.process = None
        if self.cancelled.is_set():
            raise InterruptedError()
        if code != 0:
            self.log.flush()
            raise StartupError(stage, reason, solution)

    def prepare(self):
        if sys.version_info[:2] not in SUPPORTED or struct.calcsize('P') * 8 != 64:
            raise StartupError('Python环境', '当前解释器不是64位Python3.13或3.14。', '安装完整的64位Python3.13或3.14，再双击启动入口。')
        for name in ('app.py', 'requirements.txt', 'configs/demo_files.json', '.streamlit/config.toml'):
            if not (ROOT / name).is_file():
                raise StartupError('项目文件', f'缺少 {name}', '将整个项目ZIP完整解压，不要单独复制启动文件。')
        if not PYTHON.exists():
            if (ROOT / '.venv').exists():
                raise StartupError('本机环境', '已有.venv不适用于此电脑或系统。', '将旧.venv移到项目外，再双击入口；不要跨电脑复制.venv。')
            self.notify('progress', '正在创建本机Python环境…')
            self.command([sys.executable, '-m', 'venv', ROOT / '.venv'], '创建环境', '无法创建.venv。', '确认项目文件夹可写，Python包含venv和pip。')
        self.notify('progress', '正在检查运行环境和依赖…')
        self.command([PYTHON, '-c', 'import sys; assert sys.version_info[:2] in {(3,13),(3,14)}'],
                     'Python版本', '项目环境的Python版本不符合要求。', '将旧.venv移到项目外，再用Python3.13或3.14打开入口。')
        pip_probe = subprocess.run([str(PYTHON), '-c', 'import pip'], cwd=ROOT, stdout=self.log,
                                   stderr=subprocess.STDOUT, timeout=30, **hidden_process_options())
        if pip_probe.returncode != 0:
            self.notify('progress', '正在补全Python安装组件…')
            self.command([PYTHON, '-m', 'ensurepip', '--upgrade'], '安装组件', '环境缺少pip且无法自动补全。',
                         '使用包含pip和venv的完整Python安装；将未完成的.venv移到项目外后重新启动。')
        # Check every pinned distribution, so a partly installed/upgraded environment is repaired.
        probe = ('from pathlib import Path; from importlib.metadata import version; '
                 'lines=Path("requirements.txt").read_text().splitlines(); '
                 'pairs=[x.strip().split("==",1) for x in lines if x.strip() and not x.lstrip().startswith("#")]; '
                 'assert all(version(n.split("[",1)[0])==v for n,v in pairs)')
        checked = subprocess.run([str(PYTHON), '-c', probe], cwd=ROOT, stdout=self.log,
                                 stderr=subprocess.STDOUT, timeout=60, **hidden_process_options())
        if checked.returncode != 0:
            self.notify('progress', '正在安装或补全依赖，首次使用可能需要几分钟…')
            self.command([PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check',
                          '--timeout', '30', '--retries', '2', '-r', ROOT / 'requirements.txt'],
                         '依赖安装', '依赖未能安装完整。',
                         '检查网络和Python包源；Mac还需确认Python与芯片架构匹配。查看错误日志后重试，不要关闭安装窗口。', timeout=900)
        self.command([PYTHON, '-c', 'import streamlit,openpyxl,pandas,sqlalchemy,plotly'],
                     '依赖加载', '依赖已记录安装，但无法正常加载。', '查看日志中的缺失模块或动态库提示，修复后重试；不要复制其他电脑的.venv。')

    def launch(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.log = self.log_path.open('w', encoding='utf-8')
        os.environ['PYTHONUTF8'] = '1'
        os.environ['PYTHONUNBUFFERED'] = '1'
        try:
            self.notify('progress', '正在检查项目…')
            self.prepare()
            self.url = existing_service()
            if self.url:
                self.notify('progress', '程序已在运行，正在打开现有页面…')
            else:
                if self.cancelled.is_set():
                    raise InterruptedError()
                port = manage.available_port(self.port)
                self.url = f'http://127.0.0.1:{port}'
                self.notify('progress', '正在启动网页服务，请稍候…')
                self.process = subprocess.Popen([str(PYTHON), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
                                                '--server.address=127.0.0.1', f'--server.port={port}',
                                                '--server.headless=true', '--browser.gatherUsageStats=false'],
                                               cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT, **hidden_process_options())
                deadline = time.monotonic() + 90
                while not healthy(self.url):
                    if self.cancelled.is_set():
                        raise InterruptedError()
                    if self.process.poll() is not None:
                        raise StartupError('网页服务', '网页服务启动后退出。', '查看日志中的错误，核对依赖及端口；修复后再次双击入口。')
                    if time.monotonic() >= deadline:
                        raise StartupError('网页服务', '90秒内未能连接本机服务。', '查看日志；检查本机防火墙、代理和运行环境。程序仅监听127.0.0.1。')
                    self.cancelled.wait(0.3)
                temporary = STATE.with_suffix('.tmp')
                temporary.write_text(json.dumps({'project': str(ROOT), 'pid': self.process.pid, 'port': port}), encoding='utf-8')
                temporary.replace(STATE)
            if not self.no_browser:
                self.notify('progress', '服务已就绪，正在打开默认浏览器…')
                if not webbrowser.open(self.url):
                    self.notify('browser_error', ('浏览器', '服务已启动，但默认浏览器未能打开。', '在系统设置中设置默认浏览器，然后点击“打开网页”重试。'))
            self.notify('ready', self.url)
        except InterruptedError:
            self.stop_child()
        except Exception as error:
            if self.log:
                traceback.print_exc(file=self.log)
                self.log.flush()
            self.stop_child()
            if isinstance(error, StartupError):
                payload = (error.stage, error.reason, error.solution)
            else:
                payload = ('启动检查', str(error), '确认项目目录可写，查看日志后修复并重试。')
            self.notify('error', payload)

    def stop_child(self):
        process = self.process
        if process is not None and process.poll() is None:
            manage.stop_process(process)
        if process is not None:
            try:
                if json.loads(STATE.read_text(encoding='utf-8')).get('pid') == process.pid:
                    STATE.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        self.process = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
        window = tk.Tk()
    except Exception as error:
        native_error('阶段：启动窗口\n缺少或无法加载Tk图形组件。\n'
                     '请使用含Tk的完整Python3.13/3.14安装；在Mac可运行python3 -m tkinter检查。\n'
                     f'具体错误：{error}')
        return 1
    window.title('财务经营分析工作台')
    window.geometry('610x310')
    window.minsize(560, 300)
    status = tk.StringVar(value='正在准备，请稍候…')
    address = tk.StringVar(value='自动启动后将打开默认浏览器')
    ttk.Label(window, text='财务经营分析工作台', font=('', 18, 'bold')).pack(pady=(24, 14))
    ttk.Label(window, textvariable=status, wraplength=540).pack(pady=5)
    progress = ttk.Progressbar(window, mode='indeterminate', length=490)
    progress.pack(pady=12)
    progress.start()
    ttk.Label(window, textvariable=address, wraplength=540).pack(pady=5)
    ttk.Label(window, text='保持这个窗口运行；关闭它会停止本窗口启动的服务。', wraplength=540).pack(pady=8)
    events = queue.Queue()
    controller = Controller(lambda kind, data: events.put((kind, data)), args.port, args.no_browser)
    buttons = ttk.Frame(window)
    buttons.pack(pady=8)

    def open_page():
        if controller.url and healthy(controller.url):
            if not webbrowser.open(controller.url):
                messagebox.showerror('浏览器未打开', '请在系统设置中设置默认浏览器，再点击“打开网页”。', parent=window)
        else:
            messagebox.showerror('服务未运行', '网页服务尚未就绪或已经退出，请关闭启动窗口后重新双击入口。', parent=window)

    def open_log():
        if controller.log:
            controller.log.flush()
        if controller.log_path.exists():
            if os.name == 'nt':
                os.startfile(controller.log_path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(controller.log_path)])

    open_button = ttk.Button(buttons, text='打开网页', command=open_page, state='disabled')
    open_button.pack(side='left', padx=7)
    ttk.Button(buttons, text='查看错误日志', command=open_log).pack(side='left', padx=7)

    def close():
        controller.cancelled.set()
        status.set('正在停止，请稍候…')
        # Worker owns the process while startup is underway; avoid races during installation.
        def finish():
            if worker.is_alive():
                controller.stop_child()
                window.after(200, finish)
            else:
                controller.stop_child()
                if controller.log:
                    controller.log.close()
                window.destroy()
        finish()

    ttk.Button(buttons, text='关闭程序', command=close).pack(side='left', padx=7)
    window.protocol('WM_DELETE_WINDOW', close)
    notified_exit = False

    def poll():
        nonlocal notified_exit
        while not events.empty():
            kind, data = events.get_nowait()
            if kind == 'progress':
                status.set(data)
            elif kind == 'ready':
                progress.stop()
                progress.configure(mode='determinate', value=100)
                status.set('程序已就绪，可以使用网页。')
                address.set(data)
                open_button.configure(state='normal')
            elif kind in ('error', 'browser_error'):
                progress.stop()
                stage, reason, solution = data
                status.set(f'未完成：{stage}')
                messagebox.showerror('财务分析：启动未完成',
                                     f'出错阶段：{stage}\n\n原因：{reason}\n\n处理方式：{solution}'
                                     f'\n\n错误日志：{controller.log_path}', parent=window)
        if controller.process is not None and not worker.is_alive() and controller.process.poll() is not None and not notified_exit:
            notified_exit = True
            status.set('网页服务已退出，请重新启动。')
            open_button.configure(state='disabled')
            messagebox.showerror('网页服务已退出', f'查看日志：{controller.log_path}\n关闭本窗口，再双击入口。', parent=window)
        if not controller.cancelled.is_set():
            window.after(200, poll)

    worker = threading.Thread(target=controller.launch, daemon=True)
    worker.start()
    window.after(100, poll)
    window.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
