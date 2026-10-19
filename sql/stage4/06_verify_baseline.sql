-- 只读取小样本，核对预先手算的基准；不改订单/退款/费用。
DROP PROCEDURE IF EXISTS sp_stage4_verify_baseline;
DELIMITER $$
CREATE PROCEDURE sp_stage4_verify_baseline()
BEGIN
 DECLARE v_count INT DEFAULT 0;
 SELECT COUNT(*) INTO v_count FROM vw_monthly_company WHERE month='2026-09-01'
 AND net_revenue=3240 AND net_cost=2055 AND gross_margin=1185 AND expense_amount=400
 AND operating_profit=785 AND confirmed_orders=8 AND sales_quantity=40;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MONTHLY_BASELINE_FAILED'; END IF;
 SELECT 'MONTHLY_BASELINE' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM vw_confirmed_sales_detail WHERE month='2026-09-01';
 IF v_count<>9 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='DETAIL_ROW_COUNT_FAILED'; END IF;
 SELECT 'DETAIL_9_ROWS_8_ORDERS' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM (
 SELECT product_id,SUM(net_revenue) AS revenue,SUM(net_cost) AS cost,SUM(gross_margin) AS margin
 FROM vw_monthly_financials WHERE month='2026-09-01' GROUP BY product_id
 ) p WHERE (product_id='P001' AND revenue=2940 AND cost=1890 AND margin=1050)
 OR (product_id='P002' AND revenue=60 AND cost=30 AND margin=30)
 OR (product_id='P003' AND revenue=240 AND cost=135 AND margin=105);
 IF v_count<>3 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='PRODUCT_BASELINE_FAILED'; END IF;
 SELECT 'PRODUCT_BASELINE' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM vw_monthly_financials WHERE month='2026-09-01'
 AND ((channel_code='C01' AND region_code='R01' AND net_revenue=2390 AND gross_margin=850)
 OR (channel_code='C02' AND region_code='R02' AND product_id='P001' AND net_revenue=550 AND gross_margin=200)
 OR (channel_code='C02' AND region_code='R02' AND product_id='P002' AND net_revenue=60 AND gross_margin=30)
 OR (channel_code='C03' AND region_code='R03' AND net_revenue=240 AND gross_margin=105));
 IF v_count<>4 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='DIMENSION_BASELINE_FAILED'; END IF;
 SELECT 'CHANNEL_REGION_BASELINE' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM vw_monthly_financials WHERE month='2026-10-01'
 AND sales_revenue=0 AND refund_amount=110 AND net_revenue=-110 AND net_cost=-70 AND gross_margin=-40;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='REFUND_ONLY_MONTH_LOST'; END IF;
 SELECT 'REFUND_ONLY_MONTH_PRESERVED' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM (
 SELECT SUM(budget_net_revenue) AS revenue,SUM(budget_net_cost) AS cost,SUM(budget_gross_margin) AS margin
 FROM vw_budget_sales_metrics WHERE month='2026-09-01' AND budget_version='B2026_V1'
 ) b WHERE revenue=3380 AND cost=2100 AND margin=1280;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='BUDGET_BASELINE_FAILED'; END IF;
 SELECT 'BUDGET_BASELINE' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM vw_expense_budget_comparison WHERE month='2026-09-01' AND budget_version='B2026_V1'
 AND expense_category='marketing' AND actual_expense=100 AND budget_amount=90 AND channel_scope='C01' AND region_scope='ALL';
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='EXPENSE_SCOPE_FAILED'; END IF;
 SELECT 'COMMON_EXPENSE_SCOPE' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM information_schema.views WHERE table_schema=DATABASE() AND table_name IN
 ('vw_confirmed_sales_detail','vw_monthly_sales','vw_monthly_returns','vw_monthly_financials','vw_monthly_expenses',
 'vw_monthly_company','vw_budget_sales_metrics','vw_calendar_company','vw_sales_budget_comparison','vw_expense_budget_comparison');
 IF v_count<>10 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='VIEW_COUNT_FAILED'; END IF;
 SELECT 'TEN_ANALYSIS_VIEWS' AS test_name,'PASS' AS result;
END$$
DELIMITER ;
CALL sp_stage4_verify_baseline();
DROP PROCEDURE sp_stage4_verify_baseline;

