"""All headers can be categories, independently of financial field definitions."""
from copy import deepcopy
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd
from openpyxl import Workbook
from sqlalchemy.dialects import mysql
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from analysis import FinancialEngine, Filters
from dashboard.uploads import SelectedFile
from desktop.paths import AppPaths
from etl.column_catalog import ADAPTER, build_catalog, column_id, database_tables, file_tables, summarize, table_id, validate_catalog
from etl.file_import import build_profile, saved_profiles, save_profile, stage_uploads, suggest_mapping, table_references
from etl.file_tables import read_table
from etl.sources import inspect_profile, load_facts, validate_profile


class CatalogFixture:
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.paths=AppPaths(ROOT,self.root/'private')
        self.path=self.root/'名册.xlsx'
        book=Workbook();sheet=book.active;sheet.title='员工';sheet.append(['演示用名册'])
        sheet.append(['员工','任职地','分值','日期','记录数']);sheet.append(['甲','北京',12,'2026-09-03','A']);sheet.append(['乙','北京',15,'2026-09-04','B']);sheet.append(['丙',None,12,'2026-09-04','C']);book.save(self.path);book.close()
        self.files=stage_uploads([SelectedFile(self.path.read_bytes(),self.path.name,str(self.path))],paths=self.paths)
        self.ref=table_references(self.files)[0]

    def specs(self,labels=None):
        table=read_table(self.ref['path'],sheet_name='员工',header_row=2)
        return [{'reference':self.ref,'header_row':2,'columns':[{'field':field,'label':(labels or {}).get(field,field),'enabled':True} for field in table.columns]}]

    def profile(self):return build_catalog('企业甲','名册接入',self.specs())


