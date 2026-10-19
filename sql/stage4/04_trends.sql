-- 查询8：完整自然月序列上用LAG取上月/上年同月。
-- CASE限定数据覆盖，不把未载入数据当作0。YTD需要年初至当月完整覆盖。
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

