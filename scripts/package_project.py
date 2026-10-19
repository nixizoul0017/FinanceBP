"""Versioned source archive, deterministic file manifest and explicit public inputs."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ('src', 'scripts', 'tests', 'sql', 'docs', 'data/demo', 'data/sample')
FILES = ('START.cmd','START.command','.gitattributes','scripts/manage.py','scripts/desktop_launcher.py','scripts/launch_windows.ps1','app.py','requirements.txt','requirements-desktop-lock.txt','README.md','CHANGELOG.md','VERSION','.gitignore',
         '.streamlit/config.toml','configs/demo_files.json','configs/demo_renamed_files.json',
         'configs/sample_files.json','configs/multidimensional_files.json','configs/demo_mysql.example.json',
         'configs/demo_renamed_mysql.example.json','configs/sample_mysql.example.json',
         'tests/fixtures/sample_sql_reference.json','tests/fixtures/monthly_reference.json',
         'tests/fixtures/report_reference.json','scripts/manage.ps1','scripts/setup_python.ps1',
         'scripts/run_stage7.ps1','scripts/run_stage11.ps1','scripts/stage11.py',
         'src/dashboard/theme.py','src/dashboard/cockpit.css')
SKIP_DIRS = {'__pycache__','node_modules','.venv','.git','outputs','dist'}


def release_files(root=ROOT):
    root = Path(root).resolve()
    selected = set()
    for value in DIRECTORIES:
        directory = root/value
        if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
            raise ValueError('Missing or linked release directory: '+value)
        for current, dirs, names in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS
                       and not (Path(current)/name).is_symlink() and not (Path(current)/name).is_junction()]
            for name in names:
                path=Path(current)/name
                if path.is_symlink() or name.endswith(('.pyc','.local.json','.log')) or name.startswith('.env') or name=='secrets.toml':
                    continue
                if not path.resolve().is_relative_to(root):
                    raise ValueError('Release file outside project')
                if path.is_file(): selected.add(path)
    for value in FILES:
        path=root/value
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or linked release file: '+value)
        selected.add(path)
    for path in selected:
        if path.parent==root/'configs':
            connection=json.loads(path.read_text(encoding='utf-8-sig')).get('source',{}).get('connection',{})
            if {'password','url'} & connection.keys():
                raise ValueError('Credentials must not be packaged')
    return sorted(selected)


def build(output=None, root=ROOT):
    root=Path(root).resolve()
    output=Path(output) if output else root/'dist'
    version=(root/'VERSION').read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?',version):
        raise ValueError('Invalid VERSION')
    output.mkdir(parents=True,exist_ok=True)
    files=release_files(root)
    contents={path.relative_to(root).as_posix():path.read_bytes() for path in files}
    rows=[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in contents.items()]
    manifest={'format':'finance_bp_source_release_v2','version':version,'runtime':'Windows / macOS / Python 3.13 or 3.14',
              'platform_validation':{'Windows':'本机运行通过','macOS':'入口已提供，实体Mac尚未验收'},
              'data_origin':'个人模拟数据','files':rows,'physical_other_computer_tested':False,
              'exclusions':['.venv','outputs','dist','credentials / local configuration','logs / caches / directory links']}
    archive=output/('FinanceBP-v'+version+'.zip')
    temporary=archive.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as book:
            entries={**contents,'release_manifest.json':json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')}
            for name,data in entries.items():
                info=zipfile.ZipInfo('FinanceBP/'+name,date_time=(2026,1,1,0,0,0))
                info.create_system=3
                info.external_attr=(0o100755 if name=='START.command' else 0o100644) << 16
                info.compress_type=zipfile.ZIP_DEFLATED
                book.writestr(info,data)
        with zipfile.ZipFile(temporary) as book:
            if book.testzip() is not None: raise ValueError('Archive integrity check failed')
            for row in rows:
                if hashlib.sha256(book.read('FinanceBP/'+row['path'])).hexdigest()!=row['sha256']:
                    raise ValueError('Archive member hash mismatch')
        os.replace(temporary,archive)
    finally:
        temporary.unlink(missing_ok=True)
    record={**manifest,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'archive_bytes':archive.stat().st_size,'archive_name':archive.name}
    evidence=root/'outputs/validation'
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'release_manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'RELEASE_READY: {len(rows)} files; {archive.stat().st_size} bytes; {archive}')
    return archive


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output')
    build(parser.parse_args().output)
