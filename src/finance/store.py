"""Transactional, source-isolated local budgets, month confirmations and actions."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from analysis.forecast_store import content_digest
from etl.common import encode

from desktop.paths import AppPaths
STORE_PATH=AppPaths.current().runtime/'finance_workspace.sqlite3'


class WorkspaceError(ValueError):
    pass


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def dumps(value):
    return json.dumps(value,default=encode,ensure_ascii=False,sort_keys=True,allow_nan=False)


def text(value,label,max_length=200):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>max_length:
        raise WorkspaceError(f'{label}请输入1—{max_length}个字符')
    return value.strip()


SCHEMA='''
CREATE TABLE budgets(id TEXT PRIMARY KEY, context TEXT NOT NULL, name TEXT NOT NULL,
 kind TEXT NOT NULL, parent_id TEXT, status TEXT NOT NULL, dataset TEXT NOT NULL,
 digest TEXT NOT NULL, revision INTEGER NOT NULL, creator TEXT NOT NULL,
 approver TEXT, note TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(context,name));
CREATE TABLE controls(context TEXT NOT NULL, month TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(context,month));
CREATE TABLE closes(id TEXT PRIMARY KEY,context TEXT NOT NULL,month TEXT NOT NULL,
 revision INTEGER NOT NULL,snapshot TEXT NOT NULL,digest TEXT NOT NULL,actor TEXT NOT NULL,
 note TEXT NOT NULL,created_at TEXT NOT NULL,released_at TEXT,release_actor TEXT,release_reason TEXT);
CREATE UNIQUE INDEX active_close ON closes(context,month) WHERE released_at IS NULL;
CREATE TABLE issues(id TEXT PRIMARY KEY,context TEXT NOT NULL,month TEXT NOT NULL,
 facts TEXT NOT NULL,notes TEXT NOT NULL,status TEXT NOT NULL,revision INTEGER NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,seen_at TEXT NOT NULL);
CREATE TABLE settings(context TEXT PRIMARY KEY,payload TEXT NOT NULL);
CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,context TEXT NOT NULL,
 object_type TEXT NOT NULL,object_id TEXT NOT NULL,action TEXT NOT NULL,actor TEXT NOT NULL,
 note TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL);
PRAGMA user_version=1;
'''


class WorkspaceStore:
    def __init__(self,path=None):
        self.path=Path(path or STORE_PATH)

    @contextmanager
    def connection(self,write=False):
        connection=None
        try:
            if not write and not self.path.exists():
                yield None
                return
            if write:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                connection=sqlite3.connect(self.path,timeout=8)
            else:
                connection=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=8)
            connection.row_factory=sqlite3.Row
            version=connection.execute('PRAGMA user_version').fetchone()[0]
            if version==0 and write:
                connection.executescript(SCHEMA.replace('CREATE TABLE ','CREATE TABLE IF NOT EXISTS ').replace('CREATE UNIQUE INDEX ','CREATE UNIQUE INDEX IF NOT EXISTS '))
            elif version!=1:
                raise WorkspaceError('本机财务工作区版本不受支持，请保留原文件并核对程序版本')
            if write:
                connection.execute('BEGIN IMMEDIATE')
            yield connection
            if write:
                connection.commit()
        except (sqlite3.DatabaseError,OSError) as error:
            if connection:
                connection.rollback()
            raise WorkspaceError('本机财务工作区暂时无法读写，请核对目录权限或数据库文件；来源数据未修改') from error
        finally:
            if connection:
                connection.close()

    def _read(self,sql,args=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql,args)] if db else []

    @staticmethod
    def _audit(db,context,kind,identity,action,actor,note,payload):
        db.execute('INSERT INTO audit(context,object_type,object_id,action,actor,note,at,payload) VALUES(?,?,?,?,?,?,?,?)',
                   (context,kind,identity,action,actor,note,now(),dumps(payload)))

    @staticmethod
    def _budget(row):
        return {**dict(row),'dataset':json.loads(row['dataset'])} if row else None

    def budgets(self,context,published_only=False):
        sql='SELECT * FROM budgets WHERE context=?'+(" AND status='published'" if published_only else '')+' ORDER BY created_at,id'
        return [self._budget(row) for row in self._read(sql,(context,))]

    def budget(self,context,identity):
        rows=self._read('SELECT * FROM budgets WHERE context=? AND id=?',(context,identity))
        return self._budget(rows[0]) if rows else None

    def save_budget(self,context,name,kind,dataset,actor,note='',*,identity=None,expected_revision=None,parent_id=None):
        from .budgets import validate_dataset
        dataset=validate_dataset(dataset)
        name=text(name,'预算名称',60)
        actor=text(actor,'编制人',60)
        if kind not in ('original','adjustment'):
            raise WorkspaceError('预算类型无效')
        digest=content_digest(dataset)
        with self.connection(True) as db:
            if db.execute('SELECT id FROM budgets WHERE context=? AND name=? AND id!=?',(context,name,identity or '')).fetchone():
                raise WorkspaceError('同一企业的预算名称已存在')
            if parent_id:
                parent=db.execute("SELECT * FROM budgets WHERE context=? AND id=? AND status='published'",(context,parent_id)).fetchone()
                if not parent:
                    raise WorkspaceError('调整预算必须关联本接入配置中已发布的原版本')
                parent_data=json.loads(parent['dataset'])
                if parent_data['year']!=dataset['year'] or parent_data['entity_id']!=dataset['entity_id']:
                    raise WorkspaceError('调整预算的企业和年度必须与所依据版本一致')
            if kind=='adjustment' and not parent_id:
                raise WorkspaceError('请选择调整所依据的已发布版本')
            timestamp=now()
            if identity:
                old=db.execute('SELECT * FROM budgets WHERE context=? AND id=?',(context,identity)).fetchone()
                if not old or old['status']!='draft':
                    raise WorkspaceError('只能修改草稿，已发布预算保持锁定')
                if expected_revision!=old['revision']:
                    raise WorkspaceError('草稿已被更新，请刷新后再保存')
                if kind!=old['kind'] or parent_id!=old['parent_id']:
                    raise WorkspaceError('替换草稿时不能更改预算类型或原版本')
                db.execute('UPDATE budgets SET name=?,dataset=?,digest=?,revision=revision+1,creator=?,note=?,updated_at=? WHERE id=?',
                           (name,dumps(dataset),digest,actor,note,timestamp,identity))
                action='replace_draft'
            else:
                identity='LOCAL_'+uuid.uuid4().hex[:16]
                db.execute('INSERT INTO budgets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (identity,context,name,kind,parent_id,'draft',dumps(dataset),digest,1,actor,None,note,timestamp,timestamp))
                action='create_draft'
            self._audit(db,context,'budget',identity,action,actor,note,{'digest':digest,'name':name,'kind':kind,'parent_id':parent_id})
        return self.budget(context,identity)

    def publish_budget(self,context,identity,actor,note,expected_revision):
        actor=text(actor,'确认人',60)
        note=text(note,'发布说明',2000)
        with self.connection(True) as db:
            old=db.execute('SELECT * FROM budgets WHERE context=? AND id=?',(context,identity)).fetchone()
            if not old or old['status']!='draft' or expected_revision!=old['revision']:
                raise WorkspaceError('草稿状态或版本已变化，请刷新后核对')
            from .budgets import validate_dataset
            validate_dataset(json.loads(old['dataset']))
            db.execute("UPDATE budgets SET status='published',approver=?,note=?,updated_at=?,revision=revision+1 WHERE id=?",(actor,note,now(),identity))
            self._audit(db,context,'budget',identity,'publish',actor,note,{'digest':old['digest'],'kind':old['kind']})
        return self.budget(context,identity)

    def controls(self,context,month):
        rows=self._read('SELECT payload FROM controls WHERE context=? AND month=?',(context,str(month)[:7]))
        return json.loads(rows[0]['payload']) if rows else None

    def save_controls(self,context,month,amounts,actor,source):
        from .reconciliation import CONTROL_FIELDS, control_amount
        from analysis.metrics import month_date
        month=month_date(month).strftime('%Y-%m')
        actor=text(actor,'核对人',60)
        source=text(source,'独立参考来源',1000)
        if set(amounts)-set(CONTROL_FIELDS):
            raise WorkspaceError('不支持的对账指标')
        values={field:control_amount(amounts.get(field)) for field in CONTROL_FIELDS}
        payload={'amounts':values,'actor':actor,'source':source,'updated_at':now()}
        with self.connection(True) as db:
            db.execute('INSERT OR REPLACE INTO controls VALUES(?,?,?)',(context,month,dumps(payload)))
            self._audit(db,context,'controls',month,'save',actor,source,payload)
        return payload

    def closes(self,context,month=None):
        rows=self._read('SELECT * FROM closes WHERE context=?'+(' AND month=?' if month else '')+' ORDER BY month,revision,id',
                        (context,str(month)[:7]) if month else (context,))
        return [{**row,'snapshot':json.loads(row['snapshot'])} for row in rows]

    def confirm_month(self,context,engine,month,actor,note):
        from .reconciliation import reconciliation, month_snapshot
        month=str(month)[:7]
        actor=text(actor,'确认人',60)
        note=text(note,'确认说明',2000)
        with self.connection(True) as db:
            row=db.execute('SELECT payload FROM controls WHERE context=? AND month=?',(context,month)).fetchone()
            controls=json.loads(row['payload']) if row else None
            checked=reconciliation(engine,month,controls)
            if not checked['can_confirm']:
                raise WorkspaceError('月份尚不能确认：'+'；'.join(checked['blockers']))
            if db.execute('SELECT id FROM closes WHERE context=? AND month=? AND released_at IS NULL',(context,month)).fetchone():
                raise WorkspaceError('该月已有有效确认，需先解除原确认并说明原因')
            snapshot=month_snapshot(engine,month)
            snapshot['reconciliation']=checked
            identity=uuid.uuid4().hex
            revision=db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM closes WHERE context=? AND month=?',(context,month)).fetchone()[0]
            db.execute('INSERT INTO closes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (identity,context,month,revision,dumps(snapshot),snapshot['actual_hash'],actor,note,now(),None,None,None))
            self._audit(db,context,'month',identity,'confirm',actor,note,{'month':month,'revision':revision,'actual_hash':snapshot['actual_hash']})
        return identity

    def release_month(self,context,identity,actor,reason):
        actor=text(actor,'解除确认人',60)
        reason=text(reason,'解除原因',2000)
        with self.connection(True) as db:
            old=db.execute('SELECT * FROM closes WHERE context=? AND id=? AND released_at IS NULL',(context,identity)).fetchone()
            if not old:
                raise WorkspaceError('原确认已解除或不存在')
            db.execute('UPDATE closes SET released_at=?,release_actor=?,release_reason=? WHERE id=?',(now(),actor,reason,identity))
            self._audit(db,context,'month',identity,'release',actor,reason,{'month':old['month'],'revision':old['revision']})

    def settings(self,context):
        rows=self._read('SELECT payload FROM settings WHERE context=?',(context,))
        return json.loads(rows[0]['payload']) if rows else {}

    def save_settings(self,context,payload,actor):
        from .issues import validate_thresholds
        validated=validate_thresholds(payload)
        actor=text(actor,'设置人',60)
        with self.connection(True) as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(context,dumps(validated)))
            self._audit(db,context,'settings',context,'save',actor,'更新异常阈值',validated)

    def issues(self,context,month=None):
        rows=self._read('SELECT * FROM issues WHERE context=?'+(' AND month=?' if month else '')+' ORDER BY created_at,id',
                        (context,str(month)[:7]) if month else (context,))
        return [{**row,'facts':json.loads(row['facts']),'notes':json.loads(row['notes'])} for row in rows]

    def scan_issues(self,context,month,candidates,actor,scan_key='company'):
        actor=text(actor,'扫描人',60)
        month=str(month)[:7]
        timestamp=now()
        ids=set()
        with self.connection(True) as db:
            for item in candidates:
                if item['month']!=month:
                    raise WorkspaceError('异常期间与扫描月份不一致')
                identity=content_digest({'context':context,'month':month,'key':item['key']})[:32]
                ids.add(identity)
                facts={**deepcopy(item),'scan_key':scan_key,'currently_detected':True}
                old=db.execute('SELECT * FROM issues WHERE context=? AND id=?',(context,identity)).fetchone()
                if old:
                    if json.loads(old['facts'])!=json.loads(dumps(facts)):
                        db.execute('UPDATE issues SET facts=?,revision=revision+1,updated_at=?,seen_at=? WHERE id=?',(dumps(facts),timestamp,timestamp,identity))
                        self._audit(db,context,'issue',identity,'refresh_facts',actor,'系统事实更新',{'before':json.loads(old['facts']),'after':facts})
                    else:
                        db.execute('UPDATE issues SET seen_at=? WHERE id=?',(timestamp,identity))
                else:
                    db.execute('INSERT INTO issues VALUES(?,?,?,?,?,?,?,?,?,?)',(identity,context,month,dumps(facts),'{}','open',1,timestamp,timestamp,timestamp))
                    self._audit(db,context,'issue',identity,'detect',actor,'系统识别',facts)
            for old in db.execute('SELECT * FROM issues WHERE context=? AND month=?',(context,month)).fetchall():
                facts=json.loads(old['facts'])
                if old['id'] not in ids and facts.get('currently_detected') and facts.get('scan_key','company')==scan_key:
                    facts['currently_detected']=False
                    db.execute('UPDATE issues SET facts=?,revision=revision+1,updated_at=? WHERE id=?',(dumps(facts),timestamp,old['id']))
                    self._audit(db,context,'issue',old['id'],'no_longer_detected',actor,'本次未再触发，原跟进状态保留',facts)

    def update_issue(self,context,identity,notes,status,actor,expected_revision):
        from .issues import validate_notes
        notes=validate_notes(notes,status)
        actor=text(actor,'记录人',60)
        with self.connection(True) as db:
            old=db.execute('SELECT * FROM issues WHERE context=? AND id=?',(context,identity)).fetchone()
            if not old or old['revision']!=expected_revision:
                raise WorkspaceError('异常记录已变化，请刷新后再保存')
            db.execute('UPDATE issues SET notes=?,status=?,revision=revision+1,updated_at=? WHERE id=?',(dumps(notes),status,now(),identity))
            self._audit(db,context,'issue',identity,'update_action',actor,notes.get('resolution') or notes.get('action',''),
                        {'before':{'status':old['status'],'notes':json.loads(old['notes'])},'after':{'status':status,'notes':notes}})

    def audit(self,context,limit=200):
        rows=self._read('SELECT * FROM audit WHERE context=? ORDER BY seq DESC LIMIT ?',(context,min(max(int(limit),1),10000)))
        return [{**row,'payload':json.loads(row['payload'])} for row in rows]
