"""The business file wizard applies only a validated snapshot in the real app."""
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from dashboard.uploads import SelectedFile
from dashboard.file_import_ui import EMPTY, UNMAPPED
from test_business_files import simple_sales, write_book


class BusinessImportUITests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.path=self.root/'销售.xlsx';write_book(self.path,{'sales':simple_sales()})
        for target,name in [('dashboard.dimension_store.STORE_PATH','views.json'),
                            ('finance.store.STORE_PATH','finance.sqlite3'),
                            ('dashboard.theme.PREFERENCE_PATH','theme.json')]:
            mock=patch(target,self.root/name);mock.start();self.addCleanup(mock.stop)
        self.upload=patch('dashboard.file_import_ui.import_artifact',return_value=[SelectedFile(self.path.read_bytes(),self.path.name,str(self.path))])
        self.uploader=self.upload.start();self.addCleanup(self.upload.stop)

    def start(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']='自定义配置'
        app.session_state['display_unit']='元'
        app.run();self.clean(app)
        return app

    def clean(self,app):
        self.assertFalse(app.exception,[item.message for item in app.exception])

    def ready(self,app):
        app.toggle('business_financial_mode').set_value(True).run()
        app.checkbox('business_partial_period').uncheck().run()
        app.text_input('business_start').set_value('2026-09')
        app.text_input('business_end').set_value('2026-09')
        next(item for item in app.selectbox if item.label=='退款明细来源').set_value(EMPTY)
        next(item for item in app.checkbox if item.label.startswith('已确认：')).check()
        app.run();self.clean(app)
        return app

    def test_default_business_upload_supports_formats_and_advanced_json_remains(self):
        app=self.start()
        self.assertIn('Excel',app.radio('custom_import_mode').value)
        self.assertTrue({'xlsx','xls','dta','csv','tsv'}<=set(self.uploader.call_args.kwargs['type']))
        self.assertTrue(self.uploader.call_args.kwargs['accept_multiple_files'])
        self.assertFalse(app.metric)
        self.assertTrue(app.button('business_apply').disabled)
        app.radio('custom_import_mode').set_value('已有JSON配置（高级）').run()
        self.clean(app)
        self.assertEqual(len(app.get('file_uploader')),1)

    def test_source_switch_waiting_for_files_releases_loading_overlay(self):
        self.uploader.return_value=[]
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']='小样本核对'
        app.run();self.clean(app)
        app.selectbox('source').set_value('自定义配置').run();self.clean(app)
        self.assertTrue(any(item.value=='导入业务数据' for item in app.title))
        self.assertFalse(any('<div class="fb-loading" data-active="true"' in item.value for item in app.markdown))
        app.radio('custom_import_mode').set_value('已有JSON配置（高级）').run();self.clean(app)
        self.assertFalse(any('<div class="fb-loading" data-active="true"' in item.value for item in app.markdown))

    def test_preview_waiting_for_confirmation_releases_loading_overlay(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']='自定义配置'
        app.session_state['_source_loading']=True
        app.run();self.clean(app)
        self.assertTrue(app.button('business_apply').disabled)
        self.assertFalse(any('<div class="fb-loading" data-active="true"' in item.value for item in app.markdown))

    def test_desktop_waiting_for_native_file_selection_keeps_input_available(self):
        from dashboard.uploads import import_artifact
        self.uploader.side_effect=import_artifact
        with patch.dict(os.environ,{'FINANCEBP_DESKTOP':'1','FINANCEBP_RUN_DIR':str(self.root/'native_session')}):
            app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
            app.session_state['source']='自定义配置'
            app.session_state['_source_loading']=True
            app.run();self.clean(app)
            self.assertFalse(app.button('business_files').disabled)
            self.assertFalse(any('<div class="fb-loading" data-active="true"' in item.value for item in app.markdown))
            app.run();self.clean(app)
            self.assertFalse(app.button('business_files').disabled)
            self.assertFalse(any('<div class="fb-loading" data-active="true"' in item.value for item in app.markdown))

    def test_confirm_import_then_nine_pages_and_three_themes(self):
        app=self.ready(self.start())
        self.assertFalse(app.metric)
        app.button('business_apply').click().run();self.clean(app)
        self.assertEqual(app.session_state['engine'].summary('2026-09')['net_revenue'],Decimal(300))
        self.assertTrue(app.metric)
        for page in ['月度趋势','维度分析','预算工作台','预算比较','预测与情景','对账与跟进','点评与月报','数据与下载','经营总览']:
            app.button('nav_'+page).click().run();self.clean(app)
        for theme in ['teal','plum','navy']:
            app.radio('ui_theme').set_value(theme).run();self.clean(app)

    def test_invalid_mapping_keeps_previous_snapshot_and_cancel_restores(self):
        app=self.ready(self.start());app.button('business_apply').click().run();self.clean(app)
        original=app.session_state['engine'].metadata['source_fingerprint']
        app.button('business_edit_open').click().run();self.clean(app)
        # Required fields cannot silently inherit a different business meaning.
        next(item for item in app.selectbox if item.label=='订单编号（唯一明细编号） *').set_value(UNMAPPED).run()
        next(item for item in app.checkbox if item.label.startswith('已确认：')).check().run()
        app.button('business_apply').click().run();self.clean(app)
        self.assertTrue(any('缺少字段映射' in item.value for item in app.error),[item.value for item in app.error])
        self.assertEqual(app.session_state['engine'].metadata['source_fingerprint'],original)
        app.button('business_cancel').click().run();self.clean(app)
        self.assertEqual(app.session_state['engine'].metadata['source_fingerprint'],original)
        self.assertEqual(app.session_state['engine'].summary('2026-09')['net_revenue'],Decimal(300))


if __name__=='__main__':unittest.main()
