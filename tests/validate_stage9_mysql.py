"""独立临时MySQL核对预测来源、服务器近期均值与历史基准，来源只读。"""
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
import time

from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis import FinancialEngine,Filters
from analysis.forecast import History,forecast_base,predict,period_summary
from analysis.scenario import Assumptions,forecast_pack
from analysis.forecast_store import save_forecast,load_forecast
from etl.common import ZERO,db_engine,read_json,write_json
from etl.ingest import Importer,initialize_demo
from etl.sources import load_facts


def run(port):
    started=time.perf_counter()
    settings={"host":"127.0.0.1","port":port,"user":"root","database":"finance_bp_demo_stage9"}
    admin=db_engine({**settings,"database":None},"")
    initialize_demo(admin,settings["database"])
    admin.dispose()
    database=db_engine(settings,"")
    checks=[]
    values_checked=0
    maximum=ZERO
    def check(name,condition):
        checks.append({"check":name,"passed":bool(condition)})
        assert condition,name
    def near(left,right):
        nonlocal values_checked,maximum
        if left is None or right is None:
            assert left is right
        else:
            error=abs(left-right)
            maximum=max(maximum,error)
            assert error<Decimal("1e-18"),(left,right,error)
        values_checked+=1
    try:
        with Importer(database,ROOT/"outputs/stage9/validation_imports") as importer:
            imports=importer.import_manifest(ROOT/"data/demo")
        check("temporary_import",all(row["rejected_rows"]==0 for row in imports))
        profile=read_json(ROOT/"configs/demo_mysql.example.json")
        profile["source"]["connection"]=settings
        sql_engine=FinancialEngine(load_facts(profile,database))
        file_engine=FinancialEngine(load_facts(ROOT/"configs/demo_files.json"))
        sql_base=forecast_base(sql_engine,"2026-09")
        file_base=forecast_base(file_engine,"2026-09")
        check("chosen_method_and_backtest_source_equivalence",sql_base["metadata"]["method"]==file_base["metadata"]["method"] and sql_base["backtest"]["scores"]==file_base["backtest"]["scores"])
        for filters in (Filters(),Filters(products="P005"),Filters(channels="C03",regions="R01")):
            sql_result=forecast_pack(sql_base,filters,Assumptions(price_change="0.05",quantity_change="-0.03"))
            file_result=forecast_pack(file_base,filters,Assumptions(price_change="0.05",quantity_change="-0.03"))
            check("all_scenarios_equivalent_"+str(filters.as_dict()),sql_result["scenarios"]==file_result["scenarios"])
        history=History(sql_engine)
        trained=history.snapshot("2026-09")
        targets=[date(2026,m,1) for m in (10,11,12)]
        recent=predict(trained,targets,"recent_mean",3)
        query=text((ROOT/"sql/stage9/01_recent_mean_reference.sql").read_text(encoding="utf-8"))
        params={"start":date(2026,7,1),"cutoff":date(2026,9,1),"window":3}
        with database.connect() as connection:
            connection.execute(text("SET SESSION div_precision_increment=30"))
            reference=[dict(row) for row in connection.execute(query,params).mappings()]
            fees=[dict(row) for row in connection.execute(text("SELECT expense_category,department,COALESCE(channel_code,'ALL') AS channel_scope,COALESCE(region_code,'ALL') AS region_scope,ROUND(SUM(amount)/:window,2) AS amount FROM expenses WHERE expense_date>=:start AND expense_date<DATE_ADD(:cutoff,INTERVAL 1 MONTH) GROUP BY expense_category,department,channel_scope,region_scope"),params).mappings()]
        for period in recent:
            lookup={(row["product_id"],row["channel_id"],row["region_id"]):row for row in period["sales"]}
            for row in reference:
                actual=lookup[(row["product_id"],row["channel_code"],row["region_code"])]
                for field,expected_field in (("sales_quantity","forecast_quantity"),("sales_revenue","sales_revenue"),("sales_cost","sales_cost"),("refund_amount","refund_amount"),("cogs_reversal_amount","cogs_reversal_amount")):
                    near(actual[field],row[expected_field])
            for row in fees:
                actual=next(item for item in period["expense_rows"] if all(item[field]==row[field] for field in ("expense_category","department","channel_scope","region_scope")))
                near(actual["amount"],row["amount"])
        check("server_recent_mean_quantities_prices_refunds_expenses",True)
        seasonal=predict(trained,targets,"last_year_same_month",3)
        for period in seasonal:
            when=period["month"].replace(year=2025)
            with database.connect() as connection:
                sales=connection.execute(text("SELECT SUM(i.quantity*i.unit_list_price-i.discount_amount) AS revenue,SUM(i.quantity*i.unit_cost_snapshot) AS cost FROM orders o JOIN order_items i ON i.order_id=o.order_id WHERE o.order_status='completed' AND o.recognized_date>=:month AND o.recognized_date<DATE_ADD(:month,INTERVAL 1 MONTH)"),{"month":when}).mappings().one()
                returns=connection.execute(text("SELECT SUM(refund_amount) AS refund,SUM(cogs_reversal_amount) AS reversal FROM returns WHERE refund_date>=:month AND refund_date<DATE_ADD(:month,INTERVAL 1 MONTH)"),{"month":when}).mappings().one()
                fee=connection.execute(text("SELECT SUM(amount) FROM expenses WHERE expense_date>=:month AND expense_date<DATE_ADD(:month,INTERVAL 1 MONTH)"),{"month":when}).scalar_one()
            expected_revenue=sales["revenue"]-returns["refund"]
            expected_cost=sales["cost"]-returns["reversal"]
            actual=period_summary(period,trained.flags)
            for field,value in (("net_revenue",expected_revenue),("net_cost",expected_cost),("gross_margin",expected_revenue-expected_cost),("expenses",fee),("operating_profit",expected_revenue-expected_cost-fee)):
                near(actual[field],value)
        check("server_seasonal_baseline",True)
        saved=save_forecast(forecast_pack(sql_base),ROOT/"outputs/stage9/validation_runs")
        check("frozen_version_from_mysql_inputs",load_forecast(saved["path"])["result"]["metadata"]["training_fingerprint"]==sql_base["metadata"]["training_fingerprint"])
        write_json(ROOT/"outputs/stage9/mysql_validation.json",{"passed":True,"port":port,"numeric_checks":values_checked,"maximum_difference":maximum,"checks":checks,"seconds":round(time.perf_counter()-started,3)})
        print(f"STAGE9_MYSQL_PASS：{values_checked}项服务器数值核对，{len(checks)}组来源与保存验证。")
    finally:
        database.dispose()


if __name__=="__main__":
    run(int(sys.argv[1]))