class ColumnCatalogTests(CatalogFixture,unittest.TestCase):
    def test_import_without_any_financial_columns_or_fake_semantics(self):
        profile=self.profile();validate_profile(profile)
        self.assertEqual(profile['adapter'],ADAPTER)
        self.assertNotIn('semantics',profile);self.assertNotIn('coverage',profile)
        key=next(iter(profile['tables']));frames=file_tables(profile)
        self.assertEqual(list(frames[key]),['员工','任职地','分值','日期','记录数'])
        self.assertEqual(len(frames[key]),3)

    def test_numeric_date_and_identifier_headers_can_all_group(self):
        profile=self.profile();key=next(iter(profile['tables']));frame=file_tables(profile)[key];setting=profile['tables'][key]
        for column in setting['columns']:
            selected,grouped=summarize(frame,setting,[column['id']])
            self.assertEqual(len(selected),3)
            self.assertEqual(grouped.iloc[:,-1].sum(),3)

    def test_missing_bucket_totals_and_multi_group_order(self):
        profile=self.profile();key=next(iter(profile['tables']));setting=profile['tables'][key];frame=file_tables(profile)[key]
        selected,groups=summarize(frame,setting,[column_id(key,'任职地'),column_id(key,'分值')])
        self.assertEqual(list(groups),['任职地','分值','记录数'])
        self.assertIn('未归属（缺失值）',groups['任职地'].tolist())
        _,filtered=summarize(frame,setting,[column_id(key,'员工')],{column_id(key,'任职地'):['北京']})
        self.assertEqual(filtered.iloc[:,-1].sum(),2)

    def test_rename_retains_original_field_id_and_local_reload(self):
        first=self.profile();second=build_catalog('企业甲','名册接入',self.specs({'任职地':'城市'}))
        key=next(iter(first['tables']))
        self.assertEqual(first['profile_id'],second['profile_id'])
        self.assertEqual(first['tables'][key]['columns'][1]['id'],second['tables'][key]['columns'][1]['id'])
        self.assertEqual(second['tables'][key]['columns'][1]['field'],'任职地')
        save_profile(second,paths=self.paths)
        self.assertEqual(saved_profiles(paths=self.paths),[second])

    def test_duplicate_blank_names_and_credentials_blocked(self):
        for labels in ({'任职地':'员工'},{'任职地':' '}):
            with self.assertRaises(ValueError):build_catalog('企业甲','名册接入',self.specs(labels))
        profile=self.profile();profile['source']={'kind':'mysql','connection':{'password':'never-save'}}
        with self.assertRaisesRegex(ValueError,'密码'):validate_catalog(profile)

    def test_removed_classification_cannot_silently_keep_filter(self):
        profile=self.profile();key=next(iter(profile['tables']));setting=profile['tables'][key]
        setting['columns'][1]['enabled']=False
        with self.assertRaisesRegex(ValueError,'失效'):
            summarize(file_tables(profile)[key],setting,[],{column_id(key,'任职地'):['北京']})

    def test_schema_changes_require_reconfirmation(self):
        profile=self.profile();setting=next(iter(profile['tables'].values()))
        setting['columns'].pop()
        with self.assertRaisesRegex(ValueError,'新表头'):file_tables(profile)

    def test_database_read_only_and_preserves_all_fields_including_empty_columns(self):
        engine=MagicMock();connection=engine.connect.return_value.__enter__.return_value
        connection.dialect=mysql.dialect()
        schema=MagicMock();schema.get_columns.return_value=[{'name':'任职地'},{'name':'金额'},{'name':'空列'}]
        frame=pd.DataFrame({'任职地':['北京'],'金额':[Decimal('12.34')],'空列':[None]})
        with patch('etl.column_catalog.inspect',return_value=schema),patch('etl.column_catalog.pd.read_sql_query',return_value=frame) as query:
            frames,_=database_tables(engine,['含 空格`表'])
        self.assertEqual(list(frames['含 空格`表']),list(frame))
        self.assertEqual(connection.exec_driver_sql.call_args_list[1].args[0],'START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        self.assertIn('`含 空格``表`',str(query.call_args.args[0]))
        connection.rollback.assert_called_once()

    def test_financial_amount_date_and_raw_alias_columns_group_without_changing_money(self):
        path=self.root/'sales.csv'
        path.write_text('sale_line_id,order_id,when,quantity,raw_quantity,cost,product\n001,001,2026-09-03,300,2,100,A\n',encoding='utf-8')
        ref={'path':str(path),'name':path.name,'sheet_name':None}
        mapping={'sale_line_id':'sale_line_id','order_id':'order_id','revenue_date':'when','sales_amount_before_refund':'quantity','quantity':'raw_quantity','cogs_amount':'cost','product_id':'product'}
        dimensions=[{'field':field,'label':label} for field,label in [('quantity','原始金额'),('when','交易日'),('product','品类')]]
        profile=build_profile('E','财务','2026-09','2026-09',{'sales':{'reference':ref,'mapping':mapping},'refunds':{'empty':True}},dimension_fields=dimensions,selected_headers=True)
        engine=FinancialEngine(load_facts(profile))
        amount=next(item['id'] for item in profile['dimensions'] if item['label']=='原始金额')
        self.assertEqual(engine.dimension_values(amount),['300'])
        self.assertEqual(engine.summary('2026-09')['net_revenue'],Decimal(300))
        self.assertEqual(engine.dimension_labels['product_id'],'品类')
        self.assertNotIn('channel_id',engine.selectable_dimension_ids)
        self.assertEqual(engine.metadata['forecast_dimensions'],['product_id','channel_id','region_id'])

    def test_mysql_and_file_scans_list_all_field_types(self):
        scan=inspect_profile(json.loads((ROOT/'configs/multidimensional_files.json').read_text(encoding='utf-8')))
        fields={item['field'] for item in scan['candidates'] if item['table']=='sales'}
        self.assertTrue({'sale_line_id','revenue_date','quantity','sales_amount_before_refund','employee_id'}<=fields)


class ColumnCatalogUITests(CatalogFixture,unittest.TestCase):
    def setUp(self):
        super().setUp()
        for target,name in [('dashboard.dimension_store.STORE_PATH','views.json'),('finance.store.STORE_PATH','finance.sqlite3'),('dashboard.theme.PREFERENCE_PATH','theme.json')]:
            mock=patch(target,self.root/name);mock.start();self.addCleanup(mock.stop)
        upload=patch('dashboard.file_import_ui.import_artifact',return_value=[SelectedFile(self.path.read_bytes(),self.path.name,str(self.path))])
        upload.start();self.addCleanup(upload.stop)

    def editor(self,data,**kwargs):
        result=data.copy()
        result.loc[result['原表头'].isin(['任职地','分值','日期']),'启用']=True
        result.loc[result['原表头'].eq('任职地'),'分类名称']='城市'
        return result

    def start(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90);app.session_state['source']='自定义配置';app.run()
        next(item for item in app.number_input if item.label=='第几行作为表头 / 分类名称').set_value(2).run()
        self.assertFalse(app.exception,[item.message for item in app.exception]);return app

    def test_default_header_flow_import_rename_and_edit_without_financial_mapping(self):
        with patch('dashboard.column_catalog_ui.st.data_editor',side_effect=self.editor):
            app=self.start()
            self.assertFalse(any(item.key=='business_start' for item in app.text_input))
            next(item for item in app.checkbox if item.label.startswith('已核对表头行')).check().run()
            app.button('business_apply').click().run()
            self.assertFalse(app.exception,[item.message for item in app.exception])
            profile=app.session_state['_business_profile'];key=next(iter(profile['tables']))
            self.assertEqual(profile['adapter'],ADAPTER)
            self.assertEqual(profile['tables'][key]['columns'][1]['label'],'城市')
            self.assertTrue(any(item.label=='城市' for item in app.multiselect))
            self.assertFalse(any('fb-loading" data-active="true' in item.value for item in app.markdown))
            app.button('open_dimension_setup').click().run()
            self.assertFalse(app.exception,[item.message for item in app.exception])
            self.assertEqual(next(item for item in app.number_input if item.label=='第几行作为表头 / 分类名称').value,2)

    def test_no_save_until_confirm_and_duplicate_labels_fail(self):
        app=self.start()
        self.assertTrue(app.button('business_apply').disabled)
        self.assertNotIn('_business_profile',app.session_state)
        def duplicate(data,**kwargs):
            result=data.copy();result['启用']=True;result['分类名称']='重复名称';return result
        with patch('dashboard.column_catalog_ui.st.data_editor',side_effect=duplicate):
            app.run()
            next(item for item in app.checkbox if item.label.startswith('已核对表头行')).check().run()
            app.button('business_apply').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertNotIn('_business_profile',app.session_state)

    def test_financial_category_grid_renames_and_keeps_financial_baseline(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        app.session_state['source']='小样本核对';app.run()
        def financial_editor(data,**kwargs):
            result=data.copy()
            result.loc[result['分类名称'].eq('商品'),'分类名称']='产品类别'
            result.loc[result['来源表'].eq('order_items') & result['原表头'].eq('quantity'),'启用']=True
            return result
        with patch('dashboard.dimension_setup.st.data_editor',side_effect=financial_editor):
            app.button('open_dimension_setup').click().run()
            app.button('dimension_headers_apply').click().run()
        self.assertFalse(app.exception,[item.message for item in app.exception])
        self.assertFalse(app.error,[item.value for item in app.error])
        self.assertEqual(app.session_state['engine'].summary('2026-09')['net_revenue'],Decimal(3240))
        self.assertEqual(app.session_state['engine'].dimension_labels['product_id'],'产品类别')
        restarted=AppTest.from_file(ROOT/'app.py',default_timeout=90)
        restarted.session_state['source']='小样本核对';restarted.run()
        self.assertEqual(restarted.session_state['engine'].dimension_labels['product_id'],'产品类别')


if __name__=='__main__':unittest.main()
