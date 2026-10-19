-- 查询4：商品收入与毛利排名；不分摊公司共同费用。
WITH products_summary AS (
 SELECT f.product_id,p.product_name,SUM(f.net_revenue) AS net_revenue,SUM(f.net_cost) AS net_cost,
 SUM(f.gross_margin) AS gross_margin FROM vw_monthly_financials f JOIN products p ON p.product_id=f.product_id
 WHERE f.month=@analysis_month AND @analysis_month BETWEEN @actual_start_month AND @actual_end_month
 GROUP BY f.product_id,p.product_name
)
SELECT *,CASE WHEN net_revenue>0 THEN ROUND(100*gross_margin/net_revenue,2) END AS margin_pct,
DENSE_RANK() OVER (ORDER BY net_revenue DESC) AS revenue_rank,
DENSE_RANK() OVER (ORDER BY gross_margin DESC) AS margin_rank FROM products_summary ORDER BY revenue_rank,product_id;

-- 查询5：渠道分析。分组改变结果粒度，先合计金额再算比例。
SELECT channel_code,SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin,
CASE WHEN SUM(net_revenue)>0 THEN ROUND(100*SUM(gross_margin)/SUM(net_revenue),2) END AS margin_pct
FROM vw_monthly_financials WHERE month=@analysis_month AND @analysis_month BETWEEN @actual_start_month AND @actual_end_month
GROUP BY channel_code ORDER BY net_revenue DESC;

-- 查询6：区域分析。
SELECT region_code,SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin
FROM vw_monthly_financials WHERE month=@analysis_month AND @analysis_month BETWEEN @actual_start_month AND @actual_end_month
GROUP BY region_code ORDER BY net_revenue DESC;

-- 查询7：发现毛利金额超过100元的商品。HAVING筛选分组结果。
SELECT product_id,SUM(gross_margin) AS gross_margin FROM vw_monthly_financials
WHERE month=@analysis_month AND @analysis_month BETWEEN @actual_start_month AND @actual_end_month
GROUP BY product_id HAVING SUM(gross_margin)>100 ORDER BY gross_margin DESC;

