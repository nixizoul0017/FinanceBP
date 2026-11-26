"""Month replacement, provenance, validation and restart semantics on real file profiles."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from analysis import FinancialEngine
from dashboard.uploads import SelectedFile
from desktop.paths import AppPaths
from etl.file_import import build_profile, save_profile, saved_profiles, stage_uploads
from etl.month_update import prepare_update, inspect_input
from etl.sources import load_facts
from etl.dimensions import profile_key
from finance.issues import workflow_snapshot
from finance.reconciliation import reconciliation, compare_snapshot
from finance.store import WorkspaceStore
from reporting.service import build_report, markdown_report
from reporting.excel import excel_bytes
from openpyxl import load_workbook


class MonthlyUpdates(unittest.TestCase):
    def ref(self, rows):
        data=json.dumps(rows).encode()
        obj=stage_uploads([SelectedFile(data,'sales.json','')],paths=self.paths)[0]
        return {**obj,'sheet_name':None,'header_row':1,'aliases':{}}

    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths=AppPaths(ROOT,Path(tmp.name))
        self.jan={'id':'001','day':'2026-01-22','amount':'100.00','cost':'40.00','team':'甲'}
        self.feb={**self.jan,'id':'002','day':'2026-02-04','amount':'200.00'}
        self.profile=build_profile('ACME','订单','2026-01','2026-01',{
            'sales':{'reference':self.ref([self.jan]),'mapping':{'order_id':'id','revenue_date':'day',
                     'sales_amount_before_refund':'amount','cogs_amount':'cost'}},
            'refunds':{'empty':True},'expenses':{'empty':True}},dimension_fields=[{'field':'team','label':'团队'}])
        save_profile(self.profile,paths=self.paths)

    def update(self,profile,rows,start,end=None):
        end=end or start
        from etl.month_update import months_between
        decisions={m:'empty' for m in months_between(start,end)}
        return prepare_update(profile,{'sales':{'ref':self.ref(rows),'missing':decisions},
            'refunds':{'missing':decisions},'expenses':{'missing':decisions}},start,end)

    def test_monthly_vs_ytd_correction_and_three_exports(self):
        feb=self.update(self.profile,[self.feb],'2026-02')
        combined=self.update(self.profile,[self.jan,self.feb],'2026-01','2026-02')
        self.assertEqual(feb['facts'].metadata['snapshot_hash'],combined['facts'].metadata['snapshot_hash'])
        prior=feb['profile']
        store=WorkspaceStore(self.paths.runtime/'finance.sqlite3')
        ctx=profile_key(prior)
        engine=FinancialEngine(feb['facts'])
        snapshots={}
        for month in ['2026-01','2026-02']:
            rec=reconciliation(engine,month)
            store.save_controls(ctx,month,{r['field']:str(r['分析结果（元）']) for r in rec['rows']},'财务','模拟总账')
            store.confirm_month(ctx,engine,month,'财务','核对通过')
            snapshots[month]=store.closes(ctx,month)[0]['snapshot']
        corrected=[{**self.jan,'amount':'115.00'},self.feb]
        result=self.update(prior,corrected,'2026-01','2026-02')
        self.assertEqual([(r['月份'],r['业务编号'],r['变化']) for r in result['details']],[('2026-01','001','修改')])
        change=result['summary'][0]
        self.assertEqual(change['新金额']-change['原金额'],Decimal('15'))
        engine=FinancialEngine(result['facts'])
        for month,expected in [('2026-01',True),('2026-02',False)]:
            self.assertEqual(compare_snapshot(snapshots[month],engine,month)['changed'],expected)
        self.assertFalse(self.update(result['profile'],corrected,'2026-01','2026-02')['changed'])
        report=build_report(engine,'2026-01',workflow=workflow_snapshot(store,ctx,engine,'2026-01'))
        pre=report['metadata']['preflight']
        self.assertEqual(pre['月报状态'],'待核对')
        self.assertIn(pre['数据批次'],markdown_report(report))
        book=load_workbook(BytesIO(excel_bytes(report)),read_only=True)
        self.assertEqual(len(book.sheetnames),10)
        values=[v for row in book['口径与追溯'].values for v in row]
        self.assertIn(pre['数据批次'],values)
        self.assertIn('待核对',values)
        book.close()

    def test_atomic_conflict_failure_and_missing_decision(self):
        newer=self.update(self.profile,[self.feb],'2026-02')['profile']
        with patch('etl.file_import.atomic_json',side_effect=OSError('模拟写入中断')), self.assertRaises(OSError):
            save_profile(newer,expected=self.profile,paths=self.paths)
        self.assertEqual(saved_profiles(paths=self.paths),[self.profile])
        save_profile(newer,expected=self.profile,paths=self.paths)
        with self.assertRaisesRegex(ValueError,'已变化'):
            save_profile(self.profile,expected=self.profile,paths=self.paths)
        with self.assertRaisesRegex(ValueError,'逐月选择'):
            prepare_update(newer,{'sales':{'ref':self.ref([self.jan])}},'2026-01','2026-02')
        kept=prepare_update(newer,{'sales':{'ref':self.ref([self.jan]),'missing':{'2026-02':'keep'}}},'2026-01','2026-02')
        self.assertFalse(kept['changed'])
        deleted=prepare_update(newer,{'sales':{'ref':self.ref([self.jan]),'missing':{'2026-02':'empty'}}},'2026-01','2026-02')
        self.assertEqual(deleted['details'][0]['变化'],'移除')
        self.assertEqual(load_facts(saved_profiles(paths=self.paths)[0]).metadata['row_counts']['sales'],2)
        from desktop.workspace import backup, restore
        archive=self.paths.data/'更新后备份.zip'
        backup(self.paths.data,archive)
        restored=AppPaths(ROOT,self.paths.data/'restored')
        restore(restored.data,archive)
        self.assertEqual(load_facts(saved_profiles(paths=restored)[0]).metadata['snapshot_hash'],load_facts(newer).metadata['snapshot_hash'])

    def test_refund_against_history_aliases_and_partial_month(self):
        refund={'refund_id':'R2','sale_line_id':'001','refund_date':'2026-02-10','refund_amount':'8',
                'returned_quantity':0,'recoverable_quantity':0,'cost_reversal_amount':0}
        ref=self.ref([{**self.feb,'price':'220'}])
        ref['aliases']={'amount':'price'}
        info=inspect_input('sales',self.profile['tables']['sales'],ref,['2026-02'])
        self.assertEqual(info['amount'],220)
        changes={'sales':{'ref':ref},'refunds':{'ref':self.ref([refund]),'mapping':{k:k for k in refund},'defaults':{}}}
        result=prepare_update(self.profile,changes,'2026-02','2026-02')
        self.assertIn('2026-02-01',result['profile']['coverage']['incomplete_months'])
        self.assertIsNone(FinancialEngine(result['facts']).summary('2026-02')['observed_metrics']['expenses'])
        self.assertEqual(result['facts'].metadata['row_counts']['refunds'],1)
        changes['refunds']['ref']=self.ref([{**refund,'sale_line_id':'unknown'}])
        with self.assertRaises(ValueError):
            prepare_update(self.profile,changes,'2026-02','2026-02')

    def test_desktop_page_preview_then_activate(self):
        from streamlit.testing.v1 import AppTest
        import os
        ref=self.ref([{**self.jan,'amount':'115.00'}])
        with patch.dict(os.environ,{'FINANCEBP_DATA_DIR':str(self.paths.data),'FINANCEBP_DESKTOP':'0'}), patch(
            'dashboard.month_update_ui.import_artifact',return_value=[SelectedFile(Path(ref['path']).read_bytes(),'sales.json','')]):
            app=AppTest.from_file(ROOT/'app.py',default_timeout=45)
            app.session_state['source']='自定义配置'
            app.session_state['_business_profile']=self.profile
            app.run()
            app.button('business_month_update').click().run()
            next(r for r in app.radio if r.label=='更新方式').set_value('当月独立文件').run()
            app.selectbox('monthly_sales_ref').set_value(ref['sha256']+':None').run()
            next(b for b in app.button if b.label=='校验全部数据并预览差异').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['_monthly_preview'][1]['summary'][0]['新金额'],115)
            next(c for c in app.checkbox if c.label.startswith('已核对差异')).check().run()
            next(b for b in app.button if b.label=='应用此次月度更新').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['engine'].summary('2026-01')['net_revenue'],115)

