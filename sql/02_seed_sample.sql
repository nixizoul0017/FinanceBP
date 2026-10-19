-- 仅向新建的空练习库插入样本；不使用覆盖、REPLACE或INSERT IGNORE。
-- JSON文件是原始小样本；批次记录使用对应文件实际SHA-256。
USE finance_bp_stage3;
SET SESSION cte_max_recursion_depth=1200;
START TRANSACTION;
INSERT INTO dim_date (date_id,full_date,year,month,month_start,quarter)
WITH RECURSIVE calendar AS (
  SELECT DATE('2024-01-01') AS d
  UNION ALL SELECT DATE_ADD(d, INTERVAL 1 DAY) FROM calendar WHERE d<'2026-12-31'
)
SELECT YEAR(d)*10000+MONTH(d)*100+DAY(d),d,YEAR(d),MONTH(d),DATE_SUB(d,INTERVAL (DAY(d)-1) DAY),QUARTER(d)
FROM calendar;

INSERT INTO import_batches
(batch_id,dataset_type,file_name,file_hash,started_at,finished_at,status,attempt_count,source_rows,accepted_rows,rejected_rows,skipped_rows)
VALUES
(1,'products','products.json','2066c5dea7736248a260f05cf81faef181ce9c27f41872998166ee35aa0873c1',NOW(),NOW(),'completed',1,3,3,0,0),
(2,'customers','customers.json','c6061b9aefdf6e7e7bf170c4a72ee0da0d309d2dfb6de6152a8dc0c808a438a1',NOW(),NOW(),'completed',1,3,3,0,0),
(3,'orders','orders.json','9907e1d33bf0e4683062e8fedd539e938976ece9d5645bfff85baa50972f51a6',NOW(),NOW(),'completed',1,10,10,0,0),
(4,'order_items','order_items.json','7a737654cbcb7d1576e2af17edcb27f37251e0a8f6fb718fa5df66e0ab2e94a4',NOW(),NOW(),'completed',1,11,11,0,0),
(5,'returns','returns.json','8264ccc3985ed60b6b4a4f2ac8d040fbc8d7d76a2e239e490ee3807133589413',NOW(),NOW(),'completed',1,5,5,0,0),
(6,'expenses','expenses.json','5403220bc738b3109a291647fa3ee9f9172c101a5d04807550b170b8f6e3d99e',NOW(),NOW(),'completed',1,5,5,0,0),
(7,'budget_sales','budget_sales.json','52e4aea58812c767ddc90c891b2ae5ed2aaa56e825c516fea80b7188ff8a7623',NOW(),NOW(),'completed',1,5,5,0,0),
(8,'budget_expenses','budget_expenses.json','9a3a70bb2fc5863d3b8f8aa868cd0e6d23cd7804bd89997b58152e5a24ebfc4c',NOW(),NOW(),'completed',1,5,5,0,0),
(9,'returns','returns_crossmonth.json','952af13cc336f82f503c524aa86b828af11329fbd42888720b956d45f549edf8',NOW(),NOW(),'completed',1,1,1,0,0);

-- 样本：products
INSERT INTO products
(product_id,product_name,category,quantity_unit,active_flag,import_batch_id)
VALUES
('P001','收纳盒','STORAGE','件',1,1),
('P002','清洁刷','CLEANING','件',1,1),
('P003','厨房置物架','KITCHEN','件',1,1);

-- 样本：customers
INSERT INTO customers
(customer_id,signup_date,import_batch_id)
VALUES
('U0001','2024-01-01',2),
('U0002','2024-01-01',2),
('U0003','2024-01-01',2);

-- 样本：orders
INSERT INTO orders
(order_id,customer_id,order_date,recognized_date,channel_code,region_code,order_status,import_batch_id)
VALUES
('O_S01','U0001','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S02','U0002','2026-09-01',NULL,'C01','R01','cancelled',3),
('O_S03','U0003','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S04','U0001','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S05','U0002','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S06','U0003','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S07','U0001','2026-09-01','2026-09-03','C01','R01','completed',3),
('O_S08','U0002','2026-09-01',NULL,'C01','R01','pending',3),
('O_S09','U0003','2026-09-15','2026-09-16','C02','R02','completed',3),
('O_S10','U0001','2026-09-19','2026-09-20','C03','R03','completed',3);

