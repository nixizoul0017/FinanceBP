"""Real application controls: publish budgets, confirm a month and retain action notes."""
from pathlib import Path
from decimal import Decimal
import sys
import tempfile
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from finance.store import WorkspaceStore
from test_finance_workflow import dataset


class FinanceAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'finance.sqlite3'
        for target,value in [('finance.store.STORE_PATH',self.path),('dashboard.dimension_store.STORE_PATH',Path(self.tmp.name)/'views.json')]:
            item=patch(target,value);item.start();self.addCleanup(item.stop)
        self.store=WorkspaceStore(self.path)

    def start(self,source='小样本核对'):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']=source
        app.run();self.clean(app)
        return app

    def clean(self,app):
        self.assertFalse(app.exception,[r.message for r in app.exception])

    def page(self,app,name):
        app.button('nav_'+name).click().run();self.clean(app)

    def item(self,app,kind,label):
        return next(item for item in getattr(app,kind) if item.label==label)

    def test_budget_publish_changes_version_and_clone_adjustment(self):
        app=self.start()
        context=app.session_state['_dimension_scope']
        d=dataset();d['entity_id']='XCYX_SAMPLE'
        row=self.store.save_budget(context,'2026原始预算','original',d,'测试编制员')
        self.page(app,'预算工作台')
        self.item(app,'text_input','发布确认人').set_value('测试确认员')
        self.item(app,'text_area','发布说明').set_value('已核对公司合计和预算年度')
        self.item(app,'checkbox','我已核对企业、年度、分类粒度和金额，确认将此版本发布到分析中').check()
        self.item(app,'button','确认发布预算').click().run();self.clean(app)
        self.assertEqual(app.selectbox('budget_version').value,row['id'])
        self.assertEqual(self.store.budget(context,row['id'])['status'],'published')
        self.item(app,'text_input','新调整预算名称').set_value('2026调整一')
        self.item(app,'text_input','调整预算编制人').set_value('预算员')
        self.item(app,'text_input','调整原因').set_value('变更销量预期')
        self.item(app,'button','从此版本建立调整草稿').click().run();self.clean(app)
        self.assertEqual(len(self.store.budgets(context)),2)
        self.page(app,'预算比较')
        self.assertFalse(app.error)

    def test_independent_controls_confirm_month_and_release(self):
        app=self.start();context=app.session_state['_dimension_scope']
        self.page(app,'对账与跟进')
        self.assertTrue(self.item(app,'button','保存本月确认快照').disabled)
        refs={'退款前销售收入':'4150','退款额':'910','成交成本':'2615','成本转回':'560','公司费用':'400'}
        for label,value in refs.items():self.item(app,'text_input',label+'（元）').set_value(value)
        self.item(app,'text_input','核对人').set_value('测试核对员')
        self.item(app,'text_area','独立参考来源与期间').set_value('小样本独立SQL参考表，2026年9月')
        self.item(app,'button','保存核对依据').click().run();self.clean(app)
        self.assertFalse(self.item(app,'button','保存本月确认快照').disabled)
        self.item(app,'text_input','月份确认人').set_value('财务负责人')
        self.item(app,'text_area','月份确认说明').set_value('五项独立核对通过')
        self.item(app,'checkbox','我已核对独立依据并确认本月实际；这是本程序的管理确认，不代表法定审计或数据库关账').check()
        self.item(app,'button','保存本月确认快照').click().run();self.clean(app)
        self.assertEqual(len(self.store.closes(context,'2026-09')),1)
        self.item(app,'text_input','解除确认人').set_value('复核人')
        self.item(app,'text_area','解除原因').set_value('验证可保留原快照并复核')
        self.item(app,'button','保留历史并解除确认').click().run();self.clean(app)
        self.assertTrue(self.store.closes(context)[0]['released_at'])

    def test_exception_action_survives_scan_and_report_invalidates(self):
        app=self.start();context=app.session_state['_dimension_scope']
        self.store.save_settings(context,{'amount':0,'rate':0},'测试设置人')
        self.page(app,'对账与跟进')
        self.item(app,'text_input','本次扫描记录人').set_value('测试扫描员')
        app.button('issue_scan').click().run();self.clean(app)
        self.assertEqual(len(self.store.issues(context)),2)
        self.item(app,'selectbox','处理状态').set_value('in_progress')
        self.item(app,'text_input','负责人').set_value('销售主管')
        self.item(app,'text_area','后续行动').set_value('核实促销成交价')
        self.item(app,'text_input','截止日（YYYY-MM-DD）').set_value('2026-10-30')
        self.item(app,'text_input','本次记录人').set_value('财务BP')
        self.item(app,'button','保存跟进记录').click().run();self.clean(app)
        app.button('issue_scan').click().run();self.clean(app)
        self.assertTrue(any(r['notes'].get('owner')=='销售主管' for r in self.store.issues(context)))
        self.page(app,'点评与月报')
        self.item(app,'button','生成点评与Excel月报').click().run();self.clean(app)
        self.assertTrue('report_generated' in app.session_state,[r.value for r in app.error])
        saved=app.session_state['report_generated']
        row=self.store.issues(context)[0]
        self.store.update_issue(context,row['id'],{'resolution':'独立核对说明'},'ignored','复核员',row['revision'])
        app.run();self.clean(app)
        self.assertFalse(any(r.key=='report_download_excel' for r in app.get('download_button')))
        self.assertEqual(app.session_state['report_generated']['key'],saved['key'])

    def test_history_comparison_remembers_mode_between_pages_and_themes(self):
        app=self.start('多维模拟数据')
        self.page(app,'月度趋势')
        app.radio('history_mode').set_value('yoy').run();self.clean(app)
        self.page(app,'预算工作台')
        self.page(app,'月度趋势')
        self.assertEqual(app.radio('history_mode').value,'yoy')
        for theme in ('navy','teal','plum'):
            app.radio('ui_theme').set_value(theme).run();self.clean(app)
            self.page(app,'对账与跟进')
            self.page(app,'预算工作台')
        self.assertFalse(app.error)


if __name__=='__main__':unittest.main()
