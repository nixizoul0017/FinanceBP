"""Offline diagnostics run inside the bundled interpreter, with isolated records."""
from decimal import Decimal
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import tempfile
import time


def run(paths,mysql_port=None):
    from analysis import FinancialEngine, Filters
    from etl.common import db_engine, encode
    from etl.sources import load_facts
    from reporting.service import build_report, markdown_report
    from reporting.excel import excel_bytes, inspect_excel
    from finance.budgets import workbook_bytes, parse_workbook, FORMAT
    from finance.store import WorkspaceStore
    from .workspace import backup,restore,import_legacy
    from .events import atomic_json
    from .artifacts import submit,save_request,finish_request
    started=time.perf_counter()
    paths.ensure()
    checks=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition: raise AssertionError(name)
    sample=FinancialEngine(load_facts(paths.resources/'configs/sample_files.json'))
    check('sample_net_revenue_3240',sample.summary('2026-09')['net_revenue']==Decimal(3240))
    check('sample_product_P001_2940',sample.summary('2026-09',filters=Filters(products='P001'))['net_revenue']==Decimal(2940))
    multi=FinancialEngine(load_facts(paths.resources/'configs/multidimensional_files.json'))
    check('salesperson_1_net_revenue_4300',multi.summary('2026-09',filters=Filters(dimensions={'salesperson_id':['1']}))['net_revenue']==Decimal(4300))
    groups=multi.dimensions('2026-09',by=['sales_department_id','salesperson_id'])
    check('joint_groups_preserve_amounts',sum(groups['net_revenue'])==multi.summary('2026-09')['net_revenue'])
    demo=FinancialEngine(load_facts(paths.resources/'configs/demo_files.json'))
    report=build_report(demo,'2026-09',data_origin='个人模拟数据')
    excel=excel_bytes(report)
    book=inspect_excel(excel)
    check('report_ten_sheets',len(book.sheetnames)==10)
    book.close()
    reference=json.loads((paths.resources/'tests/fixtures/report_reference.json').read_text(encoding='utf-8'))
    check('report_matches_web_reference',json.loads(json.dumps(report,default=encode))==reference)
    evidence=paths.exports/'诊断验收'
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'月报.xlsx').write_bytes(excel)
    (evidence/'月报.md').write_text(markdown_report(report),encoding='utf-8')
    (evidence/'月报.json').write_text(json.dumps(report,ensure_ascii=False,default=encode),encoding='utf-8')
    dataset={'format':FORMAT,'entity_id':sample.entity_id,'year':2026,'input_mode':'amounts','grain':[],'expense_grain':[],
             'sales':[{'month':'2026-09-01','budget_net_revenue':'3380','budget_net_cost':'2080'}],
             'expenses':[{'month':'2026-09-01','amount':'900'}]}
    payload=workbook_bytes(sample,2026,dataset=dataset)
    parsed=parse_workbook(payload,sample)
    check('budget_excel_roundtrip',parsed['sales'][0]['budget_net_revenue']==Decimal(3380))
    (evidence/'预算模板.xlsx').write_bytes(payload)
    with tempfile.TemporaryDirectory() as temporary:
        from etl.file_tables import read_table
        from etl.file_import import build_profile, suggest_mapping
        import pandas as pd
        from openpyxl import Workbook
        business=Path(temporary)/'中文业务.xlsx'
        book=Workbook();sheet=book.active;sheet.title='销售'
        sheet.append(['明细编号','订单号','销售日期','数量','销售金额','销售成本'])
        sheet.append(['0001','0001','2026-09-03',2,300,100]);book.save(business);book.close()
        table=read_table(business,sheet_name='销售')
        imported=build_profile('SELFTEST','文件导入自检','2026-09','2026-09',{
            'sales':{'reference':{'path':str(business),'name':business.name,'sheet_name':'销售'},'mapping':suggest_mapping('sales',table.columns)},
            'refunds':{'empty':True}})
        check('business_xlsx_net_revenue_300',FinancialEngine(load_facts(imported)).summary('2026-09')['net_revenue']==Decimal(300))
        stata=Path(temporary)/'业务.dta'
        pd.DataFrame({'staff':[7],'day':pd.to_datetime(['2026-09-03']),'amount':[135.25]}).to_stata(stata,write_index=False,version=118,convert_dates={'day':'td'},variable_labels={'staff':'销售员'})
        table=read_table(stata)
        check('business_dta_dates_codes_and_labels',table.rows[0]=={'staff':7,'day':'2026-09-03','amount':135.25} and table.comments['staff']=='销售员')
        legacy=read_table(paths.resources/'tests/fixtures/business_import_legacy.xls')
        check('business_legacy_xls_bundled_reader',legacy.rows[0]['员工编号']=='0007' and legacy.rows[0]['销售金额']==135.25)
        from etl.column_catalog import build_catalog, column_id, file_tables, summarize
        catalog=build_catalog('SELFTEST','表头分类',[
            {'reference':{'name':business.name,'path':str(business),'sheet_name':'销售','label':'销售'},
             'columns':[{'field':field,'label':'自定义'+field,'enabled':True} for field in read_table(business,sheet_name='销售').columns]}])
        table_id=next(iter(catalog['tables']))
        _,grouped=summarize(file_tables(catalog)[table_id],catalog['tables'][table_id],[column_id(table_id,'销售金额'),column_id(table_id,'销售日期')])
        check('header_catalog_amount_date_count',list(grouped)==['自定义销售金额','自定义销售日期','记录数'] and grouped['记录数'].sum()==1)
        check('header_catalog_no_invented_financial_semantics','semantics' not in catalog and 'coverage' not in catalog)
        root=Path(temporary)/'个人数据'
        store=WorkspaceStore(root/'runtime/finance_workspace.sqlite3')
        row=store.save_budget('selftest','诊断预算','original',parsed,'诊断')
        published=store.publish_budget('selftest',row['id'],'诊断','离线预算回读验收',1)
        check('sqlite_publish',published['status']=='published')
        atomic_json(root/'runtime/ui_preferences.json',{'version':1,'theme':'teal'})
        archive=Path(temporary)/'备份.zip'
        check('backup_two_files',backup(root,archive)==2)
        restored=Path(temporary)/'恢复数据'
        check('restore_preserves_budget',restore(restored,archive)==2 and WorkspaceStore(restored/'runtime/finance_workspace.sqlite3').budget('selftest',row['id'])['digest']==published['digest'])
        project=Path(temporary)/'旧项目'
        import shutil
        shutil.copytree(root,project/'outputs')
        import_legacy(restored,project);import_legacy(restored,project)
        check('repeat_import_no_duplicates',len(WorkspaceStore(restored/'runtime/finance_workspace.sqlite3').budgets('selftest'))==1)
        job=submit('中文测试','测试.csv','text/csv',folder=root)
        saved=save_request(root/'exports'/(job+'.json'),Path(temporary)/'中文另存为.csv')
        check('native_export_content',saved.read_text(encoding='utf-8')=='中文测试')
        job=submit(b'cancelled','取消.json',folder=root)
        finish_request(root/'exports'/(job+'.json'),'cancelled')
        check('cancel_export_cleans_payload',not (root/'exports'/(job+'.bin')).exists())
    mysql=None
    if mysql_port:
        profile=json.loads((paths.resources/'configs/sample_mysql.example.json').read_text(encoding='utf-8'))
        profile['source']['connection'].update(host='127.0.0.1',port=int(mysql_port),user='root')
        connection=db_engine(profile['source']['connection'],password='')
        try:
            actual=FinancialEngine(load_facts(profile,connection)).summary('2026-09')['net_revenue']
            check('isolated_frozen_mysql_net_revenue_3240',actual==Decimal(3240))
            mysql={'port':mysql_port,'net_revenue':str(actual)}
        finally: connection.dispose()
    return {'passed':True,'version':(paths.resources/'VERSION').read_text().strip(),'python':platform.python_version(),
            'platform':platform.platform(),'checks':checks,'report_id':report['report_id'],'mysql':mysql,
            'packages':{name:importlib.metadata.version(name) for name in ('streamlit','pandas','numpy','openpyxl','xlrd','PyMySQL','pywebview','pyinstaller')},
            'elapsed_seconds':round(time.perf_counter()-started,3),'created_at':datetime.now().isoformat(),
            'excel_sha256':hashlib.sha256(excel).hexdigest()}
