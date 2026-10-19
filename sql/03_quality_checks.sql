-- 跨表质量查询：正确样本应全部violations=0。
USE finance_bp_stage3;
CREATE TEMPORARY TABLE stage3_quality_results AS
SELECT 'DQ01_ORDER_WITHOUT_ITEMS' AS check_name, COUNT(*) AS violations
FROM orders o LEFT JOIN order_items i ON i.order_id=o.order_id WHERE i.order_id IS NULL
UNION ALL
SELECT 'DQ02_CUSTOMER_DATE',COUNT(*) FROM orders o JOIN customers c ON c.customer_id=o.customer_id WHERE c.signup_date>o.order_date
UNION ALL
SELECT 'DQ03_RETURN_STATUS_DATE',COUNT(*) FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
JOIN orders o ON o.order_id=i.order_id
WHERE o.order_status<>'completed' OR o.recognized_date IS NULL OR r.refund_date<o.recognized_date
UNION ALL
SELECT 'DQ04_RETURN_CUMULATIVE',COUNT(*) FROM (
 SELECT i.order_item_id FROM order_items i JOIN returns r ON r.order_item_id=i.order_item_id
 GROUP BY i.order_item_id,i.quantity,i.unit_list_price,i.discount_amount,i.unit_cost_snapshot
 HAVING SUM(r.refund_amount)>i.quantity*i.unit_list_price-i.discount_amount
 OR SUM(r.returned_quantity)>i.quantity OR SUM(r.cogs_reversal_amount)>i.quantity*i.unit_cost_snapshot
) bad_returns
UNION ALL
SELECT 'DQ05_RETURN_COST_EVIDENCE',COUNT(*) FROM returns r JOIN order_items i ON i.order_item_id=r.order_item_id
WHERE r.cogs_reversal_amount<>r.recoverable_quantity*i.unit_cost_snapshot
UNION ALL
SELECT 'DQ06_FACT_DATE_NOT_IN_CALENDAR',COUNT(*) FROM (
 SELECT signup_date AS d FROM customers UNION ALL SELECT order_date FROM orders
 UNION ALL SELECT recognized_date FROM orders WHERE recognized_date IS NOT NULL
 UNION ALL SELECT refund_date FROM returns UNION ALL SELECT expense_date FROM expenses
 UNION ALL SELECT month FROM budget_sales UNION ALL SELECT month FROM budget_expenses
) dates LEFT JOIN dim_date c ON c.full_date=dates.d WHERE c.date_id IS NULL
UNION ALL
SELECT 'DQ07_CALENDAR_COMPLETENESS',CASE WHEN COUNT(*)=1096 AND MIN(full_date)='2024-01-01'
AND MAX(full_date)='2026-12-31' AND COUNT(DISTINCT full_date)=1096 THEN 0 ELSE 1 END FROM dim_date
UNION ALL
SELECT 'DQ08_BATCH_RECONCILIATION',COUNT(*) FROM import_batches b LEFT JOIN (
 SELECT import_batch_id AS batch_id,COUNT(*) AS rows_loaded FROM products GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM customers GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM orders GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM order_items GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM returns GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM expenses GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM budget_sales GROUP BY import_batch_id
 UNION ALL SELECT import_batch_id,COUNT(*) FROM budget_expenses GROUP BY import_batch_id
) x ON x.batch_id=b.batch_id
WHERE b.status NOT IN ('completed','completed_with_errors') OR COALESCE(x.rows_loaded,0)<>b.accepted_rows
UNION ALL
SELECT 'DQ09_BATCH_DATASET_MISMATCH',COUNT(*) FROM (
 SELECT import_batch_id AS batch_id,'products' AS data_type FROM products
 UNION ALL SELECT import_batch_id,'customers' FROM customers
 UNION ALL SELECT import_batch_id,'orders' FROM orders
 UNION ALL SELECT import_batch_id,'order_items' FROM order_items
 UNION ALL SELECT import_batch_id,'returns' FROM returns
 UNION ALL SELECT import_batch_id,'expenses' FROM expenses
 UNION ALL SELECT import_batch_id,'budget_sales' FROM budget_sales
 UNION ALL SELECT import_batch_id,'budget_expenses' FROM budget_expenses
) x JOIN import_batches b ON b.batch_id=x.batch_id WHERE x.data_type<>b.dataset_type;

SELECT check_name,violations,IF(violations=0,'PASS','FAIL') AS result FROM stage3_quality_results ORDER BY check_name;
SET @stage3_quality_violations=(SELECT SUM(violations) FROM stage3_quality_results);

