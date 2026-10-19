"""0.5.1: editing, applying, cancelling and invalidating analysis requests."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from analysis.service import analysis_pack
from analysis import FinancialEngine
from dashboard.dimension_store import DimensionStore
from dashboard.filter_state import normalized, selection, errors
from etl.sources import load_facts


def apply_filters(app):
    app.button('filter_apply').click().run()
    return app


class FilterApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        for target,name in [('dashboard.dimension_store.STORE_PATH','views.json'),
                            ('finance.store.STORE_PATH','finance.sqlite3'),
                            ('dashboard.theme.PREFERENCE_PATH','theme.json')]:
            mock=patch(target,self.path/name)
            mock.start()
            self.addCleanup(mock.stop)

    def start(self,source='小样本核对'):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']=source
        app.session_state['display_unit']='元'
        app.run()
        self.clean(app)
        return app

    def clean(self,app):
        self.assertFalse(app.exception,[item.message for item in app.exception])

    def test_edits_are_staged_and_apply_is_atomic_noop_is_disabled(self):
        with patch('analysis.service.analysis_pack',wraps=analysis_pack) as compute:
            app=self.start()
            self.assertTrue(app.button('filter_apply').disabled)
            before=[x.value for x in app.metric]
            app.multiselect('product_filter').set_value(['P001']).run()
            app.multiselect('channel_filter').set_value(['C02']).run()
            app.multiselect('region_filter').set_value(['R02']).run()
            app.selectbox('display_unit').set_value('万元').run()
            self.clean(app)
            self.assertEqual([x.value for x in app.metric],before)
            self.assertEqual(compute.call_count,1)
            self.assertEqual(selection(app.session_state['_filter_applied']).is_company,True)
            apply_filters(app)
            self.clean(app)
            self.assertEqual(app.metric[0].value,'0.06')
            self.assertEqual(compute.call_count,2)
            self.assertTrue(app.button('filter_apply').disabled)
            app.multiselect('product_filter').set_value(['P001']).run()
            self.assertTrue(app.button('filter_apply').disabled)
            self.assertEqual(compute.call_count,2)

    def test_cancel_and_navigation_discard_all_draft_values(self):
        app=self.start()
        app.multiselect('product_filter').set_value(['P001']).run()
        apply_filters(app)
        committed=deepcopy(app.session_state['_filter_applied'])
        app.selectbox('month').set_value('2026-10').run()
        app.selectbox('display_unit').set_value('万元').run()
        app.selectbox('dimension_slot_2').set_value(None).run()
        app.button('filter_cancel').click().run()
        self.clean(app)
        self.assertEqual(app.session_state['_filter_applied'],committed)
        self.assertEqual(app.selectbox('month').value,'2026-09')
        self.assertEqual(app.selectbox('dimension_slot_2').value,'region_id')
        app.multiselect('product_filter').set_value(['P002']).run()
        app.button('nav_维度分析').click().run()
        self.clean(app)
        self.assertEqual(app.multiselect('product_filter').value,['P001'])
        app.multiselect('dimension_group_by').set_value(['channel_id','region_id']).run()
        self.assertEqual(app.session_state['_filter_applied']['layout']['group_by'],['product_id'])
        app.button('nav_经营总览').click().run()
        self.assertEqual(app.session_state['_filter_applied'],committed)

    def test_display_and_slot_order_reuse_financial_results(self):
        from dashboard.view_model import monthly_trend
        with patch('analysis.service.analysis_pack',wraps=analysis_pack) as compute, patch('dashboard.view_model.monthly_trend',wraps=monthly_trend) as trend:
            app=self.start()
            app.selectbox('display_unit').set_value('万元').run()
            apply_filters(app)
            app.selectbox('dimension_slot_0').set_value(None).run()
            app.selectbox('dimension_slot_1').set_value('product_id').run()
            app.selectbox('dimension_slot_0').set_value('channel_id').run()
            apply_filters(app)
            self.clean(app)
            self.assertEqual(compute.call_count,1)
            self.assertEqual(trend.call_count,1)
            self.assertEqual(app.session_state['_filter_applied']['layout']['slots'][:2],['channel_id','product_id'])

    def test_scheme_stages_layout_and_saving_requires_application(self):
        app=self.start('多维模拟数据')
        scope=app.session_state['_dimension_scope']
        known=app.session_state['_dimension_known']
        store=DimensionStore()
        scheme=store.save_scheme(scope,'销售团队',{'slots':['sales_department_id','salesperson_id','region_id'],'group_by':['salesperson_id']},known)
        app.run()
        app.selectbox('dimension_scheme').set_value(scheme).run()
        self.clean(app)
        self.assertEqual(app.session_state['_filter_applied']['layout']['slots'][0],'product_id')
        self.assertTrue(app.button('dimension_save_new').disabled)
        # Loading a scheme must not remember its draft as the analysis layout.
        before=store.context(scope)
        apply_filters(app)
        self.assertEqual(app.session_state['_filter_applied']['scheme'],scheme)
        self.assertFalse(app.button('dimension_save_new').disabled)
        self.assertEqual(store.layout(scope,known)[0]['slots'][0],'sales_department_id')

    def test_refresh_invalid_object_requires_explicit_reapplication(self):
        facts=load_facts(ROOT/'configs/sample_files.json')
        app=self.start()
        app.multiselect('product_filter').set_value(['P001']).run()
        apply_filters(app)
        for name,frame in facts.tables.items():
            if 'product_id' in frame:
                frame.loc[frame['product_id'].eq('P001'),'product_id']='P099'
        facts.metadata['source_fingerprint']='replacement-snapshot'
        with patch('etl.sources.load_facts',return_value=facts):
            app.button('refresh_files').click().run()
            self.clean(app)
            self.assertTrue(app.session_state['_filter_invalid'])
            self.assertFalse(app.metric)
            self.assertEqual(selection(app.session_state['_filter_applied']).products,('P001',))
            self.assertFalse(app.button('filter_apply').disabled)
            apply_filters(app)
            self.clean(app)
            self.assertFalse(app.session_state['_filter_invalid'])
            self.assertTrue(selection(app.session_state['_filter_applied']).is_company)

    def test_candidate_snapshot_is_reused_and_unapplied_layout_is_not_remembered(self):
        original=FinancialEngine.dimension_values
        with patch.object(FinancialEngine,'dimension_values',autospec=True,side_effect=original) as candidates:
            app=self.start('多维模拟数据')
            count=candidates.call_count
            self.assertEqual(count,7)
            app.selectbox('dimension_slot_2').set_value('salesperson_id').run()
            app.multiselect('dim_value_salesperson_id').set_value(['1']).run()
            app.button('dimension_add').click().run()
            app.selectbox('dimension_slot_3').set_value('region_id').run()
            self.assertEqual(candidates.call_count,count)
            restarted=self.start('多维模拟数据')
            self.assertEqual(restarted.selectbox('dimension_slot_2').value,'region_id')
            apply_filters(app)
            restarted=self.start('多维模拟数据')
            self.assertEqual(restarted.selectbox('dimension_slot_3').value,'region_id')
            self.assertEqual(restarted.multiselect('dim_value_salesperson_id').value,[])

    def test_report_and_download_remain_valid_until_committed(self):
        from test_stage9 import simple_history
        with patch('etl.sources.load_facts',return_value=simple_history()):
            app=self.start()
            app.button('nav_点评与月报').click().run()
            app.button('FormSubmitter:report_generation-生成点评与Excel月报').click().run()
            self.clean(app)
            report=deepcopy(app.session_state['report_generated'])
            app.multiselect('product_filter').set_value(['A']).run()
            self.assertTrue(any(x.key=='report_download_excel' for x in app.get('download_button')))
            self.assertEqual(app.session_state['report_generated']['excel'],report['excel'])
            app.button('filter_cancel').click().run()
            app.selectbox('display_unit').set_value('万元').run()
            apply_filters(app)
            self.assertTrue(any(x.key=='report_download_excel' for x in app.get('download_button')))
            app.multiselect('product_filter').set_value(['A']).run()
            apply_filters(app)
            self.clean(app)
            self.assertFalse(any(x.key=='report_download_excel' for x in app.get('download_button')))

    def test_joint_grouping_and_budget_version_are_staged_independently(self):
        app=self.start('多维模拟数据')
        app.button('nav_维度分析').click().run()
        old=deepcopy(app.session_state['_filter_applied'])
        app.multiselect('dimension_group_by').set_value(['sales_department_id','salesperson_id']).run()
        versions=list(app.selectbox('budget_version').options)
        self.assertGreater(len(versions),1)
        app.selectbox('budget_version').set_value(versions[-1]).run()
        app.selectbox('month').set_value('2026-07').run()
        self.assertEqual(app.session_state['_filter_applied'],old)
        apply_filters(app)
        self.clean(app)
        request=app.session_state['_filter_applied']
        self.assertEqual(request['month'],'2026-07')
        self.assertEqual(request['version'],versions[-1])
        self.assertEqual(request['layout']['group_by'],['sales_department_id','salesperson_id'])
        frame=app.dataframe[0].value
        self.assertEqual(list(frame.columns[:2]),['销售部门','销售员'])

    def test_normalization_and_validation_do_not_silently_broaden(self):
        request={'month':'2026-09','version':'V1','unit':'元','scheme':None,
                 'layout':{'slots':['product_id',None,None,None],'group_by':['product_id']},
                 'objects':{'product_id':['P002','P001','P001']}}
        same=deepcopy(request)
        same['objects']['product_id']=['P001','P002']
        same['layout']['slots'].pop()
        self.assertEqual(normalized(request),normalized(same))
        self.assertTrue(errors(request,['product_id'],{'product_id':['P001']},['2026-09'],['V1']))
        self.assertFalse(selection(request).is_company)
        same['layout']['slots'][1]='product_id'
        self.assertIn('分类不能重复',errors(same,['product_id'],{'product_id':['P001','P002']},['2026-09'],['V1']))

    def test_loading_is_cleared_after_a_failed_apply_and_recovery(self):
        app=self.start()
        app.multiselect('product_filter').set_value(['P001']).run()
        with patch('analysis.service.analysis_pack',side_effect=ValueError('controlled test failure')):
            apply_filters(app)
        self.assertTrue(app.exception)
        self.assertFalse(any('<div class="fb-loading" data-active="true"' in x.value for x in app.markdown))
        self.assertTrue(any('<div class="fb-loading" data-active="false"' in x.value for x in app.markdown))
        app.run()
        self.clean(app)
        self.assertEqual(app.metric[0].value,'2,940.00')
        self.assertTrue(app.button('filter_apply').disabled)


if __name__=='__main__':
    unittest.main()
