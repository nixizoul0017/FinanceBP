"""Versioned backups and non-destructive legacy import of owned personal records."""
from contextlib import contextmanager,closing
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile
import uuid

from .events import atomic_json

FIXED={'runtime/finance_workspace.sqlite3','runtime/dimension_views.json','runtime/ui_preferences.json'}
TABLES=('budgets','controls','closes','issues','settings','audit')


def allowed(name):
    p=Path(name)
    return (not p.is_absolute() and '..' not in p.parts and
            (p.as_posix() in FIXED or (len(p.parts)==3 and p.parts[:2]==('forecasts','runs') and p.name.startswith('FC9_') and p.suffix=='.json')
             or (len(p.parts)==2 and p.parts[0]=='profiles' and p.suffix=='.json')))


def safe_target(root,name):
    if not allowed(name): raise ValueError('备份包含不支持的数据路径')
    root=Path(root).resolve()
    path=root/name
    if not path.resolve().is_relative_to(root): raise ValueError('数据路径超出个人目录')
    for part in (path,*path.parents):
        if part==root.parent: break
        if part.is_symlink() or part.is_junction(): raise ValueError('个人数据目录不能使用目录链接')
    return path


def validate_file(path,name):
    path=Path(path)
    if name.endswith('.sqlite3'):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0]!=1 or db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('财务工作区版本或完整性检查失败')
            if not set(TABLES).issubset({x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}):
                raise ValueError('财务工作区缺少必要数据表')
    else:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict): raise ValueError('个人配置格式无效')
        if name.endswith('dimension_views.json') and (data.get('version')!=1 or not isinstance(data.get('contexts'),dict)):
            raise ValueError('分类方案版本不受支持')
        if name.endswith('ui_preferences.json') and (data.get('version')!=1 or data.get('theme') not in ('navy','teal','plum')):
            raise ValueError('显示偏好版本不受支持')
        if name.startswith('profiles/'):
            conn=data.get('source',{}).get('connection',{})
            if any(key in conn for key in ('password','url')): raise ValueError('配置含口令或连接URL，请移除后重新导入')
        if name.startswith('forecasts/'):
            from analysis.forecast_store import load_forecast
            load_forecast(path)


@contextmanager
def workspace_lock(root):
    folder=Path(root)/'runtime'
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'workspace-maintenance.lock').open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
            try: msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError: raise ValueError('另一个备份或导入正在进行，请稍后再试')
        try: yield
        finally:
            if os.name=='nt':
                stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def files(root):
    root=Path(root)
    paths=[root/name for name in FIXED]
    for directory,pattern in (('forecasts/runs','FC9_*.json'),('profiles','*.json')):
        paths.extend((root/directory).glob(pattern))
    return [p for p in paths if p.is_file() and allowed(p.relative_to(root).as_posix())]


def backup(root,destination):
    root,destination=Path(root),Path(destination)
    if not destination.suffix: destination=destination.with_suffix('.zip')
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.resolve() in {p.resolve() for p in files(root)}: raise ValueError('备份不能覆盖个人数据文件')
    temporary=destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tempfile.TemporaryDirectory() as staging,zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            rows=[]
            for source in files(root):
                name=source.relative_to(root).as_posix()
                safe_target(root,name)
                validate_file(source,name)
                if source.suffix=='.sqlite3':
                    snapshot=Path(staging)/'snapshot.sqlite3'
                    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(snapshot)) as dst:
                        src.backup(dst)
                    data=snapshot.read_bytes()
                else: data=source.read_bytes()
                archive.writestr('data/'+name,data)
                rows.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            archive.writestr('manifest.json',json.dumps({'format':'financebp_backup_v1','version':1,'created_at':datetime.now().isoformat(),'files':rows},ensure_ascii=False))
        os.replace(temporary,destination)
    finally: temporary.unlink(missing_ok=True)
    return len(rows)


def automatic_backup(root):
    path=Path(root)/'backups'/('恢复前_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.zip')
    backup(root,path)
    return path


def _replace_files(root,staging,names):
    # Backups remain available even if replacing a file fails partway through.
    automatic_backup(root)
    originals={}
    try:
        for name in names:
            target=safe_target(root,name)
            originals[name]=target.read_bytes() if target.exists() else None
            target.parent.mkdir(parents=True,exist_ok=True)
            pending=target.with_name('.'+target.name+'.restore-tmp')
            try:
                shutil.copyfile(Path(staging)/name,pending)
                os.replace(pending,target)
            finally: pending.unlink(missing_ok=True)
    except Exception:
        for name,data in originals.items():
            target=safe_target(root,name)
            if data is None: target.unlink(missing_ok=True)
            else: target.write_bytes(data)
        raise


