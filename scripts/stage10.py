"""导出同一财务口径的点评、Excel与精确分析包。"""
import argparse
from dataclasses import fields
from decimal import Decimal
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from analysis import FinancialEngine,Filters
from analysis.scenario import Assumptions
from dashboard.view_model import safe_export_name
from etl.common import write_json
from etl.sources import load_facts
from reporting.service import build_report,markdown_report
from reporting.excel import excel_bytes,inspect_excel


def run(profile,month="2026-09",version="B2026_V1",filters=Filters(),method="auto",window=3,objective="net_revenue",assumptions=Assumptions(),output=None,data_origin=None):
    engine=FinancialEngine(load_facts(profile))
    known={"demo_files.json","demo_renamed_files.json","sample_files.json","demo_mysql.example.json","sample_mysql.example.json"}
    origin=data_origin or ("个人模拟数据" if Path(profile).resolve().parent==ROOT/"configs" and Path(profile).name in known else "来源属性待确认")
    report=build_report(engine,month,filters,version,method=method,window=window,objective=objective,assumptions=assumptions,data_origin=origin)
    payload=excel_bytes(report)
    book=inspect_excel(payload)
    output=Path(output) if output else ROOT/"outputs/reports"
    output.mkdir(parents=True,exist_ok=True)
    name=safe_export_name(engine.entity_id,month,"经营月报",filters,version=report["report_id"],fingerprint=engine.metadata.get("source_fingerprint")).removesuffix(".csv")
    path=output/(name+".xlsx")
    path.write_bytes(payload)
    (output/"commentary.md").write_text(markdown_report(report),encoding="utf-8")
    write_json(output/"report_result.json",report)
    write_json(output/"export_manifest.json",{"report_id":report["report_id"],"forecast_content_id":report["forecast_content_id"],"excel_path":str(path),"worksheets":book.sheetnames,"bytes":len(payload),"validation":report["validation"]})
    print("STAGE10_COMPLETED："+report["report_id"]+"；"+str(len(book.sheetnames))+"张月报工作表；"+str(report["validation"]["fact_count"])+"项点评事实核对通过。")
    return report,path


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="经营点评与Excel月报")
    parser.add_argument("--profile",default="configs/demo_files.json")
    parser.add_argument("--month",default="2026-09")
    parser.add_argument("--version",default="B2026_V1")
    parser.add_argument("--method",choices=["auto","last_year_same_month","recent_mean","driver_based"],default="auto")
    parser.add_argument("--window",type=int,choices=[1,3,6],default=3)
    parser.add_argument("--objective",choices=["net_revenue","gross_margin","operating_profit"],default="net_revenue")
    for dimension in ("products","channels","regions"):
        parser.add_argument("--"+dimension,nargs="+")
    for item in fields(Assumptions):
        parser.add_argument("--"+item.name.replace("_","-"),type=Decimal,default=Decimal(0))
    parser.add_argument("--output")
    parser.add_argument("--data-origin")
    args=parser.parse_args()
    profile=Path(args.profile)
    try:
        run(profile if profile.is_absolute() else ROOT/profile,args.month,args.version,Filters(args.products,args.channels,args.regions),args.method,args.window,args.objective,Assumptions(**{item.name:getattr(args,item.name) for item in fields(Assumptions)}),args.output,args.data_origin)
    except Exception as error:
        print("阶段10已停止："+type(error).__name__+"；请检查来源、期间、预算和报表依赖。",file=sys.stderr)
        sys.exit(1)
