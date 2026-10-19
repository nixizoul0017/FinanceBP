-- 使用06文档独立手算结果核对；销售和退款先分表按各自月份汇总。
USE finance_bp_stage3;
CREATE TEMPORARY TABLE stage3_expected_cases (
 order_id VARCHAR(32),month DATE,expected_revenue DECIMAL(18,2),expected_cost DECIMAL(18,2),expected_margin DECIMAL(18,2)
);
INSERT INTO stage3_expected_cases VALUES
('O_S01','2026-09-01',550,350,200),
('O_S02','2026-09-01',0,0,0),
('O_S03','2026-09-01',440,280,160),
('O_S04','2026-09-01',550,350,200),
('O_S04','2026-10-01',-110,-70,-40),
('O_S05','2026-09-01',520,350,170),
('O_S06','2026-09-01',330,210,120),
('O_S07','2026-09-01',0,0,0),
('O_S08','2026-09-01',0,0,0),
('O_S09','2026-09-01',610,380,230),
('O_S10','2026-09-01',240,135,105);

CREATE TEMPORARY TABLE stage3_case_actual AS
WITH sales AS (
 SELECT o.order_id,DATE_SUB(o.recognized_date,INTERVAL (DAY(o.recognized_date)-1) DAY) AS month,
 SUM(i.quantity*i.unit_list_price-i.discount_amount) AS revenue,SUM(i.quantity*i.unit_cost_snapshot) AS cost
 FROM orders o JOIN order_items i ON i.order_id=o.order_id WHERE o.order_status='completed'
 GROUP BY o.order_id,month
),refunds AS (
 SELECT i.order_id,DATE_SUB(r.refund_date,INTERVAL (DAY(r.refund_date)-1) DAY) AS month,
 SUM(r.refund_amount) AS refund_amount,SUM(r.cogs_reversal_amount) AS reversal
 FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id GROUP BY i.order_id,month
)
SELECT e.order_id,e.month,
COALESCE(s.revenue,0)-COALESCE(r.refund_amount,0) AS actual_revenue,
COALESCE(s.cost,0)-COALESCE(r.reversal,0) AS actual_cost,
e.expected_revenue,e.expected_cost,e.expected_margin
FROM stage3_expected_cases e LEFT JOIN sales s ON s.order_id=e.order_id AND s.month=e.month
LEFT JOIN refunds r ON r.order_id=e.order_id AND r.month=e.month;

SELECT order_id,month,actual_revenue,actual_cost,actual_revenue-actual_cost AS actual_margin,
IF(actual_revenue=expected_revenue AND actual_cost=expected_cost AND actual_revenue-actual_cost=expected_margin,'PASS','FAIL') AS result
FROM stage3_case_actual ORDER BY order_id,month;
SET @stage3_case_failures=(SELECT COUNT(*) FROM stage3_case_actual WHERE actual_revenue<>expected_revenue OR actual_cost<>expected_cost OR actual_revenue-actual_cost<>expected_margin);

CREATE TEMPORARY TABLE stage3_monthly_actual AS
WITH sales AS (
 SELECT DATE_SUB(o.recognized_date,INTERVAL (DAY(o.recognized_date)-1) DAY) AS month,
 SUM(i.quantity*i.unit_list_price-i.discount_amount) AS revenue,SUM(i.quantity*i.unit_cost_snapshot) AS cost,
 COUNT(DISTINCT o.order_id) AS confirmed_orders
 FROM orders o JOIN order_items i ON i.order_id=o.order_id WHERE o.order_status='completed' GROUP BY month
), refunds AS (
 SELECT DATE_SUB(refund_date,INTERVAL (DAY(refund_date)-1) DAY) AS month,SUM(refund_amount) AS refund_amount,SUM(cogs_reversal_amount) AS reversal
 FROM returns GROUP BY month
), fee AS (
 SELECT DATE_SUB(expense_date,INTERVAL (DAY(expense_date)-1) DAY) AS month,SUM(amount) AS amount FROM expenses GROUP BY month
), periods AS (SELECT DISTINCT month_start AS month FROM dim_date)
SELECT p.month,COALESCE(s.revenue,0) AS sales_revenue,COALESCE(r.refund_amount,0) AS refunds,
COALESCE(s.revenue,0)-COALESCE(r.refund_amount,0) AS net_revenue,
COALESCE(s.cost,0)-COALESCE(r.reversal,0) AS net_cost,COALESCE(f.amount,0) AS expenses,
COALESCE(s.confirmed_orders,0) AS confirmed_orders
FROM periods p LEFT JOIN sales s ON s.month=p.month LEFT JOIN refunds r ON r.month=p.month LEFT JOIN fee f ON f.month=p.month;

SELECT month,sales_revenue,refunds,net_revenue,net_cost,net_revenue-net_cost AS margin,expenses,
net_revenue-net_cost-expenses AS operating_profit,confirmed_orders
FROM stage3_monthly_actual WHERE month IN ('2026-09-01','2026-10-01') ORDER BY month;
SET @stage3_monthly_failures=(SELECT COUNT(*) FROM stage3_monthly_actual WHERE
(month='2026-09-01' AND (sales_revenue<>4150 OR refunds<>910 OR net_revenue<>3240 OR net_cost<>2055 OR expenses<>400 OR confirmed_orders<>8))
OR (month='2026-10-01' AND (sales_revenue<>0 OR refunds<>110 OR net_revenue<>-110 OR net_cost<>-70 OR expenses<>0 OR confirmed_orders<>0)));

SET @stage3_budget_revenue=(SELECT SUM(budget_quantity*budget_net_unit_price-budget_refund_amount) FROM budget_sales WHERE month='2026-09-01' AND budget_version='B2026_V1');
SET @stage3_budget_cost=(SELECT SUM(budget_quantity*budget_unit_cost-budget_cogs_reversal_amount) FROM budget_sales WHERE month='2026-09-01' AND budget_version='B2026_V1');
SET @stage3_budget_fees=(SELECT SUM(budget_amount) FROM budget_expenses WHERE month='2026-09-01' AND budget_version='B2026_V1');
SELECT @stage3_budget_revenue AS budget_revenue,@stage3_budget_cost AS budget_cost,
@stage3_budget_revenue-@stage3_budget_cost AS budget_margin,@stage3_budget_fees AS budget_expenses,
@stage3_budget_revenue-@stage3_budget_cost-@stage3_budget_fees AS budget_operating_profit;
SET @stage3_budget_failures=IF(@stage3_budget_revenue=3380 AND @stage3_budget_cost=2100 AND @stage3_budget_fees=380,0,1);

SELECT 'SAMPLE_VERIFICATION' AS check_name,
@stage3_case_failures+@stage3_monthly_failures+@stage3_budget_failures AS failures;

