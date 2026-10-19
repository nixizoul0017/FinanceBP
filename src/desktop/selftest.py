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
            'packages':{name:importlib.metadata.version(name) for name in ('streamlit','pandas','numpy','openpyxl','PyMySQL','pywebview','pyinstaller')},
            'elapsed_seconds':round(time.perf_counter()-started,3),'created_at':datetime.now().isoformat(),
            'excel_sha256':hashlib.sha256(excel).hexdigest()}
