-- 独立核对已确认完整窗口、来源/历史成本齐全的演示数据。
-- 命名参数由开发验收入口绑定；预算不参与预测公式。
WITH sales AS (
 SELECT i.product_id,o.channel_code,o.region_code,SUM(i.quantity) AS q,
 SUM(i.quantity*i.unit_list_price-i.discount_amount) AS revenue,
 SUM(i.quantity*i.unit_cost_snapshot) AS cost
 FROM orders o JOIN order_items i ON i.order_id=o.order_id
 WHERE o.order_status='completed' AND o.recognized_date>=:start
 AND o.recognized_date<DATE_ADD(:cutoff,INTERVAL 1 MONTH)
 GROUP BY i.product_id,o.channel_code,o.region_code
),refunds AS (
 SELECT i.product_id,o.channel_code,o.region_code,SUM(r.refund_amount) AS refund,
 SUM(r.cogs_reversal_amount) AS reversal
 FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
 JOIN orders o ON o.order_id=i.order_id
 WHERE o.order_status='completed' AND r.refund_date>=:start
 AND r.refund_date<DATE_ADD(:cutoff,INTERVAL 1 MONTH)
 GROUP BY i.product_id,o.channel_code,o.region_code
),history_keys AS (
 SELECT DISTINCT i.product_id,o.channel_code,o.region_code FROM orders o
 JOIN order_items i ON i.order_id=o.order_id
 WHERE o.order_status='completed' AND o.recognized_date<DATE_ADD(:cutoff,INTERVAL 1 MONTH)
),inputs AS (
 SELECT k.*,COALESCE(s.q,0) AS q,COALESCE(s.revenue,0) AS revenue,
 COALESCE(s.cost,0) AS cost,COALESCE(r.refund,0) AS refund,COALESCE(r.reversal,0) AS reversal,
 ROUND(COALESCE(s.q,0)/:window,0) AS forecast_quantity
 FROM history_keys k LEFT JOIN sales s USING(product_id,channel_code,region_code)
 LEFT JOIN refunds r USING(product_id,channel_code,region_code)
)
SELECT product_id,channel_code,region_code,forecast_quantity,
 CASE WHEN q>0 THEN forecast_quantity*revenue/q ELSE 0 END AS sales_revenue,
 CASE WHEN q>0 THEN forecast_quantity*cost/q ELSE 0 END AS sales_cost,
 ROUND(refund*CASE WHEN revenue>0 AND q>0 THEN forecast_quantity/q ELSE 1/:window END,2) AS refund_amount,
 ROUND(reversal*CASE WHEN revenue>0 AND q>0 THEN forecast_quantity/q ELSE 1/:window END,2) AS cogs_reversal_amount
FROM inputs ORDER BY product_id,channel_code,region_code
