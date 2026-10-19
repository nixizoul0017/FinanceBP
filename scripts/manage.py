"""Portable project menu used by the macOS entry; also callable on Windows."""
from pathlib import Path
import argparse
import os
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import venv
import webbrowser
SUPPORTED_VERSIONS = {(3, 13), (3, 14)}

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def run(arguments):
    subprocess.run([str(value) for value in arguments], cwd=ROOT, check=True)


def install():
    if sys.version_info[:2] not in SUPPORTED_VERSIONS:
        raise RuntimeError('需要 Python 3.13或3.14，请用对应版本重新运行启动入口。')
    if not PYTHON.exists():
        if (ROOT / '.venv').exists():
            raise RuntimeError('现有.venv不适用于这台电脑。请将它移到项目外，再重新安装；换电脑只复制项目ZIP。')
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    run([PYTHON, '-c', 'import sys; assert sys.version_info[:2] in {(3,13),(3,14)}, "Python 3.13/3.14 required"'])
    run([PYTHON, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt'])


def ensure_environment():
    if not PYTHON.exists():
        print('首次使用：准备本机Python环境和依赖，需要可用的包源。', flush=True)
        install()
    run([PYTHON, '-c', 'import sys,streamlit,openpyxl,pandas,sqlalchemy,plotly; '
         'assert sys.version_info[:2] in {(3,13),(3,14)}, "Python 3.13/3.14 required"'])


def available_port(first):
    for port in range(first, min(first + 20, 65535) + 1):
        with socket.socket() as probe:
            try:
                probe.bind(('127.0.0.1', port))
            except OSError:
                continue
            return port
    raise RuntimeError('附近端口均被占用，请通过--port指定其他端口。')


def wait_ready(process, url, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('网页服务已退出，请查看上方错误。')
        try:
            with urlopen(url + '/_stcore/health', timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            pass
        time.sleep(0.3)
    raise RuntimeError('网页未在90秒内准备好，请查看上方提示并重新启动。')


def stop_process(process):
    """Windows venv redirectors have children: stop the owned process tree."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        try:
            stopped = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            if stopped.returncode != 0 and process.poll() is None:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            if process.poll() is None:
                process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def start(port, no_browser):
    port = available_port(port)
    url = f'http://127.0.0.1:{port}'
    print(f'项目位置：{ROOT}\n浏览器地址：{url}\n保持此窗口运行；结束时按Ctrl+C。', flush=True)
    process = subprocess.Popen([str(PYTHON), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
                               '--server.address=127.0.0.1', f'--server.port={port}',
                               '--server.headless=true', '--browser.gatherUsageStats=false'], cwd=ROOT)
    try:
        wait_ready(process, url)
        if not no_browser:
            if not webbrowser.open(url):
                print('浏览器未自动打开，请点击或复制上方地址。', flush=True)
        if process.wait() != 0:
            raise RuntimeError('网页服务异常退出，请查看上方提示。')
    finally:
        if process.poll() is None:
            stop_process(process)


def perform(action, port=8501, no_browser=False):
    if action == 'Install':
        install()
        return
    if action == 'Reports':
        directory = ROOT / 'outputs/reports'
        directory.mkdir(parents=True, exist_ok=True)
        print(directory)
        if not no_browser:
            if sys.platform == 'darwin':
                run(['open', directory])
            elif os.name == 'nt':
                os.startfile(directory)
            else:
                run(['xdg-open', directory])
        return
    ensure_environment()
    if action == 'Start':
        start(port, no_browser)
    elif action == 'Check':
        run([PYTHON, ROOT / 'scripts/check_project.py'])
        print('PROJECT_READY')
    elif action == 'Verify':
        run([PYTHON, ROOT / 'scripts/stage11.py'])
        print('验收结果：outputs/validation')
    elif action == 'Package':
        run([PYTHON, ROOT / 'scripts/check_project.py'])
        run([PYTHON, ROOT / 'scripts/package_project.py'])
        print('整体项目包已放入dist文件夹。')


def main():
    parser = argparse.ArgumentParser(description='财务经营分析工作台：安装、启动、验收、打包')
    parser.add_argument('--action', choices=['Menu', 'Start', 'Install', 'Check', 'Verify', 'Package', 'Reports'], default='Menu')
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口范围为1024至65535')
    os.environ['PYTHONUTF8'] = '1'
    try:
        if args.action != 'Menu':
            perform(args.action, args.port, args.no_browser)
            return 0
        choices = {'1': 'Start', '2': 'Install', '3': 'Verify', '4': 'Package', '5': 'Reports'}
        while True:
            print('\n===== 财务经营分析工作台 =====\n1  打开程序（首次使用自动准备环境）'
                  '\n2  安装/更新依赖\n3  运行整体验收（文件模式）\n4  生成完整项目ZIP'
                  '\n5  打开本地报告目录\n0  退出', flush=True)
            selection = input('请选择：').strip()
            if selection == '0':
                return 0
            if selection not in choices:
                print('请输入0至5。')
                continue
            try:
                perform(choices[selection], args.port, args.no_browser)
            except KeyboardInterrupt:
                print('\n程序已停止。')
            except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
                print(f'未完成：{error}\n依赖问题可选择2重新安装。')
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, subprocess.CalledProcessError, OSError, EOFError) as error:
        print(f'未完成：{error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
