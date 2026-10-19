"""Independent deterministic classification fixtures; never writes a database."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import csv
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from etl.sources import CONTRACT, SEMANTICS


def generate():
    target=ROOT/'data/demo/multidimensional'
    target.mkdir(parents=True,exist_ok=True)
    rows={name:[] for name in CONTRACT}
    people=[{'employee_id':str(i),'employee_name':name} for i,name in enumerate(('林悦','陈舟','周宁','李晨','王晓','刘然'),1)]
    for year,last in ((2025,12),(2026,9)):
        for month in range(1,last+1):
            for person in people:
                employee=person['employee_id']
                dept='D1' if int(employee)<=3 else 'D2'
                if employee=='1' and (year,month)>=(2026,7):
                    dept='D2'
                for p in range(1,3):
                    tag=f'{year}{month:02}-{employee}-{p}'
                    count=10+int(employee)+month+p
                    sales=dict(entity_id='MULTI_DEMO',sale_line_id='S'+tag,order_id=f'O{year}{month:02}-{employee}',revenue_date=date(year,month,10),product_id='P'+str(p),channel_id='C'+str(1+int(employee)%2),region_id='R'+str(1+int(employee)%2),quantity=count,sales_amount_before_refund=count*100,cogs_amount=count*60,sales_department=dept,employee_id=employee,store_code='SHOP'+str(1+int(employee)%3),customer_segment='企业客户' if p==1 else '个人客户')
                    if year==2026 and month==8 and employee=='6' and p==2:
                        sales['employee_id']=''
                        sales['sales_department']=''
                    rows['sales'].append(sales)
            rows['expenses'].append(dict(entity_id='MULTI_DEMO',expense_id=f'E{year}{month:02}',expense_date=date(year,month,15),expense_category='administration',department='公司管理部',channel_scope='ALL',region_scope='ALL',amount=1200))
    # A refund after employee 1 transferred: it retains the original June department D1.
    rows['refunds'].append(dict(entity_id='MULTI_DEMO',refund_id='F_TRANSFER',sale_line_id='S202606-1-1',refund_date=date(2026,8,20),returned_quantity=1,recoverable_quantity=1,refund_amount=100,cost_reversal_amount=60))
    for month in range(1,13):
        coarse=defaultdict(int)
        for person in people:
            employee=person['employee_id']
            dept='D1' if int(employee)<=3 else 'D2'
            if employee=='1' and month>=7:
                dept='D2'
            for p in range(1,3):
                key=('P'+str(p),'C'+str(1+int(employee)%2),'R'+str(1+int(employee)%2))
                count=12+int(employee)+month+p
                coarse[key]+=count
                rows['sales_budget'].append(dict(entity_id='MULTI_DEMO',budget_version='B2026_TEAM',month=date(2026,month,1),product_id=key[0],channel_id=key[1],region_id=key[2],quantity=count,net_unit_price=100,unit_cost=60,refund_amount=0,cost_reversal_amount=0,sales_department=dept,employee_id=employee))
        for key,count in sorted(coarse.items()):
            rows['sales_budget'].append(dict(entity_id='MULTI_DEMO',budget_version='B2026_COMPANY',month=date(2026,month,1),product_id=key[0],channel_id=key[1],region_id=key[2],quantity=count,net_unit_price=100,unit_cost=60,refund_amount=0,cost_reversal_amount=0,sales_department='',employee_id=''))
        for version in ('B2026_TEAM','B2026_COMPANY'):
            rows['expense_budget'].append(dict(entity_id='MULTI_DEMO',budget_version=version,month=date(2026,month,1),expense_category='administration',department='公司管理部',channel_scope='ALL',region_scope='ALL',amount=1200))
    rows['employees']=people
    for name,items in rows.items():
        fields=list(items[0]) if items else CONTRACT[name]
        with (target/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader()
            writer.writerows(items)
    specs=[]
    for identifier,label,field in (('sales_department_id','销售部门','sales_department'),('salesperson_id','销售员','employee_id'),('store_id','门店','store_code'),('customer_type','客户类型','customer_segment')):
        binding={'table':'sales','field':field}
        if identifier=='salesperson_id':
            binding['lookup']={'table':'employees','key':'employee_id','name_field':'employee_name'}
        bindings={'sales':binding}
        if identifier in ('sales_department_id','salesperson_id'):
            bindings['sales_budget']={'table':'sales_budget','field':field,'versions':['B2026_TEAM']}
        specs.append({'id':identifier,'label':label,'bindings':bindings})
    profile={'profile_version':2,'profile_id':'multidimensional-demo','display_name':'星辰优选 · 多维经营','entity_id':'MULTI_DEMO','rule_version':'sales_v1','coverage':{'complete_start':'2025-01-01','complete_end':'2026-09-30'},'semantics':SEMANTICS,'adapter':'mapped_facts_v1','source':{'kind':'files'},'tables':{name:{'files':['data/demo/multidimensional/'+name+'.csv']} for name in rows},'lookup_tables':['employees'],'dimensions':specs,'forecast_dimensions':['product_id','channel_id','region_id','sales_department_id','salesperson_id','store_id']}
    (ROOT/'configs/multidimensional_files.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({name:len(items) for name,items in rows.items()},ensure_ascii=False))


if __name__=='__main__':
    generate()
