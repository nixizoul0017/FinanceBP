-- 本文件仅创建/更新本项目分析视图，不改写10张原始业务表。
USE finance_bp_stage3;

-- 一行一条已确认销售明细。先不连接退款、费用或预算。
CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_confirmed_sales_detail AS
SELECT o.order_id,i.order_item_id,o.recognized_date,
DATE_SUB(o.recognized_date,INTERVAL (DAY(o.recognized_date)-1) DAY) AS month,
i.product_id,p.product_name,p.category,o.channel_code,o.region_code,
i.quantity,i.unit_list_price,i.discount_amount,i.unit_cost_snapshot,
i.quantity*i.unit_list_price-i.discount_amount AS sales_revenue,
i.quantity*i.unit_cost_snapshot AS sales_cost
FROM orders o JOIN order_items i ON i.order_id=o.order_id
JOIN products p ON p.product_id=i.product_id
WHERE o.order_status='completed';

-- 一行：月×商品×渠道×区域。销售和退款分别按自己的发生月份聚合。
CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_monthly_sales AS
SELECT month,product_id,channel_code,region_code,SUM(quantity) AS sales_quantity,
SUM(sales_revenue) AS sales_revenue,SUM(sales_cost) AS sales_cost
FROM vw_confirmed_sales_detail GROUP BY month,product_id,channel_code,region_code;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_monthly_returns AS
SELECT DATE_SUB(r.refund_date,INTERVAL (DAY(r.refund_date)-1) DAY) AS month,
i.product_id,o.channel_code,o.region_code,
SUM(r.returned_quantity) AS returned_quantity,SUM(r.recoverable_quantity) AS recoverable_quantity,
SUM(r.refund_amount) AS refund_amount,SUM(r.cogs_reversal_amount) AS cogs_reversal_amount
FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
JOIN orders o ON o.order_id=i.order_id WHERE o.order_status='completed'
GROUP BY month,i.product_id,o.channel_code,o.region_code;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_monthly_financials AS
WITH dimension_keys AS (
 SELECT month,product_id,channel_code,region_code FROM vw_monthly_sales
 UNION SELECT month,product_id,channel_code,region_code FROM vw_monthly_returns
)
SELECT k.month,k.product_id,k.channel_code,k.region_code,
COALESCE(s.sales_quantity,0) AS sales_quantity,COALESCE(r.returned_quantity,0) AS returned_quantity,
COALESCE(s.sales_quantity,0)-COALESCE(r.returned_quantity,0) AS net_quantity,
COALESCE(s.sales_revenue,0) AS sales_revenue,COALESCE(r.refund_amount,0) AS refund_amount,
COALESCE(s.sales_cost,0) AS sales_cost,COALESCE(r.cogs_reversal_amount,0) AS cogs_reversal_amount,
COALESCE(s.sales_revenue,0)-COALESCE(r.refund_amount,0) AS net_revenue,
COALESCE(s.sales_cost,0)-COALESCE(r.cogs_reversal_amount,0) AS net_cost,
COALESCE(s.sales_revenue,0)-COALESCE(r.refund_amount,0)-COALESCE(s.sales_cost,0)+COALESCE(r.cogs_reversal_amount,0) AS gross_margin
FROM dimension_keys k LEFT JOIN vw_monthly_sales s
ON s.month=k.month AND s.product_id=k.product_id AND s.channel_code=k.channel_code AND s.region_code=k.region_code
LEFT JOIN vw_monthly_returns r
ON r.month=k.month AND r.product_id=k.product_id AND r.channel_code=k.channel_code AND r.region_code=k.region_code;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_monthly_expenses AS
SELECT DATE_SUB(expense_date,INTERVAL (DAY(expense_date)-1) DAY) AS month,
expense_category,department,COALESCE(channel_code,'ALL') AS channel_scope,COALESCE(region_code,'ALL') AS region_scope,
SUM(amount) AS expense_amount FROM expenses
GROUP BY month,expense_category,department,channel_scope,region_scope;

