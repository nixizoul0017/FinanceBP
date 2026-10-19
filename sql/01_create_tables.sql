-- 字段依据 docs/08_数据字典.md；阶段3只建立前10张表。
USE finance_bp_stage3;

CREATE TABLE dim_date (
  date_id INT NOT NULL COMMENT 'YYYYMMDD日期主键',
  full_date DATE NOT NULL,
  year SMALLINT NOT NULL,
  month TINYINT NOT NULL,
  month_start DATE NOT NULL,
  quarter TINYINT NOT NULL,
  PRIMARY KEY (date_id),
  UNIQUE KEY uk_date_full (full_date),
  KEY ix_date_month (month_start),
  CONSTRAINT ck_date_values CHECK (
    date_id = YEAR(full_date)*10000+MONTH(full_date)*100+DAY(full_date)
    AND year=YEAR(full_date) AND month=MONTH(full_date)
    AND quarter=QUARTER(full_date)
    AND month_start=DATE_SUB(full_date, INTERVAL (DAY(full_date)-1) DAY))
) ENGINE=InnoDB;

CREATE TABLE import_batches (
  batch_id BIGINT NOT NULL AUTO_INCREMENT,
  dataset_type VARCHAR(32) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  attempt_count INT NOT NULL DEFAULT 0,
  source_rows INT NOT NULL DEFAULT 0,
  accepted_rows INT NOT NULL DEFAULT 0,
  rejected_rows INT NOT NULL DEFAULT 0,
  skipped_rows INT NOT NULL DEFAULT 0,
  error_summary TEXT NULL,
  PRIMARY KEY (batch_id),
  UNIQUE KEY uk_batch_content (dataset_type,file_hash),
  CONSTRAINT ck_batch_type CHECK (dataset_type IN ('products','customers','orders','order_items','returns','expenses','budget_sales','budget_expenses')),
  CONSTRAINT ck_batch_hash CHECK (REGEXP_LIKE(file_hash,'^[0-9a-f]{64}$','c')),
  CONSTRAINT ck_batch_status CHECK (status IN ('pending','running','completed','completed_with_errors','failed')),
  CONSTRAINT ck_batch_counts CHECK (attempt_count>=0 AND source_rows>=0 AND accepted_rows>=0 AND rejected_rows>=0 AND skipped_rows>=0),
  CONSTRAINT ck_batch_time CHECK (finished_at IS NULL OR finished_at>=started_at),
  CONSTRAINT ck_batch_completed CHECK (status NOT IN ('completed','completed_with_errors') OR
    (finished_at IS NOT NULL AND source_rows=accepted_rows+rejected_rows+skipped_rows)),
  CONSTRAINT ck_batch_failed CHECK (status<>'failed' OR accepted_rows=0)
) ENGINE=InnoDB;

CREATE TABLE products (
  product_id VARCHAR(32) NOT NULL,
  product_name VARCHAR(100) NOT NULL,
  category VARCHAR(20) NOT NULL,
  quantity_unit VARCHAR(8) NOT NULL DEFAULT '件',
  active_flag TINYINT NOT NULL DEFAULT 1,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (product_id),
  CONSTRAINT fk_products_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_products_values CHECK (active_flag IN (0,1) AND quantity_unit='件' AND category IN ('STORAGE','CLEANING','KITCHEN')),
  CONSTRAINT ck_products_name CHECK (CHAR_LENGTH(TRIM(product_name))>0)
) ENGINE=InnoDB;

CREATE TABLE customers (
  customer_id VARCHAR(32) NOT NULL,
  signup_date DATE NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (customer_id),
  CONSTRAINT fk_customers_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
) ENGINE=InnoDB;

CREATE TABLE orders (
  order_id VARCHAR(32) NOT NULL,
  customer_id VARCHAR(32) NOT NULL,
  order_date DATE NOT NULL,
  recognized_date DATE NULL,
  channel_code VARCHAR(8) NOT NULL,
  region_code VARCHAR(8) NOT NULL,
  order_status VARCHAR(16) NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (order_id),
  KEY ix_orders_period (recognized_date,channel_code,region_code),
  KEY ix_orders_customer (customer_id,order_date),
  CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
  CONSTRAINT fk_orders_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_orders_codes CHECK (channel_code IN ('C01','C02','C03') AND region_code IN ('R01','R02','R03','R04')),
  CONSTRAINT ck_orders_status CHECK (order_status IN ('pending','completed','cancelled')),
  CONSTRAINT ck_orders_confirmation CHECK (
    (order_status='completed' AND recognized_date IS NOT NULL AND recognized_date>=order_date)
    OR (order_status IN ('pending','cancelled') AND recognized_date IS NULL))
) ENGINE=InnoDB;

CREATE TABLE order_items (
  order_item_id VARCHAR(32) NOT NULL,
  order_id VARCHAR(32) NOT NULL,
  line_number INT NOT NULL,
  product_id VARCHAR(32) NOT NULL,
  quantity INT NOT NULL,
  unit_list_price DECIMAL(18,2) NOT NULL,
  discount_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  unit_cost_snapshot DECIMAL(18,2) NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (order_item_id),
  UNIQUE KEY uk_items_line (order_id,line_number),
  KEY ix_items_product (product_id,order_id),
  CONSTRAINT fk_items_order FOREIGN KEY (order_id) REFERENCES orders(order_id),
  CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(product_id),
  CONSTRAINT fk_items_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_items_values CHECK (line_number>0 AND quantity>0 AND unit_list_price>=0 AND discount_amount>=0
    AND unit_cost_snapshot>=0 AND discount_amount<=quantity*unit_list_price)
) ENGINE=InnoDB;

