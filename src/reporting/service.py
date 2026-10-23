"""组装已计算结果；文字引用事实清单，不推断业务因果。"""
from copy import deepcopy
from datetime import date
from decimal import Decimal

from analysis.metrics import Filters, month_date, month_range
from analysis.service import analysis_pack
from analysis.variance import variance_pack
from analysis.forecast import forecast_base
from analysis.scenario import forecast_pack, Assumptions
from analysis.forecast_store import content_digest
from dashboard.view_model import detail_tables, money_text, percent_text

METRICS={"net_revenue":"净收入","net_cost":"净成本","gross_margin":"毛利","gross_margin_rate":"毛利率","expenses":"公司费用","operating_profit":"经营利润"}
SCENARIOS={"base":"基础","optimistic":"乐观","cautious":"谨慎","custom":"自定义"}
ISSUES={"historic_cost_missing":"历史成本缺失","refund_source_missing":"退款来源未提供","expense_source_missing":"费用来源未提供"}
REASONS={"actual_incomplete":"实际月份不完整","budget_incomplete":"预算覆盖不足","historic_cost_missing":"历史成本缺失","budget_cost_missing":"预算成本缺失","refund_source_missing":"退款来源未提供","expense_source_missing":"费用来源未提供","expense_budget_incomplete":"费用预算覆盖不足","quantity_unit_unconfirmed":"件数口径未确认"}
REASONS.update(budget_drivers_missing='金额预算没有销量价格驱动，不能做PVM',product_grain_unavailable='预算未细分到商品')


def scope_label(filters,registry=None):
    labels={'product_id':'商品','channel_id':'渠道','region_id':'区域',**{x['id']:x['label'] for x in registry or []}}
    from etl.dimensions import display
    return '公司全部销售' if filters.is_company else '；'.join(labels.get(field,field)+':'+','.join(display(value) for value in values) for field,values in filters.items if values)


def value_at(sources,path):
    value=sources
    for key in path:
        value=value[key]
    return value


def render_statement(statement,facts):
    rendered=[]
    for fact_id in statement["fact_ids"]:
        item=facts[fact_id]
        rendered.append(percent_text(item["value"]) if item["unit"]=="ratio" else money_text(item["value"])+"元")
    return statement["template"].format(*rendered)


