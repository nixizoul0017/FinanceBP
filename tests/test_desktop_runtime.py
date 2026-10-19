"""Desktop data safety, file dialog queues and owned process contracts."""
from contextlib import closing
from copy import deepcopy
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from desktop.paths import AppPaths
from desktop.events import atomic_json
from desktop.artifacts import submit,read_request,save_request,finish_request,safe_name
from desktop.workspace import backup,restore,import_legacy,allowed,safe_target,rebase_profile
from desktop.controller import SingleInstance,Backend
from finance.store import WorkspaceStore


class DesktopRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def preference(self,root,theme='teal'):
        atomic_json(root/'runtime/ui_preferences.json',{'version':1,'theme':theme})

    def test_source_and_desktop_paths_are_separate(self):
        with patch.dict(os.environ,{'FINANCEBP_DESKTOP':'0','FINANCEBP_DATA_DIR':'','FINANCEBP_RESOURCES_DIR':''}):
            self.assertEqual(AppPaths.current().data,ROOT/'outputs')
        with patch.dict(os.environ,{'FINANCEBP_DESKTOP':'1','LOCALAPPDATA':str(self.root),'FINANCEBP_DATA_DIR':'','FINANCEBP_RESOURCES_DIR':''}):
            paths=AppPaths.current();paths.ensure()
            self.assertEqual(paths.data,self.root/'FinanceBP')
            self.assertTrue(paths.forecasts.is_dir())

    def test_frozen_paths_and_custom_data_directory(self):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(self.root/'internal'),create=True),patch.dict(os.environ,{'FINANCEBP_RESOURCES_DIR':'','FINANCEBP_DATA_DIR':str(self.root/'data')}):
            self.assertEqual(AppPaths.current().resources,self.root/'internal/resources')
            self.assertEqual(AppPaths.current().data,self.root/'data')

    def test_export_unicode_and_atomic_overwrite(self):
        target=self.root/'结果.csv';target.write_text('old')
        job=submit(BytesIO('销售员,净收入\n张三,4300'.encode()),'结果.csv',folder=self.root)
        request=self.root/'exports'/(job+'.json')
        self.assertEqual(read_request(request)[0]['name'],'结果.csv')
        save_request(request,target)
        self.assertIn('4300',target.read_text(encoding='utf-8'))
        self.assertFalse(request.exists())
        self.assertEqual(json.loads(request.with_suffix('.result').read_text())['state'],'saved')

    def test_export_hash_tampering_rejected(self):
        job=submit(b'original','测试.json',folder=self.root)
        request=self.root/'exports'/(job+'.json');request.with_suffix('.bin').write_bytes(b'tampered')
        with self.assertRaises(ValueError): save_request(request,self.root/'bad.json')
        self.assertFalse((self.root/'bad.json').exists())

    def test_export_cancel_discards_queued_content(self):
        job=submit('private','秘密.md',folder=self.root)
        request=self.root/'exports'/(job+'.json')
        finish_request(request,'cancelled')
        self.assertFalse(request.exists());self.assertFalse(request.with_suffix('.bin').exists())

    def test_native_save_retains_the_file_type_when_name_has_no_extension(self):
        job=submit(b'workbook','预算.xlsx',folder=self.root)
        saved=save_request(self.root/'exports'/(job+'.json'),self.root/'中文预算')
        self.assertEqual(saved.name,'中文预算.xlsx')
        self.assertEqual(saved.read_bytes(),b'workbook')

    def test_backend_launch_failure_can_be_retried(self):
        from desktop.host import Host
        host=Host(AppPaths(ROOT,self.root),ROOT/'scripts/windows_app.py',None)
        host.window=MagicMock()
        with patch.object(host.backend,'start',side_effect=OSError('test launch failure')):
            host.restart()
        self.assertTrue(host.failed)
        self.assertIn('无法启动本机分析进程',host.window.load_html.call_args.args[0])
        with patch.object(host.backend,'start') as start:
            host.restart()
        self.assertFalse(host.failed);self.assertFalse(host.loaded);start.assert_called_once()

    def test_export_failure_keeps_destination(self):
        job=submit(b'new','file.json',folder=self.root)
        request=self.root/'exports'/(job+'.json');destination=self.root/'file.json';destination.write_bytes(b'old')
        with patch('desktop.artifacts.os.replace',side_effect=PermissionError):
            with self.assertRaises(PermissionError): save_request(request,destination)
        self.assertEqual(destination.read_bytes(),b'old');self.assertTrue(request.exists())
        self.assertFalse(list(self.root.glob('*.tmp')))

    def test_export_names_and_size(self):
        self.assertEqual(safe_name('../CON.json'),'_CON.json')
        self.assertEqual(safe_name('CON.json'),'FinanceBP_CON.json')
        self.assertNotIn('/',safe_name('部门/结果.csv'))
        with patch('desktop.artifacts.MAX_BYTES',2):
            with self.assertRaises(ValueError): submit(b'123','x.json',folder=self.root)

    def test_backup_restore_and_pre_restore_snapshot(self):
        source=self.root/'source';target=self.root/'target';self.preference(source,'teal');self.preference(target,'navy')
        archive=self.root/'backup.zip';self.assertEqual(backup(source,archive),1)
        self.assertEqual(restore(target,archive),1)
        self.assertEqual(json.loads((target/'runtime/ui_preferences.json').read_text())['theme'],'teal')
        previous=next((target/'backups').glob('*.zip'))
        with zipfile.ZipFile(previous) as book:
            self.assertEqual(json.loads(book.read('data/runtime/ui_preferences.json'))['theme'],'navy')

    def test_backup_sqlite_snapshot_closed_and_readable(self):
        root=self.root/'source';store=WorkspaceStore(root/'runtime/finance_workspace.sqlite3')
        with store.connection(True) as db: db.execute('INSERT INTO settings VALUES (?,?)',('ctx','{"a":1}'))
        archive=self.root/'backup.zip';backup(root,archive)
        restored=self.root/'restored';restore(restored,archive)
        with closing(sqlite3.connect(restored/'runtime/finance_workspace.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT payload FROM settings').fetchone()[0],'{"a":1}')
        (root/'runtime/finance_workspace.sqlite3').unlink()  # Detect leaked Windows handles.

    def test_backup_excludes_passwords_logs_and_source_data(self):
        self.preference(self.root)
        atomic_json(self.root/'runtime/passwords.json',{'password':'do-not-export'})
        (self.root/'logs').mkdir();(self.root/'logs/error.log').write_text('private')
        archive=self.root/'backup.zip';backup(self.root,archive)
        with zipfile.ZipFile(archive) as book:
            self.assertEqual(set(book.namelist()),{'manifest.json','data/runtime/ui_preferences.json'})

    def test_restore_corruption_preserves_current_data(self):
        source=self.root/'source';target=self.root/'target';self.preference(source);self.preference(target,'plum')
        archive=self.root/'backup.zip';backup(source,archive)
        with zipfile.ZipFile(archive) as book: contents={n:book.read(n) for n in book.namelist()}
        contents['data/runtime/ui_preferences.json']=b'{}'
        with zipfile.ZipFile(archive,'w') as book:
            for name,data in contents.items(): book.writestr(name,data)
        with self.assertRaises(ValueError): restore(target,archive)
        self.assertEqual(json.loads((target/'runtime/ui_preferences.json').read_text())['theme'],'plum')

    def test_restore_traversal_and_duplicate_paths_rejected(self):
        self.assertFalse(allowed('../outside.json'));self.assertFalse(allowed('C:/outside.json'))
        with self.assertRaises(ValueError): safe_target(self.root,'../outside.json')
        archive=self.root/'duplicate.zip'
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(archive,'w') as book:
                book.writestr('manifest.json','{}');book.writestr('manifest.json','{}')
        with self.assertRaisesRegex(ValueError,'重复'): restore(self.root/'target',archive)

    def test_backup_cannot_replace_owned_database_or_preferences(self):
        self.preference(self.root)
        with self.assertRaises(ValueError): backup(self.root,self.root/'runtime/ui_preferences.json')

    def test_repeat_import_keeps_existing_records_and_old_files(self):
        project=self.root/'旧项目';old=project/'outputs';new=self.root/'new'
        self.preference(old,'teal');self.preference(new,'plum')
        oldstore=WorkspaceStore(old/'runtime/finance_workspace.sqlite3')
        newstore=WorkspaceStore(new/'runtime/finance_workspace.sqlite3')
        with oldstore.connection(True) as db: db.execute('INSERT INTO settings VALUES (?,?)',('ctx','{"old":1}'))
        with newstore.connection(True) as db: db.execute('INSERT INTO settings VALUES (?,?)',('ctx','{"new":1}'))
        import_legacy(new,project);import_legacy(new,project)
        with closing(sqlite3.connect(newstore.path)) as db:
            self.assertEqual(db.execute('SELECT payload FROM settings').fetchall(),[('{"new":1}',)])
        self.assertTrue(oldstore.path.exists())
        self.assertEqual(json.loads((new/'runtime/ui_preferences.json').read_text())['theme'],'plum')

    def test_relative_mapping_paths_rebased_without_identity_changes(self):
        value={'profile_id':'stable','tables':{'staff':{'files':['data/staff.csv']}}}
        result=rebase_profile(value,self.root)
        self.assertEqual(result['profile_id'],'stable')
        self.assertEqual(result['tables']['staff']['files'],[str((self.root/'data/staff.csv').resolve())])
        self.assertEqual(value['tables']['staff']['files'],['data/staff.csv'])

    def test_single_instance_focus_and_unlock(self):
        if os.name!='nt': self.skipTest('Windows lock contract')
        first=SingleInstance(self.root);second=SingleInstance(self.root)
        try:
            self.assertTrue(first.acquire());self.assertFalse(second.acquire());self.assertTrue((self.root/'focus.request').exists())
        finally: first.close();second.close()
        self.assertTrue(second.acquire());second.close()

    def test_backend_health_requires_owned_nonce_and_process(self):
        paths=AppPaths(ROOT,self.root);backend=Backend(paths,ROOT/'scripts/windows_app.py')
        backend.process=MagicMock(pid=42);backend.process.poll.return_value=None
        backend.run_dir=self.root/'sessions/nonce';backend.url='http://127.0.0.1:12345'
        atomic_json(backend.run_dir/'backend.json',{'pid':99,'launcher_pid':88,'run_id':'nonce'})
        with patch('desktop.controller.healthy',return_value=True):
            self.assertFalse(backend.transport_ready())
            atomic_json(backend.run_dir/'backend.json',{'pid':99,'launcher_pid':42,'run_id':'nonce'})
            self.assertTrue(backend.transport_ready())
            atomic_json(backend.run_dir/'backend.json',{'pid':42,'run_id':'wrong'})
            self.assertFalse(backend.transport_ready())

    def test_web_export_and_upload_compatibility(self):
        from dashboard.exports import export_artifact
        from dashboard.uploads import import_artifact
        with patch.dict(os.environ,{'FINANCEBP_DESKTOP':'0'}),patch('streamlit.download_button',return_value=False) as download,patch('streamlit.file_uploader',return_value=None) as upload:
            export_artifact('Excel',b'data',file_name='a.xlsx',key='old_key')
            import_artifact('Upload',type='xlsx',key='upload_key')
            self.assertEqual(download.call_args.kwargs['key'],'old_key');self.assertEqual(upload.call_args.kwargs['key'],'upload_key')

    def test_web_export_preserves_positional_and_keyword_data(self):
        from dashboard.exports import export_artifact
        with patch.dict(os.environ,{'FINANCEBP_DESKTOP':'0'}),patch('streamlit.download_button') as download:
            export_artifact('CSV',b'positional',file_name='one.csv')
            self.assertEqual(download.call_args.args,('CSV',b'positional'))
            self.assertNotIn('data',download.call_args.kwargs)
            export_artifact('CSV',data=b'keyword',file_name='two.csv')
            self.assertEqual(download.call_args.args,('CSV',))
            self.assertEqual(download.call_args.kwargs['data'],b'keyword')


if __name__=='__main__': unittest.main()