-- 样本：order_items
INSERT INTO order_items
(order_item_id,order_id,line_number,product_id,quantity,unit_list_price,discount_amount,unit_cost_snapshot,import_batch_id)
VALUES
('I_S01','O_S01',1,'P001',5,120,50,70,4),
('I_S02','O_S02',1,'P001',5,120,50,70,4),
('I_S03','O_S03',1,'P001',5,120,50,70,4),
('I_S04','O_S04',1,'P001',5,120,50,70,4),
('I_S05','O_S05',1,'P001',5,120,50,70,4),
('I_S06','O_S06',1,'P001',5,120,50,70,4),
('I_S07','O_S07',1,'P001',5,120,50,70,4),
('I_S08','O_S08',1,'P002',2,30,0,15,4),
('I_S09','O_S09',1,'P001',5,120,50,70,4),
('I_S10','O_S10',1,'P003',3,80,0,45,4),
('I_S09_B','O_S09',2,'P002',2,30,0,15,4);

-- 样本：returns
INSERT INTO returns
(return_id,order_item_id,refund_date,returned_quantity,recoverable_quantity,refund_amount,cogs_reversal_amount,reason_code,import_batch_id)
VALUES
('T_S03','I_S03','2026-09-10',1,1,110,70,'return_resalable',5),
('T_S05','I_S05','2026-09-10',0,0,30,0,'compensation',5),
('T_S06_A','I_S06','2026-09-10',1,1,110,70,'return_resalable',5),
('T_S06_B','I_S06','2026-09-15',1,1,110,70,'return_resalable',5),
('T_S07','I_S07','2026-09-10',5,5,550,350,'return_resalable',5);

-- 样本：expenses
INSERT INTO expenses
(expense_id,expense_date,department,expense_category,channel_code,region_code,amount,source_system,source_reference,import_batch_id)
VALUES
('E1','2026-09-30','D01','marketing','C01',NULL,100,'demo_expenses','EXP202609-1',6),
('E2','2026-09-30','D02','platform_commission',NULL,NULL,50,'demo_expenses','EXP202609-2',6),
('E3','2026-09-30','D03','logistics',NULL,NULL,30,'demo_expenses','EXP202609-3',6),
('E4','2026-09-30','D04','payroll',NULL,NULL,200,'demo_expenses','EXP202609-4',6),
('E5','2026-09-30','D04','administration',NULL,NULL,20,'demo_expenses','EXP202609-5',6);

-- 样本：budget_sales
INSERT INTO budget_sales
(budget_version,month,product_id,channel_code,region_code,budget_quantity,budget_net_unit_price,budget_unit_cost,budget_refund_amount,budget_cogs_reversal_amount,import_batch_id)
VALUES
('B2026_V1','2026-09-01','P001','C01','R01',30,110,70,900,560,7),
('B2026_V1','2026-09-01','P001','C02','R02',5,120,70,0,0,7),
('B2026_V1','2026-09-01','P002','C02','R02',2,30,15,0,0,7),
('B2026_V1','2026-09-01','P003','C03','R03',4,80,45,0,0,7),
('B2026_V1','2026-10-01','P001','C01','R01',0,110,70,110,70,7);

-- 样本：budget_expenses
INSERT INTO budget_expenses
(budget_version,month,expense_category,department,channel_scope,region_scope,budget_amount,import_batch_id)
VALUES
('B2026_V1','2026-09-01','marketing','D01','C01','ALL',90,8),
('B2026_V1','2026-09-01','platform_commission','D02','ALL','ALL',45,8),
('B2026_V1','2026-09-01','logistics','D03','ALL','ALL',35,8),
('B2026_V1','2026-09-01','payroll','D04','ALL','ALL',190,8),
('B2026_V1','2026-09-01','administration','D04','ALL','ALL',20,8);

-- 单独批次：10月跨月退款教学样本，不是10月完整实际
INSERT INTO returns
(return_id,order_item_id,refund_date,returned_quantity,recoverable_quantity,refund_amount,cogs_reversal_amount,reason_code,import_batch_id)
VALUES
('T_S04','I_S04','2026-10-05',1,1,110,70,'return_resalable',9);

COMMIT;
SELECT 'SAMPLES_INSERTED' AS result, (SELECT COUNT(*) FROM orders) AS orders, (SELECT COUNT(*) FROM order_items) AS items, (SELECT COUNT(*) FROM returns) AS refunds;