def commentary(sources):
    analysis,drivers,forecast=(sources[name] for name in ("analysis","drivers","forecast"))
    facts,statements={},[]
    def add(section,template,paths,unit="yuan",scope="当前销售范围",kind="事实"):
        # 所需事实缺一个就不生成该句，不把未知替换为零。
        values=[value_at(sources,path) for path in paths]
        if any(value is None for value in values):
            return
        ids=[]
        for path,value in zip(paths,values):
            fact_id="F"+str(len(facts)+1).zfill(3)
            facts[fact_id]={"fact_id":fact_id,"scope":scope,"period":analysis["metadata"]["month"],"unit":unit,"value":value,"source_path":path}
            ids.append(fact_id)
        row={"section":section,"kind":kind,"template":template,"fact_ids":ids}
        row["text"]=render_statement(row,facts)
        statements.append(row)
    def note(section,text,kind="限制"):
        statements.append({"section":section,"kind":kind,"template":text,"text":text,"fact_ids":[]})
    add("本月表现","当前销售范围净收入{0}，毛利{1}。",[["analysis","selected_scope",field] for field in ("net_revenue","gross_margin")])
    if analysis["selected_scope"]["net_revenue"] is not None and analysis["selected_scope"]["gross_margin"] is None:
        add("本月表现","当前销售范围净收入{0}；毛利缺少必要数据。",[["analysis","selected_scope","net_revenue"]])
    add("本月表现","公司全口径费用{0}，经营利润{1}。",[["analysis","company_scope",field] for field in ("expenses","operating_profit")],scope="公司全口径")
    if analysis["company_scope"]["expenses"] is not None and analysis["company_scope"]["operating_profit"] is None:
        add("本月表现","公司费用{0}；经营利润缺少必要数据。",[["analysis","company_scope","expenses"]],scope="公司全口径")
    for key,label in (("mom","环比"),("yoy","同比")):
        result=analysis["selected_trends"][key]["net_revenue"]
        add("趋势",f"当前销售范围净收入{label}金额变化{{0}}。",[["analysis","selected_trends",key,"net_revenue","change_amount"]])
        if result["change_rate"] is not None:
            add("趋势",f"当前销售范围净收入{label}变化率{{0}}。",[["analysis","selected_trends",key,"net_revenue","change_rate"]],unit="ratio")
        else:
            note("趋势",f"净收入{label}比率不可用：当前值/历史基期缺失或基期非正。")
    for field in ("net_revenue","gross_margin"):
        label=METRICS[field]
        add("预算",f"当前销售范围{label}预算{{0}}，实际减预算{{1}}。",[["analysis","selected_budget","totals",field,column] for column in ("budget","variance")])
    add("预算","公司经营利润实际减预算{0}。",[["analysis","company_budget","operating_profit","variance"]],scope="公司全口径")
    if analysis["selected_budget"]["status"]!="complete":
        note("预算","当前销售筛选维度缺少可比预算，预算、完成率与差异不可用；不分摊公司预算。" if analysis["selected_budget"]["status"]=="unsupported_dimensions" else "当前销售范围预算缺失或覆盖不足，无法确认合计预算和完成率。")
    model=drivers["selected"]["revenue_bridge"]
    if model["status"]=="complete":
        negative=sorted(((index,row) for index,row in enumerate(model["components"]) if row["amount"]<0),key=lambda pair:pair[1]["amount"])
        for index,row in negative[:3]:
            add("驱动因素",f"净收入预算差异中，{row['factor_label']}金额贡献{{0}}。",[["drivers","selected","revenue_bridge","components",index,"amount"]],kind="金额分解")
        if not negative:
            note("驱动因素","当前收入桥没有负向金额因素。")
    else:
        note("驱动因素","收入驱动拆解不可用："+REASONS.get(model["reason"],"必要输入不完整")+"。")
    for dimension in drivers["selected"]["rankings"]:
        label=sources.get("dimension_labels",{}).get(dimension,{"product_id":"商品","channel_id":"渠道","region_id":"区域"}.get(dimension,dimension))
        ranking=drivers["selected"]["rankings"][dimension]
        known=all(row["variance"] is not None for row in ranking)
        negative=[(index,row) for index,row in enumerate(ranking) if row["variance"] is not None and row["variance"]<0]
        if known and negative:
            index,row=min(negative,key=lambda pair:pair[1]["variance"])
            code=str(row[dimension]).replace("{","{{").replace("}","}}")
            add("维度贡献",f"{label}{code}的净收入负差异最大，实际减预算{{0}}。",[["drivers","selected","rankings",dimension,index,"variance"]])
    if forecast is not None:
        for name in SCENARIOS:
            add("全年预测",f"{SCENARIOS[name]}情景：当前范围全年净收入{{0}}，公司全年经营利润{{1}}。",[["forecast","scenarios",name,"selected_annual","net_revenue"],["forecast","scenarios",name,"company_annual","operating_profit"]],scope="销售范围及公司利润分别标注",kind="模型测算")
            if forecast["scenarios"][name]["selected_annual"]["net_revenue"] is not None and forecast["scenarios"][name]["company_annual"]["operating_profit"] is None:
                add("全年预测",f"{SCENARIOS[name]}情景：当前范围全年净收入{{0}}；公司经营利润预测缺少必要数据。",[["forecast","scenarios",name,"selected_annual","net_revenue"]],kind="模型测算")
        note("全年预测","未来结果取决于历史模型及情景假设，不能视为已发生实际。")
    else:
        note("全年预测","本报告没有可用预测，原因见预测状态；不补造全年数字。")
    current=analysis["selected_scope"]
    if not current["is_complete"]:
        note("数据限制","所选月份不是已确认完整实际，已观察明细仅供核对。")
    for issue in sorted(set(current["data_issues"]+analysis["company_scope"]["data_issues"])):
        note("数据限制",ISSUES.get(issue,"必要来源缺失")+"，相关指标保持未知。")
    note("口径","公司费用未分摊，筛选后的销售毛利不能减全公司费用形成维度利润。")
    note("调查建议","建议对负向维度核实活动、供货、渠道组合与成交定价记录；金额分解不能证明业务因果。","待验证建议")
    note("调查建议","建议核对退款确认日期、可回库记录和费用合同，确认后再调整未来经营假设。","待验证建议")
    return {"mode":"verified_template","facts":list(facts.values()),"statements":statements}