-- 公司级：订单数从明细去重算，不能把商品组里的订单数相加。
CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_monthly_company AS
WITH financials AS (
 SELECT month,SUM(sales_quantity) AS sales_quantity,SUM(sales_revenue) AS sales_revenue,
 SUM(refund_amount) AS refund_amount,SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin
 FROM vw_monthly_financials GROUP BY month
),fees AS (SELECT month,SUM(expense_amount) AS expense_amount FROM vw_monthly_expenses GROUP BY month),
order_counts AS (SELECT month,COUNT(DISTINCT order_id) AS confirmed_orders FROM vw_confirmed_sales_detail GROUP BY month),
month_keys AS (SELECT month FROM financials UNION SELECT month FROM fees)
SELECT k.month,COALESCE(f.sales_quantity,0) AS sales_quantity,COALESCE(f.sales_revenue,0) AS sales_revenue,
COALESCE(f.refund_amount,0) AS refund_amount,COALESCE(f.net_revenue,0) AS net_revenue,
COALESCE(f.net_cost,0) AS net_cost,COALESCE(f.gross_margin,0) AS gross_margin,
COALESCE(e.expense_amount,0) AS expense_amount,COALESCE(f.gross_margin,0)-COALESCE(e.expense_amount,0) AS operating_profit,
COALESCE(c.confirmed_orders,0) AS confirmed_orders
FROM month_keys k LEFT JOIN financials f ON f.month=k.month LEFT JOIN fees e ON e.month=k.month
LEFT JOIN order_counts c ON c.month=k.month;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_budget_sales_metrics AS
SELECT budget_version,month,product_id,channel_code,region_code,budget_quantity,
budget_quantity*budget_net_unit_price-budget_refund_amount AS budget_net_revenue,
budget_quantity*budget_unit_cost-budget_cogs_reversal_amount AS budget_net_cost,
budget_quantity*budget_net_unit_price-budget_refund_amount-budget_quantity*budget_unit_cost+budget_cogs_reversal_amount AS budget_gross_margin
FROM budget_sales;

-- 日历先补齐；未载入月份保留为未知，不从该原始视图推断“完整实际”。
CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_calendar_company AS
SELECT c.month,f.sales_quantity,f.sales_revenue,f.refund_amount,f.net_revenue,f.net_cost,
f.gross_margin,f.expense_amount,f.operating_profit,f.confirmed_orders
FROM (SELECT DISTINCT month_start AS month FROM dim_date) c LEFT JOIN vw_monthly_company f ON f.month=c.month;

-- 对每个已存在预算版本保留实际和预算双方的键；缺预算仍保留NULL。
CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_sales_budget_comparison AS
WITH versions AS (
 SELECT budget_version FROM budget_sales UNION SELECT budget_version FROM budget_expenses
),comparison_keys AS (
 SELECT v.budget_version,a.month,a.product_id,a.channel_code,a.region_code
 FROM versions v CROSS JOIN vw_monthly_financials a
 UNION SELECT budget_version,month,product_id,channel_code,region_code FROM budget_sales
)
SELECT k.budget_version,k.month,k.product_id,k.channel_code,k.region_code,
(a.product_id IS NOT NULL) AS has_actual_record,(b.budget_version IS NOT NULL) AS has_budget,
COALESCE(a.net_revenue,0) AS actual_net_revenue,COALESCE(a.net_cost,0) AS actual_net_cost,
COALESCE(a.gross_margin,0) AS actual_gross_margin,b.budget_net_revenue,b.budget_net_cost,b.budget_gross_margin
FROM comparison_keys k LEFT JOIN vw_monthly_financials a
ON a.month=k.month AND a.product_id=k.product_id AND a.channel_code=k.channel_code AND a.region_code=k.region_code
LEFT JOIN vw_budget_sales_metrics b ON b.budget_version=k.budget_version AND b.month=k.month
AND b.product_id=k.product_id AND b.channel_code=k.channel_code AND b.region_code=k.region_code;

CREATE OR REPLACE SQL SECURITY INVOKER VIEW vw_expense_budget_comparison AS
WITH versions AS (
 SELECT budget_version FROM budget_sales UNION SELECT budget_version FROM budget_expenses
),comparison_keys AS (
 SELECT v.budget_version,a.month,a.expense_category,a.department,a.channel_scope,a.region_scope
 FROM versions v CROSS JOIN vw_monthly_expenses a
 UNION SELECT budget_version,month,expense_category,department,channel_scope,region_scope FROM budget_expenses
)
SELECT k.budget_version,k.month,k.expense_category,k.department,k.channel_scope,k.region_scope,
(a.department IS NOT NULL) AS has_actual_record,(b.budget_version IS NOT NULL) AS has_budget,
COALESCE(a.expense_amount,0) AS actual_expense,b.budget_amount
FROM comparison_keys k LEFT JOIN vw_monthly_expenses a ON a.month=k.month
AND a.expense_category=k.expense_category AND a.department=k.department AND a.channel_scope=k.channel_scope AND a.region_scope=k.region_scope
LEFT JOIN budget_expenses b ON b.budget_version=k.budget_version AND b.month=k.month
AND b.expense_category=k.expense_category AND b.department=k.department AND b.channel_scope=k.channel_scope AND b.region_scope=k.region_scope;

SELECT 'ANALYSIS_VIEWS_READY' AS result,COUNT(*) AS view_count
FROM information_schema.views WHERE table_schema=DATABASE() AND table_name IN
('vw_confirmed_sales_detail','vw_monthly_sales','vw_monthly_returns','vw_monthly_financials',
'vw_monthly_expenses','vw_monthly_company','vw_budget_sales_metrics','vw_calendar_company',
'vw_sales_budget_comparison','vw_expense_budget_comparison');

