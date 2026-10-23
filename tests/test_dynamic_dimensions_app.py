"""End-to-end classification slots, saved views and seven real application pages."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from dashboard.dimension_store import DimensionStore
from etl.sources import load_facts
from etl.dimensions import profile_key
import json


class DynamicDimensionAppTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path=Path(self.directory.name)/'views.json'
        self.patch=patch('dashboard.dimension_store.STORE_PATH',self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.config=json.loads((ROOT/'configs/multidimensional_files.json').read_text(encoding='utf-8'))

    def start(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']='多维模拟数据'
        app.run()
        self.clean(app)
        return app

    def clean(self,app):
        self.assertFalse(app.exception,[item.message for item in app.exception])

    def page(self,app,name):
        app.button('nav_'+name).click().run()
        self.clean(app)

    def test_fourth_configured_slot_opens_and_restores_all_objects_after_restart(self):
        app=self.start()
        self.assertEqual(len([x for x in app.selectbox if str(x.key).startswith('dimension_slot_')]),3)
        self.assertFalse(next(x for x in app.expander if x.label.startswith('更多分类')).proto.expanded)
        app.selectbox('dimension_slot_2').set_value('salesperson_id').run()
        app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
        app.button('dimension_add').click().run()
        app.selectbox('dimension_slot_3').set_value('region_id').run()
        self.clean(app)
        self.assertTrue(next(x for x in app.expander if x.label.startswith('更多分类')).proto.expanded)
        apply_filters(app)
        restarted=self.start()
        self.assertEqual(restarted.selectbox('dimension_slot_2').value,'salesperson_id')
        self.assertEqual(restarted.selectbox('dimension_slot_3').value,'region_id')
        self.assertEqual(restarted.multiselect('dim_value_salesperson_id').value,[])
        self.assertTrue(next(x for x in restarted.expander if x.label.startswith('更多分类')).proto.expanded)

    def test_dimension_change_and_removal_release_hidden_filters(self):
        app=self.start()
        app.selectbox('dimension_slot_2').set_value('salesperson_id').run()
        app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
        app.selectbox('dimension_slot_2').set_value('region_id').run()
        self.assertEqual(app.session_state['dimension_layout']['slots'][2],'region_id')
        self.assertTrue('dim_value_salesperson_id' not in app.session_state or not app.session_state['dim_value_salesperson_id'])
        app.button('dimension_add').click().run()
        app.selectbox('dimension_slot_3').set_value('salesperson_id').run()
        self.assertEqual(app.multiselect('dim_value_salesperson_id').value,[])
        app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
        app.button('dimension_remove_last').click().run()
        self.clean(app)
        self.assertTrue('dim_value_salesperson_id' not in app.session_state or not app.session_state['dim_value_salesperson_id'])
        self.assertIn('公司全部销售','\n'.join(x.value for x in app.markdown))

    def test_scheme_apply_clears_values_preserves_month_and_named_snapshot(self):
        app=self.start()
        app.selectbox('dimension_slot_2').set_value('salesperson_id').run()
        apply_filters(app)
        app.text_input('dimension_scheme_name').set_value('销售团队').run()
        app.button('dimension_save_new').click().run()
        self.clean(app)
        store=DimensionStore(self.path)
        saved=store.schemes(profile_key(self.config))[0]
        app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
        app.selectbox('month').set_value('2026-07').run()
        app.selectbox('dimension_slot_2').set_value('store_id').run()
        self.assertEqual(store.schemes(profile_key(self.config))[0]['layout']['slots'][2],'salesperson_id')
        app.selectbox('dimension_scheme').set_value(None).run()
        app.selectbox('dimension_scheme').set_value(saved['id']).run()
        self.clean(app)
        self.assertEqual(app.selectbox('month').value,'2026-07')
        self.assertEqual(app.multiselect('dim_value_salesperson_id').value,[])

    def test_seven_pages_share_filters_and_report_invalidates_on_group_change(self):
        app=self.start()
        app.selectbox('dimension_slot_2').set_value('salesperson_id').run()
        app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
        apply_filters(app)
        for name in ('月度趋势','维度分析','预算比较','预测与情景','点评与月报','数据与下载','经营总览'):
            self.page(app,name)
            self.assertEqual(app.multiselect('dim_value_salesperson_id').value,['1'])
            if name=='维度分析':
                app.multiselect('dimension_group_by').set_value(['sales_department_id','salesperson_id']).run()
                apply_filters(app)
                self.clean(app)
            if name=='预算比较':
                self.assertIn('不可比','\n'.join(x.value for x in app.info))
            if name=='预测与情景':
                app.selectbox('forecast_method').set_value('recent_mean').run()
                self.clean(app)
                self.assertIn('历史归属','\n'.join(x.value for x in app.warning))
            if name=='点评与月报':
                next(x for x in app.button if x.label=='生成点评与Excel月报').click().run()
                self.clean(app)
                generated=app.session_state['report_generated']
                self.assertEqual(generated['report']['metadata']['group_by'],['sales_department_id','salesperson_id'])
                self.assertEqual(generated['report']['metadata']['sales_filters']['dimensions'],{'salesperson_id':('1',)})
        self.page(app,'维度分析')
        app.multiselect('dimension_group_by').set_value(['store_id']).run()
        apply_filters(app)
        self.page(app,'点评与月报')
        self.assertTrue(app.info)
        self.assertFalse(any(x.key=='report_download_excel' for x in app.get('download_button')))
        self.assertEqual(DimensionStore(self.path).layout(profile_key(self.config),self.config['forecast_dimensions']+['customer_type'])[0]['group_by'],['store_id'])

    def test_legacy_source_new_month_file_keeps_layout_and_current_objects(self):
        from copy import deepcopy
        base=json.loads((ROOT/'configs/sample_files.json').read_text(encoding='utf-8'))
        facts=load_facts(base)
        updated=deepcopy(base)
        updated['tables']['products']['files'].append(base['tables']['products']['files'][0])
        with patch('etl.sources.load_facts',return_value=facts):
            app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
            app.session_state['source']='小样本核对'
            app.run()
            self.clean(app)
            self.page(app,'维度分析')
            app.multiselect('dimension_group_by').set_value(['channel_id','region_id']).run()
            app.multiselect('product_filter').set_value(['P001']).run()
            apply_filters(app)
            before=app.session_state['_dimension_scope']
            with patch('dashboard.profiles.selected_profile',return_value=updated):
                app.run()
                self.clean(app)
                self.assertEqual(app.session_state['_dimension_scope'],before)
                self.assertEqual(app.multiselect('dimension_group_by').value,['channel_id','region_id'])
                self.assertEqual(app.multiselect('product_filter').value,['P001'])

    def test_confirmation_validates_mapping_and_persists_for_next_start(self):
        app=self.start()
        app.button('open_dimension_setup').click().run()
        self.clean(app)
        app.toggle('dimension_advanced').set_value(True).run()
        self.assertEqual(app.text_input('dimension_mapping_1_label').value,'销售员')
        app.text_input('dimension_mapping_1_label').set_value('客户经理').run()
        next(x for x in app.button if x.label=='确认分类并验证数据').click().run()
        self.clean(app)
        self.assertFalse(app.error,[x.value for x in app.error])
        restarted=self.start()
        restarted.selectbox('dimension_slot_2').set_value('salesperson_id').run()
        self.assertTrue(any('客户经理' in x.label for x in restarted.multiselect))


if __name__=='__main__':
    unittest.main()