def validate_report(report):
    """核对点评引用、文字与其计算来源；验证失败不可导出。"""
    facts={row["fact_id"]:row for row in report["commentary"]["facts"]}
    if len(facts)!=len(report["commentary"]["facts"]):
        raise ValueError("点评事实身份重复")
    for fact in facts.values():
        value=value_at(report["sources"],fact["source_path"])
        if value is None or value!=fact["value"] or not Decimal(str(value)).is_finite():
            raise ValueError("点评事实与来源不一致")
    for row in report["commentary"]["statements"]:
        if row["text"]!=render_statement(row,facts):
            raise ValueError("点评文字或数字被改变")
    metadata=report["metadata"]
    for name in ('workflow','historical'):
        item=report['sources'].get(name)
        if item is not None:
            if content_digest(item)!=metadata.get(name+'_hash'):
                raise ValueError('财务工作记录或历史比较快照已变化')
            meta=item.get('metadata',item)
            if meta.get('entity_id')!=metadata['entity_id'] or str(meta.get('month'))[:7]!=str(metadata['month'])[:7]:
                raise ValueError('财务工作记录或历史比较期间不一致')
            if name=='historical' and (meta.get('sales_filters')!=metadata['sales_filters'] or meta.get('source_fingerprint')!=metadata['source_fingerprint']):
                raise ValueError('历史比较范围或来源不一致')
    for name in ("analysis","drivers","forecast"):
        pack=report["sources"][name]
        if pack is None:
            continue
        meta=pack["metadata"]
        if any(meta.get(field)!=metadata[field] for field in ("entity_id","rule_version","source_fingerprint","budget_version")):
            raise ValueError("报告来源身份不一致")
        if month_date(meta.get("cutoff_month",meta.get("month")))!=month_date(metadata["month"]):
            raise ValueError("报告期间不一致")
        selected=meta.get("sales_filters",meta.get("filters"))
        if selected!=metadata["sales_filters"]:
            raise ValueError("报告销售范围不一致")
        if name=="forecast" and any(meta.get(field)!=metadata["forecast_settings"][setting] for field,setting in (("requested_method","method"),("window","window"),("selection_metric","objective"))):
            raise ValueError("报告预测设置不一致")
    return {"status":"passed","fact_count":len(facts),"statement_count":len(report["commentary"]["statements"])}


