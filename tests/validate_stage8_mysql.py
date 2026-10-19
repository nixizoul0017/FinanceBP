"""独立临时MySQL：在服务器内计算PVM，与标准模块逐商品逐因素核对。"""
from datetime import date
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import time

from sqlalchemy import text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis import FinancialEngine, Filters
from analysis.variance import variance_pack
from etl.common import ZERO, db_engine, read_json, write_json
from etl.ingest import Importer, initialize_demo
from etl.sources import load_facts


def run(port):
    started=time.perf_counter()
    settings={"host":"127.0.0.1","port":port,"user":"root","database":"finance_bp_demo_stage8"}
    admin=db_engine({**settings,"database":None},"")
    initialize_demo(admin,settings["database"])
    admin.dispose()
    database=db_engine(settings,"")
    checks=[]
    def check(name,condition):
        checks.append({"check":name,"passed":bool(condition)})
        assert condition,name
    try:
        with Importer(database,ROOT/"outputs/stage8/validation_imports") as importer:
            rows=importer.import_manifest(ROOT/"data/demo")
        check("temporary_import",all(row["rejected_rows"]==0 for row in rows))
        profile=read_json(ROOT/"configs/demo_mysql.example.json")
        profile["source"]["connection"]=settings
        sql_engine=FinancialEngine(load_facts(profile,database))
        file_engine=FinancialEngine(load_facts(ROOT/"configs/demo_files.json"))
        query=text((ROOT/"sql/stage8/01_product_driver_analysis.sql").read_text(encoding="utf-8"))
        sql_value_checks=0
        worst_difference=ZERO
        scenarios=[(f"2026-{month:02}",Filters()) for month in range(1,10)]+[("2026-09",Filters(products="P005")),("2026-09",Filters(channels="C03")),("2026-09",Filters(channels="C02",regions="R03"))]
        for month,filters in scenarios:
            result=variance_pack(sql_engine,month,filters)
            check("source_equivalence_"+month+str(filters.as_dict()),result["selected"]==variance_pack(file_engine,month,filters)["selected"])
            params={"month":date.fromisoformat(month+"-01"),"version":"B2026_V1","product":filters.products[0] if filters.products else None,"channel":filters.channels[0] if filters.channels else None,"region":filters.regions[0] if filters.regions else None}
            with database.connect() as connection:
                connection.execute(text("SET SESSION div_precision_increment=30"))
                expected=[dict(row) for row in connection.execute(query,params).mappings()]
            actual_inputs={row["product_id"]:row for row in result["selected"]["products"]}
            for row in expected:
                check("aligned_budget_"+month+row["product_id"]+str(filters.as_dict()),row["missing_budget_cells"]==0)
                for field in ("q_actual","q_budget","revenue_actual","revenue_budget","cost_actual","cost_budget","refund_actual","refund_budget","reversal_actual","reversal_budget"):
                    assert row[field]==actual_inputs[row["product_id"]][field],(month,field)
                    sql_value_checks+=1
            for kind,rename in (("revenue_bridge",{}),("gross_margin_bridge",{"new_product":"new_product_margin","no_sales_product":"no_sales_product_margin"})):
                model=result["selected"][kind]
                for detail in model["details"]:
                    row=next(row for row in expected if row["product_id"]==detail["product_id"])
                    expected_value=row[rename.get(detail["factor"],detail["factor"])]
                    difference=abs(expected_value-detail["amount"])
                    worst_difference=max(worst_difference,difference)
                    assert difference<Decimal("1e-18"),(month,detail,difference)
                    sql_value_checks+=1
                assert model["reconciled"]
            # 公司费用独立取数，不继承销售维度条件。
            with database.connect() as connection:
                fee_actual=connection.execute(text("SELECT SUM(amount) FROM expenses WHERE expense_date>=:month AND expense_date<DATE_ADD(:month,INTERVAL 1 MONTH)"),params).scalar_one()
                fee_budget=connection.execute(text("SELECT SUM(budget_amount) FROM budget_expenses WHERE month=:month AND budget_version=:version"),params).scalar_one()
            op=result["company_operating_bridge"]
            assert next(row["amount"] for row in op["components"] if row["factor"]=="expense")==fee_budget-fee_actual
        check("server_factor_formula_comparisons",sql_value_checks>0)
        write_json(ROOT/"outputs/stage8/mysql_validation.json",{"passed":True,"port":port,"scenarios":len(scenarios),"sql_value_checks":sql_value_checks,"max_factor_difference":worst_difference,"checks":checks,"seconds":round(time.perf_counter()-started,3)})
        print(f"STAGE8_MYSQL_PASS：{len(scenarios)}个场景，{sql_value_checks}项服务器数值核对。")
    finally:
        database.dispose()


if __name__=="__main__":
    run(int(sys.argv[1]))
