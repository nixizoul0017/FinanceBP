"""阶段9预测、回测、情景及不可覆盖版本的命令行入口。"""
import argparse
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import pandas as pd
from analysis import FinancialEngine,Filters
from analysis.forecast import METHODS,forecast_base
from analysis.scenario import Assumptions,forecast_pack
from analysis.forecast_store import save_forecast
from dashboard.view_model import csv_bytes,money_text,safe_export_name
from etl.common import write_json
from etl.sources import load_facts


def run(profile,cutoff="2026-09",method="auto",window=3,version="B2026_V1",filters=Filters(),assumptions=Assumptions(),objective="net_revenue",output=None):
    engine=FinancialEngine(load_facts(profile))
    base=forecast_base(engine,cutoff,method,window,version,objective)
    result=forecast_pack(base,filters,assumptions)
    output=Path(output) if output is not None else ROOT/"outputs/forecasts"
    saved=save_forecast(result,output/"runs")
    write_json(output/"forecast_result.json",result)
    write_json(output/"backtest_result.json",result["backtest"])
    write_json(output/"saved_version.json",saved)
    summary=[]
    for name,item in result["scenarios"].items():
        for scope,past,future in (("当前销售范围",result["actual_selected_monthly"],item["selected_monthly"]),("公司全口径",result["actual_company_monthly"],item["company_monthly"])):
            rows=[{**row,"scenario":name,"scope":scope,"cutoff_month":base["metadata"]["cutoff_month"],"forecast_run_id":saved["run_id"]} for row in past+future]
            filename=safe_export_name(engine.entity_id,cutoff,"全年预测_"+name+"_"+scope,filters if scope=="当前销售范围" else Filters(),version=saved["run_id"],fingerprint=base["metadata"]["training_fingerprint"])
            (output/filename).write_bytes(csv_bytes(pd.DataFrame(rows)))
        summary.append({"scenario":name,"selected_net_revenue":item["selected_annual"]["net_revenue"],"selected_gross_margin":item["selected_annual"]["gross_margin"],"company_operating_profit":item["company_annual"]["operating_profit"],"company_expenses":item["company_annual"]["expenses"]})
    (output/"scenario_comparison.csv").write_bytes(csv_bytes(pd.DataFrame(summary)))
    print(f"截止月{cutoff}；方法{base['metadata']['method']}；选型指标{objective}；回测截止点{len(base['backtest']['origins'])}个。")
    for row in summary:
        print(f"{row['scenario']}：全年当前范围净收入{money_text(row['selected_net_revenue'])}元；全公司经营利润{money_text(row['company_operating_profit'])}元。")
    print(f"STAGE9_COMPLETED：保存版本{saved['run_id']}；重复内容复用{saved['reused']}。")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="截至时点预测与业务情景")
    parser.add_argument("--profile",default="configs/demo_files.json")
    parser.add_argument("--cutoff",default="2026-09")
    parser.add_argument("--method",choices=["auto",*METHODS],default="auto")
    parser.add_argument("--window",type=int,choices=[1,3,6],default=3)
    parser.add_argument("--version",default="B2026_V1")
    parser.add_argument("--objective",choices=["net_revenue","gross_margin","operating_profit"],default="net_revenue")
    parser.add_argument("--products",nargs="+")
    parser.add_argument("--channels",nargs="+")
    parser.add_argument("--regions",nargs="+")
    parser.add_argument("--output")
    for item in fields(Assumptions):
        parser.add_argument("--"+item.name.replace("_","-"),type=Decimal,default=Decimal(0),help="比例小数：0.05表示+5%%")
    args=parser.parse_args()
    try:
        profile=Path(args.profile)
        run(profile if profile.is_absolute() else ROOT/profile,args.cutoff,args.method,args.window,args.version,Filters(args.products,args.channels,args.regions),Assumptions(**{item.name:getattr(args,item.name) for item in fields(Assumptions)}),args.objective,args.output)
    except Exception as error:
        print("阶段9已停止："+type(error).__name__+"，请核对完整截止月、来源、方法与情景参数。",file=sys.stderr)
        sys.exit(1)
