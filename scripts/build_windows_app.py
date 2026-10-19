"""Build the Windows 11 x64 application with a dedicated, locked Python 3.13 env."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'outputs/desktop_build'


def build(skip_freeze=False,incremental=False):
    if sys.platform!='win32' or sys.version_info[:2]!=(3,13) or platform.machine().upper() not in ('AMD64','X86_64'):
        raise RuntimeError('Build requires Windows x64 and Python 3.13')
    version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
    from package_project import release_files
    public=release_files()
    resources=BUILD/'resources'
    resources.mkdir(parents=True,exist_ok=True)
    datas=[]
    include={'app.py','VERSION','.streamlit/config.toml','docs/assets/financebp.ico','docs/USER_GUIDE.md','docs/WINDOWS_APP.md',
             'tests/fixtures/report_reference.json'}
    for path in public:
        name=path.relative_to(ROOT).as_posix()
        if name in include or name.startswith(('src/','data/demo/','data/sample/','configs/')):
            datas.append((str(path),str(Path('resources')/Path(name).parent)))
    licenses=resources/'third_party'
    licenses.mkdir(exist_ok=True)
    packages=[]
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata['Name']
        packages.append({'name':name,'version':distribution.version,'license':distribution.metadata.get('License-Expression') or distribution.metadata.get('License','See license files')})
        for file in distribution.files or []:
            if '/licenses/' in str(file).lower() or Path(str(file)).name.lower().startswith(('license','copying','notice')):
                source=Path(distribution.locate_file(file))
                if source.is_file():
                    target=licenses/name/Path(str(file)).name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(source.read_bytes())
    (licenses/'packages.json').write_text(json.dumps(packages,ensure_ascii=False,indent=2),encoding='utf-8')
    python_license=Path(sys._base_executable).parent/'LICENSE.txt'
    if python_license.is_file(): (licenses/'Python-LICENSE.txt').write_bytes(python_license.read_bytes())
    datas.append((str(licenses),'resources/third_party'))
    import PyInstaller.__main__
    from PyInstaller.utils.hooks import collect_submodules
    hidden=[]
    sys.path.insert(0,str(ROOT/'src'))
    for package in ('analysis','dashboard','desktop','etl','finance','reporting','uvicorn','starlette','anyio'):
        hidden.extend(collect_submodules(package))
    # app.py is executed by Streamlit from bundled source, not imported by the entry.
    args=[str(ROOT/'scripts/windows_app.py'),'--name=FinanceBP','--onedir','--windowed','--noconfirm',
          '--icon='+str(ROOT/'docs/assets/financebp.ico'),'--paths='+str(ROOT/'src'),
          '--distpath='+str(ROOT/'dist/windows'),'--workpath='+str(BUILD/'work'),'--specpath='+str(BUILD),
          '--exclude-module=pytest','--exclude-module=tkinter','--exclude-module=matplotlib',
          '--exclude-module=PyQt5','--exclude-module=PyQt6','--exclude-module=PySide6']
    if not incremental: args.append('--clean')
    for source,target in datas: args+=['--add-data',source+':'+target]
    for name in sorted(set(hidden)): args+=['--hidden-import='+name]
    for package in ('streamlit','webview','pythonnet','clr_loader','plotly'):
        args+=['--collect-all='+package]
    for package in ('pyinstaller','pandas','numpy','openpyxl','PyMySQL','pywebview','streamlit','altair','jsonschema','referencing','uvicorn','starlette','anyio'):
        args+=['--copy-metadata='+package]
    if not skip_freeze: PyInstaller.__main__.run(args)
    executable=ROOT/'dist/windows/FinanceBP/FinanceBP.exe'
    if not executable.is_file(): raise RuntimeError('Frozen executable missing')
    compiler=BUILD/'tools/InnoSetup/ISCC.exe'
    runtime=BUILD/'tools/MicrosoftEdgeWebView2RuntimeInstallerX64.exe'
    if not compiler.is_file() or not runtime.is_file(): raise RuntimeError('Inno Setup compiler or offline WebView2 installer missing')
    subprocess.run([str(compiler),'/DAppVersion='+version,'/DProjectRoot='+str(ROOT),str(ROOT/'scripts/windows_installer.iss')],check=True)
    setup=ROOT/'dist'/f'FinanceBP-{version}-windows-x64-setup.exe'
    digest=hashlib.sha256(setup.read_bytes()).hexdigest()
    (setup.parent/(setup.name+'.sha256')).write_text(digest+'  '+setup.name+'\n',encoding='utf-8')
    record={'version':version,'python':platform.python_version(),'setup':setup.name,'bytes':setup.stat().st_size,'sha256':digest,
            'signed':False,'clean_windows_vm_tested':False,'packages':packages,
            'offline_webview2_sha256':hashlib.sha256(runtime.read_bytes()).hexdigest()}
    (BUILD/'build-manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print('INSTALLER_READY:',setup)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--skip-freeze',action='store_true')
    parser.add_argument('--incremental',action='store_true')
    options=parser.parse_args()
    build(options.skip_freeze,options.incremental)
