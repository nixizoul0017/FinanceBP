-- 验证实例导出可复核的JSON基准；字段以元为单位，数组按ID关联而非按行号比较。
SELECT JSON_OBJECT(
 'dataset','stage3_sample_v1',
 'analysis_month','2026-09-01',
 'company',(SELECT JSON_OBJECT('net_revenue',net_revenue,'net_cost',net_cost,'gross_margin',gross_margin,
   'expenses',expense_amount,'operating_profit',operating_profit,'confirmed_orders',confirmed_orders)
   FROM vw_monthly_company WHERE month='2026-09-01'),
 'products',(SELECT JSON_ARRAYAGG(JSON_OBJECT('product_id',product_id,'net_revenue',net_revenue,'net_cost',net_cost,'gross_margin',gross_margin))
   FROM (SELECT product_id,SUM(net_revenue) AS net_revenue,SUM(net_cost) AS net_cost,SUM(gross_margin) AS gross_margin
   FROM vw_monthly_financials WHERE month='2026-09-01' GROUP BY product_id) p),
 'channels',(SELECT JSON_ARRAYAGG(JSON_OBJECT('channel_code',channel_code,'net_revenue',net_revenue,'gross_margin',gross_margin))
   FROM (SELECT channel_code,SUM(net_revenue) AS net_revenue,SUM(gross_margin) AS gross_margin
   FROM vw_monthly_financials WHERE month='2026-09-01' GROUP BY channel_code) c),
 'regions',(SELECT JSON_ARRAYAGG(JSON_OBJECT('region_code',region_code,'net_revenue',net_revenue,'gross_margin',gross_margin))
   FROM (SELECT region_code,SUM(net_revenue) AS net_revenue,SUM(gross_margin) AS gross_margin
   FROM vw_monthly_financials WHERE month='2026-09-01' GROUP BY region_code) r),
 'sales_budget',(SELECT JSON_OBJECT('version','B2026_V1','net_revenue',SUM(budget_net_revenue),
   'net_cost',SUM(budget_net_cost),'gross_margin',SUM(budget_gross_margin))
   FROM vw_budget_sales_metrics WHERE month='2026-09-01' AND budget_version='B2026_V1'),
 'expenses_budget',(SELECT SUM(budget_amount) FROM budget_expenses WHERE month='2026-09-01' AND budget_version='B2026_V1')
) AS reference_json;
