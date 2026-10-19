-- 仅用于独立验证实例；在事务中制造边界，随后回滚。
-- 趋势片段由当前04_trends.sql生成，核对答案独立指定。
USE finance_bp_stage3;
-- 验证入口为独立连接，不继承执行报告入口的会话参数。
SET NAMES utf8mb4 COLLATE utf8mb4_0900_as_cs;
SET @analysis_month=DATE('2026-09-01');
SET @actual_start_month=DATE('2026-09-01');
SET @actual_end_month=DATE('2026-09-01');
SET @budget_version='B2026_V1';
DROP PROCEDURE IF EXISTS sp_stage4_edge_cases;
DROP PROCEDURE IF EXISTS sp_stage4_trend_tests;
DELIMITER $$
CREATE PROCEDURE sp_stage4_edge_cases()
BEGIN
 DECLARE v_count INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

 START TRANSACTION;
 DELETE FROM budget_sales WHERE budget_version='B2026_V1' AND month='2026-09-01' AND product_id='P001' AND channel_code='C01' AND region_code='R01';
 SELECT COUNT(*) INTO v_count FROM vw_sales_budget_comparison WHERE budget_version='B2026_V1' AND month='2026-09-01' AND product_id='P001' AND channel_code='C01'
 AND has_actual_record=1 AND has_budget=0 AND actual_net_revenue=2390 AND budget_net_revenue IS NULL;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MISSING_BUDGET_WAS_LOST_OR_ZERO_FILLED'; END IF;
 ROLLBACK;
 SELECT 'MISSING_BUDGET_STAYS_NULL' AS test_name,'PASS' AS result;

 START TRANSACTION;
 UPDATE budget_sales SET budget_quantity=0,budget_refund_amount=0,budget_cogs_reversal_amount=0
 WHERE budget_version='B2026_V1' AND month='2026-09-01' AND product_id='P001' AND channel_code='C01' AND region_code='R01';
 SELECT COUNT(*) INTO v_count FROM vw_sales_budget_comparison WHERE budget_version='B2026_V1' AND month='2026-09-01' AND product_id='P001' AND channel_code='C01'
 AND has_budget=1 AND budget_net_revenue=0 AND actual_net_revenue=2390;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ZERO_BUDGET_IS_NOT_MISSING'; END IF;
 ROLLBACK;
 SELECT 'ZERO_BUDGET_DISTINCT_FROM_MISSING' AS test_name,'PASS' AS result;

 START TRANSACTION;
 INSERT INTO expenses VALUES ('E_STAGE4_TEST','2026-02-15','D04','administration',NULL,NULL,17,'stage4_test','fee_only',6);
 SELECT COUNT(*) INTO v_count FROM vw_monthly_company WHERE month='2026-02-01' AND net_revenue=0 AND gross_margin=0 AND expense_amount=17 AND operating_profit=-17 AND confirmed_orders=0;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='EXPENSE_ONLY_MONTH_LOST'; END IF;
 ROLLBACK;
 SELECT 'EXPENSE_ONLY_MONTH_PRESERVED' AS test_name,'PASS' AS result;

 START TRANSACTION;
 INSERT INTO returns VALUES ('T_STAGE4_TEST','I_S01','2026-09-10',1,0,110,0,'return_unsellable',5);
 SELECT COUNT(*) INTO v_count FROM vw_monthly_company WHERE month='2026-09-01' AND net_revenue=3130 AND net_cost=2055 AND gross_margin=1075;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='NONRECOVERABLE_RETURN_COST_WRONG'; END IF;
 ROLLBACK;
 SELECT 'NONRECOVERABLE_RETURN_NO_COST_REVERSAL' AS test_name,'PASS' AS result;

 START TRANSACTION;
 INSERT INTO budget_expenses VALUES ('B_STAGE4_ALT','2026-09-01','administration','D04','ALL','ALL',1,8);
 SELECT COUNT(*) INTO v_count FROM vw_sales_budget_comparison WHERE budget_version='B_STAGE4_ALT' AND month='2026-09-01' AND has_actual_record=1 AND has_budget=0 AND budget_net_revenue IS NULL;
 IF v_count<>4 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='BUDGET_VERSION_ISOLATION_FAILED'; END IF;
 ROLLBACK;
 SELECT 'BUDGET_VERSION_ISOLATION' AS test_name,'PASS' AS result;
END$$
DELIMITER ;
CALL sp_stage4_edge_cases();
DROP PROCEDURE sp_stage4_edge_cases;