def build_report(engine,month,filters=Filters(),version="B2026_V1",*,method="auto",window=3,objective="net_revenue",assumptions=Assumptions(),data_origin="来源属性待确认",analysis=None,drivers=None,base=None,group_by=None,workflow=None,historical=None):
    month=month_date(month)
    analysis=deepcopy(analysis) if analysis is not None else analysis_pack(engine,month,filters,version)
    drivers=deepcopy(drivers) if drivers is not None else variance_pack(engine,month,filters,version)
    forecast=None
    forecast_status="所选月份不是完整实际截止月" if not engine.is_complete(month) else "件数口径未确认" if engine.metadata.get("semantics",{}).get("quantity_unit")!="件" else None
    if forecast_status is None:
        base=deepcopy(base) if base is not None else forecast_base(engine,month,method,window,version,objective)
        forecast=forecast_pack(base,filters,assumptions)
        forecast_status="已生成；缺历史或必要来源的指标保持未知"
    monthly=[]
    for current in month_range(date(month.year,1,1),month):
        monthly.extend([{**engine.summary(current,filters=selection),"scope":scope} for selection,scope in ((filters,"当前销售范围"),(Filters(),"公司全口径"))])
    details={name:frame.to_dict("records") for name,frame in detail_tables(engine,month,filters).items()}
    sources={"analysis":analysis,"drivers":drivers,"forecast":forecast,"monthly":monthly,"details":details}
    result={"metadata":{"report_version":"monthly_report_v1","entity_id":engine.entity_id,"rule_version":engine.metadata["rule_version"],"source_fingerprint":engine.metadata.get("source_fingerprint"),"coverage":engine.metadata["coverage"],"month":month,"budget_version":version,"sales_filters":filters.as_dict(),"scope_label":scope_label(filters,engine.registry if len(engine.dimension_ids)>3 else None),"amount_unit":"人民币不含税元","data_origin":data_origin,"commentary_mode":"固定模板，引用已计算事实","forecast_status":forecast_status,"forecast_settings":{"method":method,"window":window,"objective":objective}},"sources":sources,"commentary":commentary(sources)}
    if engine.metadata.get('quantity_basis')=='one_per_row':
        result['metadata'].update(quantity_basis='one_per_row',quantity_note='未提供成交数量列，每条明细默认按1计数，非来源实际商品件数')
    if len(engine.dimension_ids)>3 or group_by is not None:
        groups=tuple(group_by) if group_by is not None else ('product_id',)
        grouped=engine.dimensions(month,by=groups,filters=filters).to_dict('records') if groups else []
        result['metadata'].update(dimension_registry=deepcopy(engine.registry),group_by=list(groups),scope_label=scope_label(filters,engine.registry),budget_dimensions=list(engine.budget_dimensions(version)),model_dimensions=engine.metadata.get('forecast_dimensions',list(engine.dimension_ids)))
        sources['grouped']=grouped
        sources['dimension_labels']=engine.dimension_labels
        result['commentary']=commentary(sources)
    for name,item in [('workflow',workflow),('historical',historical)]:
        if item is not None:
            sources[name]=deepcopy(item)
            result['metadata'][name+'_hash']=content_digest(item)
    if engine.metadata.get('local_budgets'):
        result['metadata']['budget_dimensions']=list(engine.budget_dimensions(version))
        result['metadata']['budget_label']=engine.metadata.get('budget_labels',{}).get(version,version)
    result["validation"]=validate_report(result)
    # 相同计算快照可复用下载，不把生成时间放入内容身份。
    result["report_id"]="R10_"+content_digest(result)[:24]
    result["forecast_content_id"]="FC9_"+content_digest(forecast)[:24] if forecast else None
    return result


def markdown_report(report):
    validate_report(report)
    meta=report["metadata"]
    rows=[f"# {meta['entity_id']} 经营月报 {str(meta['month'])[:7]}","",f"{meta['data_origin']}。{meta['amount_unit']}。销售范围：{meta['scope_label']}。预算：{meta['budget_version']}。",""]
    previous=None
    for statement in report["commentary"]["statements"]:
        if statement["section"]!=previous:
            rows.extend(["", "## "+statement["section"],""])
            previous=statement["section"]
        text=statement["text"]
        if statement["fact_ids"]:
            text+=" （依据："+",".join(statement["fact_ids"])+"）"
        rows.append(text)
    history=report['sources'].get('historical')
    if history:
        rows.extend(['','## 历史实际差异解释','',f"基期：{str(history['metadata']['base_month'])[:7]}；比较方式：{history['metadata']['mode']}。"])
        for row in history['revenue_bridge']['components']:
            rows.append(row['factor_label']+'：'+money_text(row['amount'])+'元。')
    work=report['sources'].get('workflow')
    if work:
        close=work.get('month_confirmation')
        state='未确认' if not close else '确认后数据已变更' if close['actual_changed'] else '已确认且当前实际一致'
        rows.extend(['','## 对账与人工跟进','',f"月份状态：{state}。独立参考来源：{work['reconciliation'].get('reference_source') or '未填写'}。"])
        for issue in work['issues']:
            notes=issue['notes']
            rows.append(f"{issue['facts']['title']}；记录范围：{issue.get('scope_label','见配套JSON')}；状态：{issue['status']}；负责人：{notes.get('owner','未填写')}；人工原因（{notes.get('cause_status','待核实')}）：{notes.get('cause','未填写')}；行动：{notes.get('action','未填写')}；核实依据：{notes.get('evidence','未填写')}；复盘：{notes.get('review_result','未填写')}。")
    rows.extend(["",f"报告版本：{report['report_id']}。预测内容：{report['forecast_content_id'] or '不可用'}。", "调整假设后从网页重新生成；Excel与本点评为本次结果快照。",""])
    return "\n".join(rows)
