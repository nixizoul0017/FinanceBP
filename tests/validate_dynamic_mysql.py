"""Only for the isolated disposable MySQL acceptance server, never port 3306."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys

import pandas as pd
from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from analysis import FinancialEngine, Filters
from analysis.comparison import sales_budget_comparison
from etl.common import db_engine
from etl.sources import load_facts, inspect_profile


def run(port):
    if port!=33324:
        raise ValueError('This test requires isolated acceptance port 33324')
    config=json.loads((ROOT/'configs/multidimensional_files.json').read_text(encoding='utf-8'))
    expected=FinancialEngine(load_facts(config))
    settings={'host':'127.0.0.1','port':port,'user':'root','database':'finance_bp_multi_validation'}
    admin=db_engine({**settings,'database':None},'')
    with admin.begin() as connection:
        connection.execute(text('CREATE DATABASE finance_bp_multi_validation CHARACTER SET utf8mb4'))
    admin.dispose()
    engine=db_engine(settings,'')
    checks=[]
    def check(name,condition):
        checks.append({'check':name,'passed':bool(condition)})
        if not condition:
            raise AssertionError(name)
    try:
        for name,setting in config['tables'].items():
            frame=pd.read_csv(ROOT/setting['files'][0],dtype=str,keep_default_na=False)
            if 'employee_id' in frame:
                frame['employee_id']=pd.to_numeric(frame['employee_id'],errors='coerce').astype('Int64')
            frame.to_sql(name,engine,index=False,if_exists='fail')
        config['source']={'kind':'mysql','connection':settings}
        config['tables']={name:{'table':name} for name in config['tables']}
        actual=FinancialEngine(load_facts(config,engine))
        check('mysql_dynamic_totals_match_csv',actual.summary('2026-09')['net_revenue']==expected.summary('2026-09')['net_revenue'])
        check('mysql_nullable_numeric_employee_id_matches_names',actual.dimension_text('salesperson_id','1')=='林悦 · 1')
        check('mysql_missing_bucket_preserved',actual.dimension_text('salesperson_id',actual.tables['sales'].loc[actual.tables['sales']['sale_line_id'].eq('S202608-6-2'),'salesperson_id'].iloc[0])=='未归属')
        selected=Filters(dimensions={'salesperson_id':['1']})
        check('mysql_salesperson_filter_matches_csv',actual.summary('2026-09',filters=selected)['net_revenue']==Decimal(4300))
        check('mysql_coarse_budget_unavailable',sales_budget_comparison(actual,'2026-09',filters=selected,version='B2026_COMPANY')['status']=='unsupported_dimensions')
        scan_config=deepcopy(config)
        scan_config['dimensions']=[]
        scan_config.pop('forecast_dimensions')
        scan=inspect_profile(scan_config,engine)
        check('mysql_types_comments_and_candidates',any(item['field']=='employee_id' and 'INT' in item['type'].upper() for item in scan['candidates']))
        with engine.begin() as connection:
            connection.execute(text('INSERT INTO employees SELECT * FROM employees WHERE employee_id=1'))
        blocked=False
        try:
            load_facts(config,engine)
        except ValueError as error:
            blocked='唯一' in str(error)
        check('mysql_one_to_many_blocked',blocked)
    finally:
        engine.dispose()
    output=ROOT/'outputs/dynamic_dimensions/mysql_acceptance.json'
    output.write_text(json.dumps({'port':port,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
    print('DYNAMIC_MYSQL_PASS:',len(checks),'checks')


if __name__=='__main__':
    run(int(sys.argv[1]))