CREATE TABLE returns (
  return_id VARCHAR(32) NOT NULL,
  order_item_id VARCHAR(32) NOT NULL,
  refund_date DATE NOT NULL,
  returned_quantity INT NOT NULL DEFAULT 0,
  recoverable_quantity INT NOT NULL DEFAULT 0,
  refund_amount DECIMAL(18,2) NOT NULL,
  cogs_reversal_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  reason_code VARCHAR(24) NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (return_id),
  KEY ix_returns_item (order_item_id,refund_date),
  KEY ix_returns_period (refund_date),
  CONSTRAINT fk_returns_item FOREIGN KEY (order_item_id) REFERENCES order_items(order_item_id),
  CONSTRAINT fk_returns_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_returns_values CHECK (returned_quantity>=0 AND recoverable_quantity>=0 AND recoverable_quantity<=returned_quantity
    AND refund_amount>=0 AND cogs_reversal_amount>=0 AND (recoverable_quantity>0 OR cogs_reversal_amount=0)),
  CONSTRAINT ck_returns_reason CHECK (
    (reason_code='compensation' AND returned_quantity=0 AND recoverable_quantity=0 AND cogs_reversal_amount=0)
    OR (reason_code='return_resalable' AND returned_quantity>0 AND recoverable_quantity>0)
    OR (reason_code='return_unsellable' AND returned_quantity>0 AND recoverable_quantity=0 AND cogs_reversal_amount=0))
) ENGINE=InnoDB;

CREATE TABLE expenses (
  expense_id VARCHAR(32) NOT NULL,
  expense_date DATE NOT NULL,
  department VARCHAR(8) NOT NULL,
  expense_category VARCHAR(24) NOT NULL,
  channel_code VARCHAR(8) NULL,
  region_code VARCHAR(8) NULL,
  amount DECIMAL(18,2) NOT NULL,
  source_system VARCHAR(32) NOT NULL,
  source_reference VARCHAR(64) NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (expense_id),
  UNIQUE KEY uk_expenses_source (source_system,source_reference),
  KEY ix_expenses_period (expense_date,expense_category),
  KEY ix_expenses_department (department,expense_date),
  CONSTRAINT fk_expenses_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_expenses_values CHECK (amount>=0 AND department IN ('D01','D02','D03','D04')
    AND expense_category IN ('marketing','platform_commission','logistics','payroll','administration')
    AND (channel_code IS NULL OR channel_code IN ('C01','C02','C03'))
    AND (region_code IS NULL OR region_code IN ('R01','R02','R03','R04'))),
  CONSTRAINT ck_expenses_source CHECK (CHAR_LENGTH(TRIM(source_system))>0 AND CHAR_LENGTH(TRIM(source_reference))>0)
) ENGINE=InnoDB;

CREATE TABLE budget_sales (
  budget_version VARCHAR(32) NOT NULL,
  month DATE NOT NULL,
  product_id VARCHAR(32) NOT NULL,
  channel_code VARCHAR(8) NOT NULL,
  region_code VARCHAR(8) NOT NULL,
  budget_quantity INT NOT NULL,
  budget_net_unit_price DECIMAL(18,4) NOT NULL,
  budget_unit_cost DECIMAL(18,4) NOT NULL,
  budget_refund_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  budget_cogs_reversal_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (budget_version,month,product_id,channel_code,region_code),
  KEY ix_budget_sales_period (month,product_id,channel_code,region_code),
  CONSTRAINT fk_budget_sales_product FOREIGN KEY (product_id) REFERENCES products(product_id),
  CONSTRAINT fk_budget_sales_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_budget_sales_values CHECK (DAY(month)=1 AND budget_quantity>=0 AND budget_net_unit_price>=0 AND budget_unit_cost>=0
    AND budget_refund_amount>=0 AND budget_cogs_reversal_amount>=0
    AND channel_code IN ('C01','C02','C03') AND region_code IN ('R01','R02','R03','R04'))
) ENGINE=InnoDB;

CREATE TABLE budget_expenses (
  budget_version VARCHAR(32) NOT NULL,
  month DATE NOT NULL,
  expense_category VARCHAR(24) NOT NULL,
  department VARCHAR(8) NOT NULL,
  channel_scope VARCHAR(8) NOT NULL,
  region_scope VARCHAR(8) NOT NULL,
  budget_amount DECIMAL(18,2) NOT NULL,
  import_batch_id BIGINT NOT NULL,
  PRIMARY KEY (budget_version,month,expense_category,department,channel_scope,region_scope),
  KEY ix_budget_expenses_period (month,expense_category,department),
  CONSTRAINT fk_budget_expenses_batch FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id),
  CONSTRAINT ck_budget_expenses_values CHECK (DAY(month)=1 AND budget_amount>=0
    AND department IN ('D01','D02','D03','D04')
    AND expense_category IN ('marketing','platform_commission','logistics','payroll','administration')
    AND channel_scope IN ('C01','C02','C03','ALL') AND region_scope IN ('R01','R02','R03','R04','ALL'))
) ENGINE=InnoDB;

SELECT 'TABLES_CREATED' AS result, COUNT(*) AS table_count
FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE';

