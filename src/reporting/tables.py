"""报表表格定义独立于导出引擎，保留原始Decimal及缺失状态。"""
from datetime import date
from analysis.forecast import METHOD_LABELS
from analysis.metrics import Filters
from etl.dimensions import display
from analysis.variance import contribution_ranking
from .service import METRICS, SCENARIOS, REASONS, validate_report

ADJUSTMENTS={"quantity_change":"销量调整","price_change":"均价调整","unit_cost_change":"单位成本调整","refund_rate_change":"退款强度调整","cost_reversal_change":"成本转回调整","marketing_change":"营销调整","expense_change":"全部费用调整"}
DIRECTIONS={"favorable":"有利","unfavorable":"不利","on_budget":"持平","unknown":"未知"}


def section(title,headers,rows,types=None,widths=None):
    return {"title":title,"headers":headers,"rows":rows,"types":types or ["text"]*len(headers),"widths":widths}


def workbook_tables(report):
    validate_report(report)
    meta=report["metadata"]
    a,d,f=(report["sources"][key] for key in ("analysis","drivers","forecast"))
    specs=meta.get('dimension_registry',[{'id':key,'label':label} for key,label in (('product_id','商品'),('channel_id','渠道'),('region_id','区域'))])
    dims=[entry['id'] for entry in specs]
    dim_labels={entry['id']:entry['label'] for entry in specs}
    extra=[field for field in dims if field not in ('product_id','channel_id','region_id')]
    budget_dims=meta.get('budget_dimensions',dims)
    budget_labels=[dim_labels[field] for field in budget_dims]
    selection=Filters.from_dict(meta['sales_filters'])
    sheets=[]
    def sheet(name,sections):
        sheets.append({"name":name,"title":meta["entity_id"]+" "+str(meta["month"])[:7]+" "+name,"sections":sections})
    highlights=[["当前销售范围",METRICS[key],a["selected_scope"][key]] for key in ("net_revenue","net_cost","gross_margin","gross_margin_rate")]
    highlights += [["公司全口径",METRICS[key],a["company_scope"][key]] for key in ("expenses","operating_profit")]
    sheet("总览点评",[section("本月指标（金额为元）",["范围","指标","结果"],highlights,["text","text","metric"],[24,25,23]),
        section("经营点评",["章节","性质","点评","事实引用"],[[row["section"],row["kind"],row["text"],",".join(row["fact_ids"])] for row in report["commentary"]["statements"]],widths=[16,16,100,25])])
    budget=[]
    for scope,group in (("当前销售范围",a["selected_budget"]),("公司全部销售",a["company_budget"]["sales"])):
        budget.extend([scope,METRICS[key],*[row[column] for column in ("actual","budget","variance","variance_rate","completion_rate")],DIRECTIONS[row["direction"]]] for key,row in group["totals"].items())
    for key,row in (("expenses",a["company_budget"]["expenses"]["total"]),("operating_profit",a["company_budget"]["operating_profit"])):
        budget.append(["公司全口径",METRICS[key],*[row[column] for column in ("actual","budget","variance","variance_rate","completion_rate")],DIRECTIONS[row["direction"]]])
    sales_detail=[[item["month"],*[display(item.get(field)) if item.get(field) is not None else None for field in budget_dims],item["has_budget"],item["actual_is_complete"],*[item["metrics"][metric][field] for metric in ("net_revenue","gross_margin") for field in ("actual","budget","variance")]] for item in a["selected_budget"]["details"]]
    trend=[[row["start_month"],row["scope"],row["is_complete"],*[row[key] for key in ("net_revenue","net_cost","gross_margin","expenses","operating_profit")]] for row in report["sources"]["monthly"]]
    sheet("实际预算",[section("当月实际与预算",["范围","指标","实际（元）","预算（元）","实际减预算（元）","差异率","完成率","方向"],budget,["text","text","money","money","money","ratio","ratio","text"],[22,22,21,21,24,16,16,14]),
        section("年初至报告月实际",["月份","范围","完整月","净收入（元）","净成本（元）","毛利（元）","公司费用（元）","经营利润（元）"],trend,["date","text","bool"]+["money"]*5),
        section("销售预算组合明细",["月份",*budget_labels,"有预算","完整实际","收入实际（元）","收入预算（元）","收入差额（元）","毛利实际（元）","毛利预算（元）","毛利差额（元）"],sales_detail,["date"]+["text"]*len(budget_dims)+["bool"]*2+["money"]*6)])
    dimension=[]
    for field,label in dim_labels.items():
        revenue={row[field]:row for row in d["selected"]["rankings"][field]}
        margin={row[field]:row for row in contribution_ranking(a["selected_budget"],field,"gross_margin")}
        actual={row[field]:row for row in a["dimensions"][field]}
        for key in sorted(set(revenue)|set(actual)):
            r,g,x=revenue.get(key,{}),margin.get(key,{}),actual.get(key,{})
            dimension.append([label,display(key),r.get("actual",x.get("net_revenue")),g.get("actual",x.get("gross_margin")),x.get("gross_margin_rate"),r.get("budget"),r.get("variance"),r.get("negative_contribution_share"),g.get("budget"),g.get("variance")])
    sheet("维度分析",[section("当前销售范围，贡献比例分母为各负差异绝对值之和",["维度","编码","净收入（元）","毛利（元）","毛利率","收入预算（元）","收入差额（元）","占负向差异比例","毛利预算（元）","毛利差额（元）"],dimension,["text","text","money","money","ratio","money","money","ratio","money","money"])])
    if meta.get('group_by'):
        groups=meta['group_by']
        columns=[*groups,'net_revenue','net_cost','gross_margin','gross_margin_rate','sales_quantity','confirmed_orders']
        sheets[-1]['sections'].append(section('联合分组；跨组订单数不可直接相加',[*[dim_labels[field] for field in groups],'净收入（元）','净成本（元）','毛利（元）','毛利率','成交件数','去重订单数'],[[display(row.get(field)) if field in groups else row.get(field) for field in columns] for row in report['sources'].get('grouped',[])],['text']*len(groups)+['money']*3+['ratio','count','count']))
    summaries,components,details=[],[],[]
    for label,scope,bridge in (("收入桥","当前销售范围",d["selected"]["revenue_bridge"]),("毛利桥","当前销售范围",d["selected"]["gross_margin_bridge"]),("利润桥","公司全口径",d["company_operating_bridge"])):
        summaries.append([label,scope,"完整" if bridge["status"]=="complete" else "不可用","无" if bridge["reason"] is None else REASONS.get(bridge["reason"],bridge["reason"]),bridge["budget"],bridge["actual"],bridge["variance"],bridge["reconciled"],bridge["representation_residual"]])
        components += [[label,scope,row["factor_label"],row["amount"]] for row in bridge["components"]]
        details += [[label,scope,row["factor_label"],row.get("product_id"),row.get("expense_category"),row.get("department"),row.get("channel_scope"),row.get("region_scope"),row["amount"]] for row in bridge["details"]]
    sheet("驱动因素",[section("预算差异桥状态",["模型","范围","状态","不可用原因","预算（元）","实际（元）","差额（元）","精确勾稽","表示尾差（元）"],summaries,["text"]*4+["money"]*3+["bool","check"]),
        section("金额因素",["模型","范围","因素","金额贡献（元）"],components,["text"]*3+["money"],[16,23,44,23]),
        section("因素明细",["模型","范围","因素","商品","费用类别","部门","渠道归属","区域归属","金额贡献（元）"],details,["text"]*8+["money"])])
    annual,monthly,forecast_sales,forecast_fees=[],[],[],[]
    if f:
        for name,item in f["scenarios"].items():
            for scope,key in (("当前销售范围","selected"),("公司全口径","company")):
                for metric in ("net_revenue","gross_margin","expenses","operating_profit"):
                    comparison=item[key+"_budget_comparison"].get(metric,{})
                    annual.append([SCENARIOS[name],scope,METRICS[metric],item[key+"_ytd"][metric],item[key+"_remaining"][metric],item[key+"_annual"][metric],comparison.get("budget"),comparison.get("variance"),comparison.get("completion_rate")])
                past=f["actual_"+key+"_monthly"]
                monthly += [[SCENARIOS[name],scope,row["month"],"实际" if row["kind"]=="actual" else "预测",row["is_available"],row["sales_quantity"],*[row[metric] for metric in ("net_revenue","gross_margin","expenses","operating_profit")]] for row in past+item[key+"_monthly"]]
            forecast_sales += [[SCENARIOS[name],row["month"],*[display(row.get(field)) if field in row else None for field in dims],row["sales_quantity"],row["net_unit_price"],row["unit_cost"],row["sales_revenue"],row["sales_cost"],row["refund_amount"],row["cogs_reversal_amount"]] for period in item["future_periods"] for row in period["sales"] if all(not values or row.get(field) in values for field,values in selection.items) and not any(values and field in period.get("unavailable_dimensions",[]) for field,values in selection.items)]
            forecast_fees += [[SCENARIOS[name],row["month"],row["expense_category"],row["department"],row["channel_scope"],row["region_scope"],row["amount"]] for period in item["future_periods"] for row in period["expense_rows"]]
    sheet("预测结果",[section("四情景为本次计算快照；调整假设后从网页重新导出",["情景","范围","指标","累计实际（元）","剩余预测（元）","全年预测（元）","全年预算（元）","预测减预算（元）","预计完成率"],annual,["text"]*3+["money"]*5+["ratio"]),
        section(meta["forecast_status"],["情景","范围","月份","数据性质","可计算","成交件数","净收入（元）","毛利（元）","公司费用（元）","经营利润（元）"],monthly,["text","text","date","text","bool","count"]+["money"]*4),
        section("未来销售驱动，跟随当前销售筛选",["情景","月份",*[dim_labels[field] for field in dims],"件数","成交单价（元）","单位成本（元）","成交收入（元）","成交成本（元）","退款（元）","成本转回（元）"],forecast_sales,["text","date"]+["text"]*len(dims)+["count"]+["money"]*6),
        section("未来费用保留公司全口径",["情景","月份","类别","部门","渠道归属","区域归属","费用（元）"],forecast_fees,["text","date"]+["text"]*4+["money"])])
    assumptions,scores=[],[]
    if f:
        assumptions=[[SCENARIOS[name],*[item["assumptions"][field] for field in ADJUSTMENTS]] for name,item in f["scenarios"].items()]
        scores=[[METHOD_LABELS[row["method"]],METRICS[row["metric"]],row["n"],row["mae"],row["wape"],row["bias"]] for row in f["backtest"]["scores"]]
    sheet("预测假设",[section("公司全部业务假设；销售筛选只改变展示范围",["情景",*ADJUSTMENTS.values()],assumptions,["text"]+["ratio"]*7,[18]+[22]*7),
        section("历史配对月份回测",["方法","指标","验证月份数","MAE（元）","WAPE","平均偏差（元）"],scores,["text","text","count","money","ratio","money"],[25,24,22,24,20,24]),
        section("模型说明",["项目","设置"],[["实际截止月",meta["month"]],["实际方法",METHOD_LABELS[f["metadata"]["method"]] if f else "不可用"],["窗口",meta["forecast_settings"]["window"]],["选型指标",METRICS[meta["forecast_settings"]["objective"]]],["预测内容身份",report["forecast_content_id"]],["增长倍率范围","0.5—1.8"],["件数规则","非负ROUND_HALF_UP"],["费用模型","佣金随成交收入、物流随件数；营销单独调整；其余近期均值（业务驱动）"],["价格与销量","乘法联动，未估计价格弹性"],["精度","Excel数值为15位有效数字近似；精确金额见配套JSON"]],widths=[25,105])])
    for name,key,columns in (
        ("销售明细","sales",("sale_line_id","order_id","revenue_date","product_id","channel_id","region_id","quantity","sales_amount_before_refund","cogs_amount","period_is_complete")),
        ("退款明细","refunds",("refund_id","sale_line_id","refund_date","revenue_date","product_id","channel_id","region_id","refund_amount","cost_reversal_amount","period_is_complete")),
        ("公司费用","company_expenses",("expense_id","expense_date","expense_category","department","channel_scope","region_scope","amount","period_is_complete"))):
        if key in ('sales','refunds'):
            columns=(*columns,*extra)
        headers={"sale_line_id":"销售明细ID","order_id":"订单ID","revenue_date":"销售确认日","product_id":"商品","channel_id":"渠道","region_id":"区域","quantity":"件数","sales_amount_before_refund":"成交收入（元）","cogs_amount":"历史成交成本（元）","period_is_complete":"完整月来源","refund_id":"退款ID","refund_date":"退款确认日","refund_amount":"退款（元）","cost_reversal_amount":"成本转回（元）","expense_id":"费用ID","expense_date":"费用确认日","expense_category":"费用类别","department":"部门","amount":"费用（元）"}
        headers.update(dim_labels)
        headers.update(channel_scope="渠道归属",region_scope="区域归属")
        types=["date" if column.endswith("_date") else "count" if column=="quantity" else "bool" if column=="period_is_complete" else "money" if column in ("sales_amount_before_refund","cogs_amount","refund_amount","cost_reversal_amount","amount") else "text" for column in columns]
        sections=[section("已知本月明细；完整性标记随来源和月份", [headers[column] for column in columns],[[display(row.get(column)) if column in dims and row.get(column) is not None else row.get(column) for column in columns] for row in report["sources"]["details"][key]],types)]
        if key=="company_expenses":
            sections.append(section("公司费用预算比较（空分类表示该版本未细分）",["月份","类别","部门","渠道归属","区域归属","实际（元）","预算（元）","差异（元）"],[[row.get(field) for field in ("month","expense_category","department","channel_scope","region_scope","actual","budget","variance")] for row in a["company_budget"]["expenses"]["details"]],["date"]+["text"]*4+["money"]*3))
        sheet(name,sections)
    rules=[["数据属性",meta["data_origin"]],["报告版本",report["report_id"]],["企业",meta["entity_id"]],["财务口径",meta["rule_version"]],["报告月份",meta["month"]],["实际覆盖",str(meta["coverage"])],["销售范围",meta["scope_label"]],["金额","人民币不含税元"],["预算版本",meta["budget_version"]],["来源指纹",meta["source_fingerprint"]],["预测内容身份",report["forecast_content_id"]],["训练指纹",f["metadata"]["training_fingerprint"] if f else None],["净收入","确认销售收入减退款确认月事件金额"],["净成本","历史成交成本减当月可回库成本转回"],["经营利润","公司毛利减已建模公司费用；共同费用未分摊"],["零与未知","0是已确认零值；不可用是必要数据缺失"],["刷新方式","本次结果快照，修改假设后在网页重新生成"],["点评","固定模板引用计算事实，待验证建议单列"],["原始来源","已校验的标准销售、退款、费用和预算；来源数据库只读"]]
    if meta.get('quantity_basis')=='one_per_row':
        rules.append(['数量默认方式',meta['quantity_note']])
    if 'group_by' in meta:
        rules.extend([['联合分组顺序',' → '.join(dim_labels[field] for field in meta['group_by'])],['可用分类','、'.join(dim_labels.values())],['预算粒度','、'.join(budget_labels)],['预测建模粒度','、'.join(dim_labels[field] for field in meta.get('model_dimensions',dims))]])
    ledger=[[row["fact_id"],row["scope"],row["period"],"比例小数" if row["unit"]=="ratio" else "元",row["value"],"/".join(map(str,row["source_path"]))] for row in report["commentary"]["facts"]]
    sheet("口径与追溯",[section("定义与来源",["项目","说明"],rules,widths=[25,105]),section("点评事实清单",["事实ID","范围","报告月","单位","原值","结果包路径"],ledger,["text","text","date","text","number","text"],[16,33,18,18,24,105])])
    history=report['sources'].get('historical')
    if history:
        target=next(item for item in sheets if item['name']=='驱动因素')
        hrows=[]
        for label,key in [('净收入','revenue_bridge'),('毛利','gross_margin_bridge'),('经营利润（仅公司）','operating_bridge')]:
            value=history[key]
            hrows.append([label,history['metadata']['base_month'],value['base'],value['actual'],value['variance'],value['status'],value['reason']])
        target['sections'].append(section('历史实际对比；基期不是预算',['指标','历史基期','基期实际（元）','本期实际（元）','本期减基期（元）','状态','不可用原因'],hrows,['text','date']+['money']*3+['text']*2))
        target['sections'].append(section('历史净收入差异分解',['因素','贡献（元）'],[[row['factor_label'],row['amount']] for row in history['revenue_bridge']['components']],['text','money']))
    work=report['sources'].get('workflow')
    if work:
        target=next(item for item in sheets if item['name']=='口径与追溯')
        close=work.get('month_confirmation')
        state='未确认' if not close else '确认后实际已变更' if close['actual_changed'] else '已确认，实际一致'
        target['sections'].append(section('财务工作快照',['项目','记录'],[['月份状态',state],['确认人',close['actor'] if close else None],['独立参考来源',work['reconciliation'].get('reference_source')],['参考核对人',work['reconciliation'].get('reference_actor')],['本机工作区身份',work['context']]],widths=[25,105]))
        target['sections'].append(section('对账；来源读取、标准明细和计算结果独立勾稽',['指标','来源读取（元）','标准明细（元）','分析结果（元）','内部状态','独立参考（元）','实际减参考（元）','外部状态'],[[r[k] for k in ('指标','来源读取合计（元）','标准明细合计（元）','分析结果（元）','内部勾稽','独立参考（元）','实际减参考（元）','外部核对')] for r in work['reconciliation']['rows']],['text']+['money']*3+['text','money','money','text']))
        target['sections'].append(section('异常与人工跟进；人工说明单列，非系统核实结论',['月份','系统事实','记录范围','处理状态','负责人','原因核实状态','人工原因','核实依据','行动','截止日','处理结果','复盘月份','复盘结论'],[[r['month'],r['facts']['title'],r.get('scope_label'),r['status'],*[r['notes'].get(field) for field in ('owner','cause_status','cause','evidence','action','due_date','resolution','review_month','review_result')]] for r in work['issues']],widths=[16,42,60,18,20,20,60,60,60,18,60,18,60]))
    return sheets
