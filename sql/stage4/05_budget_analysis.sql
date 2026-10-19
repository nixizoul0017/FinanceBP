-- 查询9：逐商品/渠道/区域实际与预算；NULL预算不是零预算。
WITH comparison AS (
 SELECT *,CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN actual_net_revenue END AS covered_actual_revenue,
 CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN actual_gross_margin END AS covered_actual_margin
 FROM vw_sales_budget_comparison WHERE month=@analysis_month AND budget_version=@budget_version
)
SELECT product_id,channel_code,region_code,covered_actual_revenue AS actual_revenue,
ROUND(budget_net_revenue,2) AS budget_revenue,ROUND(covered_actual_revenue-budget_net_revenue,2) AS revenue_variance,
CASE WHEN budget_net_revenue>0 THEN ROUND(100*(covered_actual_revenue-budget_net_revenue)/budget_net_revenue,2) END AS variance_pct,
CASE WHEN budget_net_revenue>0 THEN ROUND(100*covered_actual_revenue/budget_net_revenue,2) END AS completion_pct,
covered_actual_margin AS actual_margin,ROUND(budget_gross_margin,2) AS budget_margin,
CASE WHEN @analysis_month NOT BETWEEN @actual_start_month AND @actual_end_month THEN 'ACTUAL_NOT_COMPLETE'
WHEN has_budget=0 THEN 'MISSING_BUDGET' WHEN budget_net_revenue<=0 THEN 'NONPOSITIVE_BUDGET' ELSE 'COMPARABLE' END AS comparison_status
FROM comparison ORDER BY revenue_variance,product_id,channel_code,region_code;

-- 查询10：费用增加通常不利，收入增加通常有利，不能用同一种颜色/方向解释。
WITH comparison AS (
 SELECT *,CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN actual_expense END AS covered_actual_expense
 FROM vw_expense_budget_comparison WHERE month=@analysis_month AND budget_version=@budget_version
)
SELECT expense_category,department,channel_scope,region_scope,covered_actual_expense AS actual_expense,budget_amount,
covered_actual_expense-budget_amount AS expense_variance,
CASE WHEN budget_amount>0 THEN ROUND(100*(covered_actual_expense-budget_amount)/budget_amount,2) END AS variance_pct,
CASE WHEN covered_actual_expense IS NULL THEN 'ACTUAL_NOT_COMPLETE' WHEN has_budget=0 THEN 'MISSING_BUDGET'
WHEN covered_actual_expense>budget_amount THEN 'UNFAVORABLE' WHEN covered_actual_expense<budget_amount THEN 'FAVORABLE' ELSE 'ON_BUDGET' END AS direction
FROM comparison ORDER BY expense_category,department,channel_scope,region_scope;

-- 查询11：公司比较。如果有实际维度缺预算，对应预算合计标为NULL，防止用部分预算比较全公司实际。
WITH budget_sales_total AS (
 SELECT SUM(budget_net_revenue) AS revenue,SUM(budget_net_cost) AS cost,SUM(budget_gross_margin) AS margin
 FROM vw_budget_sales_metrics WHERE month=@analysis_month AND budget_version=@budget_version
),budget_fees_total AS (
 SELECT SUM(budget_amount) AS fees FROM budget_expenses WHERE month=@analysis_month AND budget_version=@budget_version
),missing AS (
 SELECT (SELECT COUNT(*) FROM vw_sales_budget_comparison WHERE month=@analysis_month AND budget_version=@budget_version AND has_actual_record=1 AND has_budget=0) AS sales_rows,
 (SELECT COUNT(*) FROM vw_expense_budget_comparison WHERE month=@analysis_month AND budget_version=@budget_version AND has_actual_record=1 AND has_budget=0) AS expense_rows
),company AS (
 SELECT @analysis_month AS month,
 CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(a.net_revenue,0) END AS actual_revenue,
 CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(a.gross_margin,0) END AS actual_margin,
 CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(a.expense_amount,0) END AS actual_expenses,
 CASE WHEN @analysis_month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(a.operating_profit,0) END AS actual_profit,
 CASE WHEN m.sales_rows=0 THEN b.revenue END AS budget_revenue,
 CASE WHEN m.sales_rows=0 THEN b.margin END AS budget_margin,
 CASE WHEN m.expense_rows=0 THEN f.fees END AS budget_expenses,
 CASE WHEN m.sales_rows=0 AND m.expense_rows=0 THEN b.margin-f.fees END AS budget_profit,
 m.sales_rows AS missing_sales_budget_rows,m.expense_rows AS missing_expense_budget_rows
 FROM (SELECT @analysis_month AS month) target LEFT JOIN vw_monthly_company a ON a.month=target.month
 CROSS JOIN budget_sales_total b CROSS JOIN budget_fees_total f CROSS JOIN missing m
)
SELECT *,ROUND(actual_revenue-budget_revenue,2) AS revenue_variance,
ROUND(actual_margin-budget_margin,2) AS margin_variance,ROUND(actual_expenses-budget_expenses,2) AS expense_variance,
ROUND(actual_profit-budget_profit,2) AS profit_variance,
CASE WHEN budget_revenue>0 THEN ROUND(100*actual_revenue/budget_revenue,2) END AS revenue_completion_pct
FROM company;

SELECT @budget_version AS selected_version,
IF(EXISTS(SELECT 1 FROM budget_sales WHERE budget_version=@budget_version)
OR EXISTS(SELECT 1 FROM budget_expenses WHERE budget_version=@budget_version),'KNOWN_VERSION','MISSING_VERSION') AS version_status;

