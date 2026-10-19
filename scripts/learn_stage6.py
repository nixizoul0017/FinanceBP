"""最小学习例子：输入、返回值、商品毛利、公司利润、缺历史。"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from analysis import FinancialEngine, Filters
from analysis.comparison import trend_comparison, year_to_date
from etl.sources import load_facts

engine = FinancialEngine(load_facts(ROOT / "configs/sample_files.json"))
company = engine.summary("2026-09")
product = engine.summary("2026-09", filters=Filters(products=("P001",)))
print("公司净收入、毛利、费用、利润：", company["net_revenue"], company["gross_margin"], company["expenses"], company["operating_profit"])
print("P001净收入、毛利：", product["net_revenue"], product["gross_margin"])
print("P001经营利润：", product["operating_profit"], "（未分摊公司费用）")
print("小样本环比：", trend_comparison(engine, "2026-09")["mom"]["net_revenue"])
print("小样本YTD：", year_to_date(engine, "2026-09")["current"]["net_revenue"], "（缺少1—8月完整实际）")