def restore(root,source):
    with workspace_lock(root),tempfile.TemporaryDirectory() as staging,zipfile.ZipFile(source) as archive:
        if len(archive.namelist())!=len(set(archive.namelist())): raise ValueError('备份成员重复')
        if len(archive.infolist())>20001 or sum(x.file_size for x in archive.infolist())>1024**3:
            raise ValueError('备份超过支持的大小')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='financebp_backup_v1' or manifest.get('version')!=1:
            raise ValueError('备份版本不受支持')
        names=[]
        for item in manifest['files']:
            name=item['path']
            target=safe_target(staging,name)
            if name in names: raise ValueError('备份路径重复')
            data=archive.read('data/'+name)
            if len(data)>250*1024*1024 or len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
                raise ValueError('备份内容校验失败')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            validate_file(target,name)
            names.append(name)
        if set(archive.namelist())!={'manifest.json',*['data/'+name for name in names]}:
            raise ValueError('备份包含未声明文件')
        _replace_files(root,staging,names)
    return len(names)


def _merge_json(old,current):
    if isinstance(old,dict) and isinstance(current,dict):
        return {**old,**{key:_merge_json(old.get(key),value) for key,value in current.items()}}
    if isinstance(old,list) and isinstance(current,list) and all(isinstance(x,dict) and 'id' in x for x in old+current):
        ids={x['id'] for x in current};names={x.get('name') for x in current}
        return current+[x for x in old if x['id'] not in ids and x.get('name') not in names]
    return current


def _merge_database(old,current,target):
    shutil.copyfile(current,target)
    with closing(sqlite3.connect(target)) as dst,closing(sqlite3.connect(Path(old).resolve().as_uri()+'?mode=ro',uri=True)) as src:
        for table in TABLES:
            cols=[x[1] for x in src.execute('PRAGMA table_info('+table+')')]
            if cols!=[x[1] for x in dst.execute('PRAGMA table_info('+table+')')]: raise ValueError('旧工作区结构不兼容')
            if table=='audit':
                cols=cols[1:]
            fields=','.join(cols)
            for row in src.execute('SELECT '+fields+' FROM '+table):
                if table=='budgets':
                    record=dict(zip(cols,row))
                    if record['parent_id'] and not dst.execute('SELECT 1 FROM budgets WHERE id=? AND context=?',(record['parent_id'],record['context'])).fetchone():
                        # Never import an adjustment whose original budget was skipped.
                        continue
                if table=='audit' and dst.execute('SELECT 1 FROM audit WHERE '+' AND '.join(x+' IS ?' for x in cols),row).fetchone():
                    continue
                dst.execute('INSERT OR IGNORE INTO '+table+' ('+fields+') VALUES ('+','.join('?' for _ in cols)+')',row)
        dst.commit()


def rebase_profile(profile,project):
    """Keep stable source IDs; only resolve external file references."""
    from copy import deepcopy
    result=deepcopy(profile)
    for table in result.get('tables',{}).values():
        if 'files' in table:
            table['files']=[str((Path(project)/name).resolve()) if not Path(name).is_absolute() else name for name in table['files']]
    return result


def import_legacy(root,project):
    root,project=Path(root),Path(project).resolve()
    old=project/'outputs'
    if not old.is_dir(): raise ValueError('请选择旧项目根目录，其中应有outputs文件夹')
    if old.resolve()==root.resolve(): raise ValueError('不能把当前个人目录作为旧项目导入')
    with workspace_lock(root),tempfile.TemporaryDirectory() as staging:
        names=[]
        for source in files(old):
            name=source.relative_to(old).as_posix()
            safe_target(old,name);validate_file(source,name)
            target=safe_target(staging,name);target.parent.mkdir(parents=True,exist_ok=True)
            incoming=None
            if name.endswith('dimension_views.json'):
                incoming=json.loads(source.read_text(encoding='utf-8'))
                for context in incoming['contexts'].values():
                    if isinstance(context,dict) and 'mapping' in context:
                        context['mapping']=rebase_profile(context['mapping'],project)
            elif name.startswith('profiles/'):
                incoming=rebase_profile(json.loads(source.read_text(encoding='utf-8')),project)
            current=safe_target(root,name)
            if current.exists():
                validate_file(current,name)
                if name.endswith('.sqlite3'): _merge_database(source,current,target)
                elif name.endswith('dimension_views.json'):
                    atomic_json(target,_merge_json(incoming,json.loads(current.read_text(encoding='utf-8'))))
                else: continue
            elif incoming is not None: atomic_json(target,incoming)
            else: shutil.copyfile(source,target)
            names.append(name)
        if not names: return 0
        _replace_files(root,staging,names)
    return len(names)
