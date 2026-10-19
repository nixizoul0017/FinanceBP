-- 只读参数化查询；确认完整月、销售/退款来源及历史成本齐全、单一件数口径后使用。
-- :month 每月1日，:version 固定预算版本；维度参数NULL表示全部。
-- 销售/退款各自先按月×商品×渠道×区域汇总，再对齐预算，防止重复累计。
WITH sales AS (
 SELECT i.product_id,o.channel_code,o.region_code,SUM(i.quantity) AS q,
 SUM(i.quantity*i.unit_list_price-i.discount_amount) AS revenue,
 SUM(i.quantity*i.unit_cost_snapshot) AS cost
 FROM orders o JOIN order_items i ON i.order_id=o.order_id
 WHERE o.order_status='completed' AND o.recognized_date>=:month
 AND o.recognized_date<DATE_ADD(:month,INTERVAL 1 MONTH)
 GROUP BY i.product_id,o.channel_code,o.region_code
), refunds AS (
 SELECT i.product_id,o.channel_code,o.region_code,SUM(r.refund_amount) AS refund,
 SUM(r.cogs_reversal_amount) AS reversal
 FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
 JOIN orders o ON o.order_id=i.order_id
 WHERE o.order_status='completed' AND r.refund_date>=:month
 AND r.refund_date<DATE_ADD(:month,INTERVAL 1 MONTH)
 GROUP BY i.product_id,o.channel_code,o.region_code
), budget AS (
 SELECT * FROM budget_sales WHERE month=:month AND budget_version=:version
), all_keys AS (
 SELECT product_id,channel_code,region_code FROM sales
 UNION SELECT product_id,channel_code,region_code FROM refunds
 UNION SELECT product_id,channel_code,region_code FROM budget
), aligned AS (
 SELECT k.*,COALESCE(s.q,0) AS qa,COALESCE(s.revenue,0) AS ra,COALESCE(s.cost,0) AS ca,
 COALESCE(r.refund,0) AS fa,COALESCE(r.reversal,0) AS xa,
 b.budget_quantity AS qb,b.budget_quantity*b.budget_net_unit_price AS rb,
 b.budget_quantity*b.budget_unit_cost AS cb,b.budget_refund_amount AS fb,
 b.budget_cogs_reversal_amount AS xb,(b.budget_version IS NULL) AS missing_budget
 FROM all_keys k LEFT JOIN sales s USING(product_id,channel_code,region_code)
 LEFT JOIN refunds r USING(product_id,channel_code,region_code)
 LEFT JOIN budget b USING(product_id,channel_code,region_code)
 WHERE (:product IS NULL OR k.product_id=:product)
 AND (:channel IS NULL OR k.channel_code=:channel)
 AND (:region IS NULL OR k.region_code=:region)
), products AS (
 SELECT product_id,SUM(qa) AS q_actual,SUM(ra) AS revenue_actual,SUM(ca) AS cost_actual,
 SUM(fa) AS refund_actual,SUM(xa) AS reversal_actual,
 CASE WHEN SUM(missing_budget)=0 THEN SUM(qb) END AS q_budget,
 CASE WHEN SUM(missing_budget)=0 THEN SUM(rb) END AS revenue_budget,
 CASE WHEN SUM(missing_budget)=0 THEN SUM(cb) END AS cost_budget,
 CASE WHEN SUM(missing_budget)=0 THEN SUM(fb) END AS refund_budget,
 CASE WHEN SUM(missing_budget)=0 THEN SUM(xb) END AS reversal_budget,
 SUM(missing_budget) AS missing_budget_cells
 FROM aligned GROUP BY product_id
), common_totals AS (
 SELECT SUM(CASE WHEN q_budget>0 AND q_actual>0 THEN q_budget ELSE 0 END) AS q0,
 SUM(CASE WHEN q_budget>0 AND q_actual>0 THEN q_actual ELSE 0 END) AS q1 FROM products
)
SELECT p.*,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual>0 THEN (t.q1-t.q0)*revenue_budget/t.q0 ELSE 0 END AS volume,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual>0 THEN q_actual*revenue_budget/q_budget-t.q1*revenue_budget/t.q0 ELSE 0 END AS mix,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual>0 THEN revenue_actual-q_actual*revenue_budget/q_budget ELSE 0 END AS price,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget=0 AND q_actual>0 THEN revenue_actual ELSE 0 END AS new_product,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual=0 THEN -revenue_budget ELSE 0 END AS no_sales_product,
 -(refund_actual-refund_budget) AS refund,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual>0 THEN (q_actual-q_budget)*(revenue_budget-cost_budget)/q_budget ELSE 0 END AS product_volume,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual>0 THEN q_actual*cost_budget/q_budget-cost_actual ELSE 0 END AS unit_cost,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget=0 AND q_actual>0 THEN revenue_actual-cost_actual ELSE 0 END AS new_product_margin,
 CASE WHEN missing_budget_cells>0 THEN NULL WHEN q_budget>0 AND q_actual=0 THEN -(revenue_budget-cost_budget) ELSE 0 END AS no_sales_product_margin,
 reversal_actual-reversal_budget AS cost_reversal
FROM products p CROSS JOIN common_totals t ORDER BY p.product_id