-- 查询8：完整自然月序列上用LAG取上月/上年同月。
-- CASE限定数据覆盖，不把未载入数据当作0。YTD需要年初至当月完整覆盖。
CREATE TEMPORARY TABLE stage4_trend_baseline AS
WITH covered_months AS (
 SELECT month,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(net_revenue,0) END AS net_revenue,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(gross_margin,0) END AS gross_margin,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(operating_profit,0) END AS operating_profit
 FROM vw_calendar_company
),windows AS (
 SELECT *,LAG(net_revenue,1) OVER (ORDER BY month) AS previous_month_revenue,
 LAG(net_revenue,12) OVER (ORDER BY month) AS previous_year_revenue,
 SUM(net_revenue) OVER (PARTITION BY YEAR(month) ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS loaded_cumulative_revenue
 FROM covered_months
)
SELECT month,net_revenue,gross_margin,operating_profit,previous_month_revenue,previous_year_revenue,
CASE WHEN previous_month_revenue>0 THEN ROUND(100*(net_revenue-previous_month_revenue)/previous_month_revenue,2) END AS revenue_mom_pct,
CASE WHEN previous_year_revenue>0 THEN ROUND(100*(net_revenue-previous_year_revenue)/previous_year_revenue,2) END AS revenue_yoy_pct,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month
AND @actual_start_month<=MAKEDATE(YEAR(month),1) THEN loaded_cumulative_revenue END AS ytd_revenue,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN loaded_cumulative_revenue END AS sample_loaded_cumulative_revenue,
CASE WHEN previous_month_revenue IS NULL THEN 'NO_COMPARABLE_MONTH'
WHEN previous_month_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS mom_status,
CASE WHEN previous_year_revenue IS NULL THEN 'NO_COMPARABLE_YEAR'
WHEN previous_year_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS yoy_status
FROM windows WHERE month=@analysis_month;
START TRANSACTION;
INSERT INTO orders VALUES
('O_STAGE4_YOY','U0001','2025-09-01','2025-09-03','C03','R03','completed',3),
('O_STAGE4_MOM','U0001','2026-08-01','2026-08-03','C03','R03','completed',3);
INSERT INTO order_items VALUES
('I_STAGE4_YOY','O_STAGE4_YOY',1,'P003',1,200,0,100,4),
('I_STAGE4_MOM','O_STAGE4_MOM',1,'P003',1,100,0,50,4);
-- 只在合成测试里声明空白月份为完整且无交易，不用于真实样本报告。
SET @actual_start_month=DATE('2025-01-01');
SET @actual_end_month=DATE('2026-09-01');
SET @analysis_month=DATE('2026-09-01');
-- 查询8：完整自然月序列上用LAG取上月/上年同月。
-- CASE限定数据覆盖，不把未载入数据当作0。YTD需要年初至当月完整覆盖。
CREATE TEMPORARY TABLE stage4_trend_history AS
WITH covered_months AS (
 SELECT month,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(net_revenue,0) END AS net_revenue,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(gross_margin,0) END AS gross_margin,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(operating_profit,0) END AS operating_profit
 FROM vw_calendar_company
),windows AS (
 SELECT *,LAG(net_revenue,1) OVER (ORDER BY month) AS previous_month_revenue,
 LAG(net_revenue,12) OVER (ORDER BY month) AS previous_year_revenue,
 SUM(net_revenue) OVER (PARTITION BY YEAR(month) ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS loaded_cumulative_revenue
 FROM covered_months
)
SELECT month,net_revenue,gross_margin,operating_profit,previous_month_revenue,previous_year_revenue,
CASE WHEN previous_month_revenue>0 THEN ROUND(100*(net_revenue-previous_month_revenue)/previous_month_revenue,2) END AS revenue_mom_pct,
CASE WHEN previous_year_revenue>0 THEN ROUND(100*(net_revenue-previous_year_revenue)/previous_year_revenue,2) END AS revenue_yoy_pct,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month
AND @actual_start_month<=MAKEDATE(YEAR(month),1) THEN loaded_cumulative_revenue END AS ytd_revenue,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN loaded_cumulative_revenue END AS sample_loaded_cumulative_revenue,
CASE WHEN previous_month_revenue IS NULL THEN 'NO_COMPARABLE_MONTH'
WHEN previous_month_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS mom_status,
CASE WHEN previous_year_revenue IS NULL THEN 'NO_COMPARABLE_YEAR'
WHEN previous_year_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS yoy_status
FROM windows WHERE month=@analysis_month;
SET @analysis_month=DATE('2026-08-01');
-- 查询8：完整自然月序列上用LAG取上月/上年同月。
-- CASE限定数据覆盖，不把未载入数据当作0。YTD需要年初至当月完整覆盖。
CREATE TEMPORARY TABLE stage4_trend_gap AS
WITH covered_months AS (
 SELECT month,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(net_revenue,0) END AS net_revenue,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(gross_margin,0) END AS gross_margin,
 CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN COALESCE(operating_profit,0) END AS operating_profit
 FROM vw_calendar_company
),windows AS (
 SELECT *,LAG(net_revenue,1) OVER (ORDER BY month) AS previous_month_revenue,
 LAG(net_revenue,12) OVER (ORDER BY month) AS previous_year_revenue,
 SUM(net_revenue) OVER (PARTITION BY YEAR(month) ORDER BY month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS loaded_cumulative_revenue
 FROM covered_months
)
SELECT month,net_revenue,gross_margin,operating_profit,previous_month_revenue,previous_year_revenue,
CASE WHEN previous_month_revenue>0 THEN ROUND(100*(net_revenue-previous_month_revenue)/previous_month_revenue,2) END AS revenue_mom_pct,
CASE WHEN previous_year_revenue>0 THEN ROUND(100*(net_revenue-previous_year_revenue)/previous_year_revenue,2) END AS revenue_yoy_pct,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month
AND @actual_start_month<=MAKEDATE(YEAR(month),1) THEN loaded_cumulative_revenue END AS ytd_revenue,
CASE WHEN month BETWEEN @actual_start_month AND @actual_end_month THEN loaded_cumulative_revenue END AS sample_loaded_cumulative_revenue,
CASE WHEN previous_month_revenue IS NULL THEN 'NO_COMPARABLE_MONTH'
WHEN previous_month_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS mom_status,
CASE WHEN previous_year_revenue IS NULL THEN 'NO_COMPARABLE_YEAR'
WHEN previous_year_revenue<=0 THEN 'NONPOSITIVE_BASE' ELSE 'COMPARABLE' END AS yoy_status
FROM windows WHERE month=@analysis_month;
-- 临时表中的合成查询结果也属于当前事务；先保存断言计数，再回滚测试业务。
SET @stage4_history_count=(SELECT COUNT(*) FROM stage4_trend_history WHERE net_revenue=3240 AND previous_month_revenue=100
 AND previous_year_revenue=200 AND revenue_mom_pct=3140 AND revenue_yoy_pct=1520 AND ytd_revenue=3340);
SET @stage4_gap_count=(SELECT COUNT(*) FROM stage4_trend_gap WHERE net_revenue=100 AND previous_month_revenue=0
 AND revenue_mom_pct IS NULL AND mom_status='NONPOSITIVE_BASE' AND ytd_revenue=100);
ROLLBACK;
SET @actual_start_month=DATE('2026-09-01');
SET @actual_end_month=DATE('2026-09-01');
SET @analysis_month=DATE('2026-09-01');

DELIMITER $$
CREATE PROCEDURE sp_stage4_trend_tests()
BEGIN
 DECLARE v_count INT DEFAULT 0;
 SELECT COUNT(*) INTO v_count FROM stage4_trend_baseline WHERE net_revenue=3240 AND previous_month_revenue IS NULL
 AND previous_year_revenue IS NULL AND revenue_mom_pct IS NULL AND revenue_yoy_pct IS NULL AND ytd_revenue IS NULL
 AND sample_loaded_cumulative_revenue=3240;
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='UNLOADED_HISTORY_WAS_ZERO_FILLED'; END IF;
 SELECT 'UNLOADED_HISTORY_AND_YTD_ARE_NULL' AS test_name,'PASS' AS result;

 SET v_count=COALESCE(@stage4_history_count,0);
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CALENDAR_MOM_YOY_YTD_FAILED'; END IF;
 SELECT 'CALENDAR_MOM_YOY_YTD' AS test_name,'PASS' AS result;

 SET v_count=COALESCE(@stage4_gap_count,0);
 IF v_count<>1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CALENDAR_GAP_OR_ZERO_DENOMINATOR_FAILED'; END IF;
 SELECT 'CALENDAR_GAP_NOT_PREVIOUS_OBSERVED_ROW' AS test_name,'PASS' AS result;

 SELECT COUNT(*) INTO v_count FROM orders WHERE order_id LIKE 'O_STAGE4_%';
 IF v_count<>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='HISTORY_TEST_NOT_ROLLED_BACK'; END IF;
 SELECT 'SYNTHETIC_HISTORY_ROLLED_BACK' AS test_name,'PASS' AS result;
END$$
DELIMITER ;
CALL sp_stage4_trend_tests();
DROP PROCEDURE sp_stage4_trend_tests;
