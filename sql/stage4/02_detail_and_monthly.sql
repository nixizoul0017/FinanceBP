-- 查询1：明细收入成本。9月9条明细、8个订单。
SELECT order_id,order_item_id,product_name,quantity,sales_revenue,sales_cost,
sales_revenue-sales_cost AS margin_before_refunds
FROM vw_confirmed_sales_detail WHERE month=@analysis_month ORDER BY order_id,order_item_id;

-- 查询2：公司月度指标，完整载入范围外显示NULL。
WITH report AS (
 SELECT month,CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN 'COMPLETE' ELSE 'NOT_COMPLETE' END AS coverage,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(sales_revenue,0) END AS sales_revenue,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(refund_amount,0) END AS refund_amount,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(net_revenue,0) END AS net_revenue,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(net_cost,0) END AS net_cost,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(gross_margin,0) END AS gross_margin,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(expense_amount,0) END AS expense_amount,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(operating_profit,0) END AS operating_profit,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(confirmed_orders,0) END AS confirmed_orders
 FROM vw_calendar_company
)
SELECT *,CASE WHEN net_revenue>0 THEN ROUND(100*gross_margin/net_revenue,2) END AS gross_margin_pct,
CASE WHEN net_revenue>0 THEN ROUND(100*expense_amount/net_revenue,2) END AS expense_pct
FROM report WHERE month=@analysis_month;

-- 查询3：仅查看10月边界事件，明确不作为10月完整经营报告。
SELECT 'CROSS_MONTH_BOUNDARY_ONLY' AS scope,month,net_revenue,net_cost,gross_margin
FROM vw_monthly_financials WHERE month='2026-10-01';

