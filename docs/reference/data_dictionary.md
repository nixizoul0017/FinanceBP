# 数据字典 v1

状态：阶段2设计成果；阶段3已将前10张表转换为SQL并在临时MySQL 26.7.0实际验证通过，用户已在现有3306服务成功建立finance_bp_stage3。依据06业务规则与07需求清单，预测扩展3张到阶段9再实施。

## 1. 统一约定

- 表名、字段名使用英文小写；编码与业务ID大小写按本字典规范化。
- 数据库计划使用InnoDB与utf8mb4，具体MySQL版本在阶段3检查。
- PK是主键，FK是外键，UK是业务唯一键。没有注明默认值的必填字段必须由输入提供。
- 所有业务ID使用VARCHAR(32)，由模拟数据或源文件提供；除batch_id、run_id外，不依赖数据库自动生成业务身份。
- 实际交易金额与交易单价/成本使用DECIMAL(18,2)，以分为最小交易单位；预算与预测单价/成本使用DECIMAL(18,4)。平均单价和模型中间结果不提前取整。
- 所有数量字段第一版为整数件数；预测数量在写入前按明确规则取整。实际退款、费用等金额以正值记录，分析时按业务含义加减。
- DATE代表业务日期；month、cutoff_month、month_start使用月份第一天。运行日志的DATETIME统一使用北京时间，由应用与数据库连接统一配置。
- NULL表示未发生或无归属，不能任意替换为零；空字符串不能代替NULL。
- 业务外键采用RESTRICT，正式导入数据禁止通过级联删除改写历史。
- import_batch_id均为必填外键；阶段3手工样本也先建立样本批次。日志表与日期表不需要该字段。
- 当前正式演示实际截止2026-09-30；日期表覆盖2024—2026完整年度。10月退款校验样本使用独立样本批次，在正式演示范围外隔离。

## 2. dim_date：日期表

粒度：一行一个自然日。PK=date_id；UK=full_date。支持完整日历和自然月比较。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| date_id | INT | 否 | YYYYMMDD形式的日期主键 | 20260901 |
| full_date | DATE | 否 | 自然日 | 2026-09-01 |
| year | SMALLINT | 否 | 自然年 | 2026 |
| month | TINYINT | 否 | 月份数字1—12 | 9 |
| month_start | DATE | 否 | 所在月份第一天 | 2026-09-01 |
| quarter | TINYINT | 否 | 季度1—4 | 3 |

校验：所有派生字段与full_date一致；日期不重复、不缺天。索引(month_start)。事实表日期不设日期维表外键，导入质量查询检查其在日历范围内；扩展日期范围先补日历。

## 3. import_batches：导入生命周期

粒度：一类数据的一个文件内容。PK=batch_id；UK=(dataset_type,file_hash)。同一内容不同文件名仍视为同一批次。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| batch_id | BIGINT | 否/自增 | 批次身份 | 1 |
| dataset_type | VARCHAR(32) | 否 | 本次目标数据类别 | orders |
| file_name | VARCHAR(255) | 否 | 源文件名，不保存凭据或敏感路径 | sample_orders.csv |
| file_hash | CHAR(64) | 否 | 文件内容SHA-256小写十六进制 | 64位内容摘要 |
| started_at | DATETIME | 否 | 最近一次实际尝试开始时间 | 2026-10-12 10:00:00 |
| finished_at | DATETIME | 是 | 最近一次尝试结束时间 | NULL |
| status | VARCHAR(32) | 否/pending | 生命周期状态 | running |
| attempt_count | INT | 否/0 | 实际处理尝试次数；重复成功文件跳过不增加 | 1 |
| source_rows | INT | 否/0 | 源数据行数，不含标题 | 10 |
| accepted_rows | INT | 否/0 | 本次新增且提交的有效行数 | 8 |
| rejected_rows | INT | 否/0 | 本次异常隔离行数 | 1 |
| skipped_rows | INT | 否/0 | 与已有业务记录完全相同、跳过的行数 | 1 |
| error_summary | TEXT | 是 | 失败或异常摘要，详细原因另存日志 | 未知商品ID |

CHECK：计数>=0；状态为pending/running/completed/completed_with_errors/failed。完成状态finished_at必须有值且不早于started_at。完成批次source_rows=accepted_rows+rejected_rows+skipped_rows；失败时计数不作为已提交记录证明，accepted_rows应为0。

流程：同一dataset_type+file_hash成功处理过则跳过；failed重试复用batch_id并增加attempt_count。运行中的同批次不得并发重复处理。每次详细日志保存于独立文件，保留重试历史。

事务政策：批次先登记；有效业务行和完成批次统计在一次事务内提交。遇到系统错误回滚新增业务行，再单独登记failed。行级问题隔离后可提交其他有效行，状态为completed_with_errors；有问题的文件修正后内容hash变化，作为新批次处理。

同一业务ID在新文件中出现时，内容相同则计入skipped_rows；内容不同则记录冲突并隔离，不自动覆盖历史。预算调整使用新版本，预测调整使用新run_id。

## 4. products：商品表

粒度：一行一个商品。PK=product_id；FK=import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| product_id | VARCHAR(32) | 否 | 稳定商品身份 | P001 |
| product_name | VARCHAR(100) | 否 | 商品名称 | 收纳盒 |
| category | VARCHAR(20) | 否 | 商品类别编码 | STORAGE |
| quantity_unit | VARCHAR(8) | 否/件 | 销量单位 | 件 |
| active_flag | TINYINT | 否/1 | 当前是否用于新销售 | 1 |
| import_batch_id | BIGINT | 否 | 首次建立该商品的批次 | 1 |

CHECK：active_flag为0或1，quantity_unit=件，category为编码字典中的类别。商品名称不设唯一键。第一版商品分类固定；停用不删除历史商品，不影响其历史收入。商品表不保存用于历史计算的当前售价/成本。

## 5. customers：客户表

粒度：一行一个虚构客户。PK=customer_id；FK=import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| customer_id | VARCHAR(32) | 否 | 模拟客户ID | U0001 |
| signup_date | DATE | 否 | 客户建立日期 | 2024-01-01 |
| import_batch_id | BIGINT | 否 | 来源批次 | 2 |

不保存真实姓名、电话等个人信息。跨表校验：signup_date不晚于首次order_date。第一版客户表用于订单关联，暂不做LTV模型。

## 6. orders：订单表

粒度：一行一个订单。PK=order_id。FK：customer_id→customers.customer_id；import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| order_id | VARCHAR(32) | 否 | 订单身份 | O0001 |
| customer_id | VARCHAR(32) | 否 | 下单客户 | U0001 |
| order_date | DATE | 否 | 下单日期 | 2026-09-01 |
| recognized_date | DATE | 是 | 销售确认日期，仅completed非空 | 2026-09-03 |
| channel_code | VARCHAR(8) | 否 | 成交渠道 | C01 |
| region_code | VARCHAR(8) | 否 | 成交区域 | R01 |
| order_status | VARCHAR(16) | 否 | 项目订单状态 | completed |
| import_batch_id | BIGINT | 否 | 来源批次 | 3 |

CHECK：状态为pending/completed/cancelled；completed时recognized_date非空且>=order_date；其他状态recognized_date为NULL。渠道、区域必须在字典中。

索引：(recognized_date,channel_code,region_code)，(customer_id,order_date)。状态更新在阶段5采用明确流程：未确认订单可按业务规则转为completed或cancelled；已确认不得因退款转cancelled。默认导入不自动更新同ID记录，更新功能另行显式处理。

## 7. order_items：订单明细表

粒度：订单的一条商品行。PK=order_item_id；UK=(order_id,line_number)。FK：order_id→orders.order_id，product_id→products.product_id，import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| order_item_id | VARCHAR(32) | 否 | 明细身份，退款引用它 | I0001 |
| order_id | VARCHAR(32) | 否 | 所属订单 | O0001 |
| line_number | INT | 否 | 订单内部行号 | 1 |
| product_id | VARCHAR(32) | 否 | 本行商品 | P001 |
| quantity | INT | 否 | 成交件数 | 5 |
| unit_list_price | DECIMAL(18,2) | 否 | 每件原价 | 120.00 |
| discount_amount | DECIMAL(18,2) | 否/0 | 整条明细折扣额 | 50.00 |
| unit_cost_snapshot | DECIMAL(18,2) | 否 | 成交时每件成本快照 | 70.00 |
| import_batch_id | BIGINT | 否 | 来源批次 | 4 |

CHECK：line_number>0，quantity>0，单价/成本/折扣>=0，discount_amount<=quantity×unit_list_price。

派生指标不存成第二份事实：折后成交收入=quantity×unit_list_price−discount_amount；成交成本=quantity×unit_cost_snapshot。取消订单也可保留明细，分析时以父订单状态决定是否纳入。

索引：(product_id,order_id)。同一商品可以在同一订单出现两行，只要行号不同，不能将(order_id,product_id)设为唯一键。实际单价与成本只到分，输入更多小数需报错或按事先规则核实，不能静默截断。

## 8. returns：退款表

粒度：一条明细的一次已确认退款事件。PK=return_id。FK：order_item_id→order_items.order_item_id，import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| return_id | VARCHAR(32) | 否 | 退款事件身份 | T0001 |
| order_item_id | VARCHAR(32) | 否 | 原成交明细 | I0001 |
| refund_date | DATE | 否 | 已确认退款日期 | 2026-09-10 |
| returned_quantity | INT | 否/0 | 实际退货件数 | 1 |
| recoverable_quantity | INT | 否/0 | 可回库、可转回原成本的件数 | 1 |
| refund_amount | DECIMAL(18,2) | 否 | 实际退款额 | 110.00 |
| cogs_reversal_amount | DECIMAL(18,2) | 否/0 | 成本转回额 | 70.00 |
| reason_code | VARCHAR(24) | 否 | 退款业务类别 | return_resalable |
| import_batch_id | BIGINT | 否 | 来源批次 | 5 |

同行CHECK：数量和金额>=0；recoverable_quantity<=returned_quantity；无回库数量时成本转回为0；reason_code为允许类别。补偿事件数量和成本转回均为0；可回库退货事件退货量>0且可回库量>0；不可回库退货事件退货量>0且可回库量=0。

跨表/累计校验：

1. 原订单必须completed，refund_date>=recognized_date。
2. Σrefund_amount<=原明细折后成交收入。
3. Σreturned_quantity<=原成交数量。
4. 每事件cogs_reversal_amount=recoverable_quantity×原unit_cost_snapshot；第一版按完整单位成本转回。
5. Σcogs_reversal_amount<=原成交成本。

一次退回多件且部分不可回库，用recoverable_quantity记录可回库部分，其reason_code用return_resalable并在日志说明。不把无法回库部分的成本转回。

索引：(order_item_id,refund_date)，(refund_date)。累计检查在同一事务中锁定原明细再核实已有退款并插入，避免并发退款各自通过后总额超限；阶段3用SQL查询检查样本，阶段5再实现导入事务。

## 9. expenses：费用明细表

粒度：一笔已确认费用行。PK=expense_id；UK=(source_system,source_reference)。FK=import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| expense_id | VARCHAR(32) | 否 | 费用记录身份 | E0001 |
| expense_date | DATE | 否 | 费用确认日期 | 2026-09-30 |
| department | VARCHAR(8) | 否 | 费用责任部门 | D01 |
| expense_category | VARCHAR(24) | 否 | 费用类别 | marketing |
| channel_code | VARCHAR(8) | 是 | 可直接归属的渠道；NULL表示共同归属 | C01或NULL |
| region_code | VARCHAR(8) | 是 | 可直接归属的区域；NULL表示共同归属 | R01或NULL |
| amount | DECIMAL(18,2) | 否 | 不含税费用额 | 100.00 |
| source_system | VARCHAR(32) | 否 | 模拟来源命名空间 | demo_expenses |
| source_reference | VARCHAR(64) | 否 | 来源中唯一的费用行号 | EXP2026090001-1 |
| import_batch_id | BIGINT | 否 | 来源批次 | 6 |

CHECK：amount>=0；部门、费用类别有效；归属非空时必须是有效代码。来源行号以费用行而不是费用单据头为单位，拆分费用用不同来源行号。

索引：(expense_date,expense_category)，(department,expense_date)。所有费用事实相加得到公司费用；不插入含明细的公司总计行，不因筛选再次分摊共同费用。

## 10. budget_sales：月度销售预算

粒度：版本×月×商品×渠道×区域。PK/UK=(budget_version,month,product_id,channel_code,region_code)。FK：product_id→products.product_id，import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| budget_version | VARCHAR(32) | 否 | 已冻结预算版本 | B2026_V1 |
| month | DATE | 否 | 预算月份第一天 | 2026-09-01 |
| product_id | VARCHAR(32) | 否 | 预算商品 | P001 |
| channel_code | VARCHAR(8) | 否 | 预算渠道 | C01 |
| region_code | VARCHAR(8) | 否 | 预算区域 | R01 |
| budget_quantity | INT | 否 | 预算确认销量 | 5 |
| budget_net_unit_price | DECIMAL(18,4) | 否 | 折后、退款前每件收入 | 110.0000 |
| budget_unit_cost | DECIMAL(18,4) | 否 | 每件成本假设 | 70.0000 |
| budget_refund_amount | DECIMAL(18,2) | 否/0 | 当月退款假设，含预计跨月退款 | 110.00 |
| budget_cogs_reversal_amount | DECIMAL(18,2) | 否/0 | 当月成本转回假设 | 70.00 |
| import_batch_id | BIGINT | 否 | 来源批次 | 7 |

CHECK：month为1号，数量/金额/单价>=0，渠道/区域有效。缺失字段不以默认0替代；两个允许默认0的退款字段仅用于明确无退款假设的完整预算记录。

预算净收入=预算数量×净单价−预算退款；预算净成本=预算数量×单位成本−成本转回；毛利=二者之差。金额汇总保留精度，展示时到分。不再额外保存收入、毛利等重复字段。

不强制“当月退款<=当月成交收入”，因为可能包含历史销售的跨月退款；业务假设需单独检查合理性。索引(month,product_id,channel_code,region_code)，用于按期间读取单一版本。

## 11. budget_expenses：月度费用预算

粒度：版本×月×类别×部门×渠道归属×区域归属。PK/UK为上述六字段组合。FK=import_batch_id→import_batches.batch_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| budget_version | VARCHAR(32) | 否 | 与销售预算同一版本 | B2026_V1 |
| month | DATE | 否 | 预算月第一天 | 2026-09-01 |
| expense_category | VARCHAR(24) | 否 | 费用类别 | marketing |
| department | VARCHAR(8) | 否 | 部门 | D01 |
| channel_scope | VARCHAR(8) | 否 | C01/C02/C03或ALL共同渠道归属 | ALL |
| region_scope | VARCHAR(8) | 否 | R01/R02/R03/R04或ALL共同区域归属 | ALL |
| budget_amount | DECIMAL(18,2) | 否 | 本费用组预算 | 100.00 |
| import_batch_id | BIGINT | 否 | 来源批次 | 8 |

CHECK：月份为1号，金额>=0，部门、类别和范围代码有效。索引(month,expense_category,department)。

ALL不表示汇总了C01等行的“公司合计”，只表示一组共同费用。实际费用比较前将channel_code/region_code的NULL映射为ALL，按同一六字段粒度比较。缺失预算不自动变成零预算。

## 12. forecast_runs：预测运行（阶段9）

**实施说明（阶段9）**：以下12—14节是关系数据库存储的预留设计，目前未建这三张表。阶段9采用outputs/stage9/runs中的本地不可覆盖JSON保存同一运行、销售、费用粒度与基础/情景引用，版本ID为内容派生的FC9文本标识。单价及计算金额保留60位有效数字输出，事件金额及费用预测至分，未知用null；未按下表DECIMAL(18,4)截断。后续迁入专用结果库时再落实类型和约束，来源业务数据库保持只读。

粒度：一次保存的预测/情景版本。PK=run_id。base_run_id自引用FK→forecast_runs.run_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| run_id | BIGINT | 否/自增 | 预测版本身份 | 1 |
| cutoff_month | DATE | 否 | 最后一个已知实际月，写月首 | 2026-09-01 |
| target_year | SMALLINT | 否 | 预测目标年 | 2026 |
| scenario_name | VARCHAR(16) | 否 | base/optimistic/cautious/custom | base |
| base_run_id | BIGINT | 是 | 情景所基于的基础版本 | NULL |
| method | VARCHAR(32) | 否 | 方法标识 | driver_based |
| assumptions_json | JSON | 否 | 价格销量成本费用退款与模型参数 | 结构化假设对象 |
| created_at | DATETIME | 否 | 运行保存时间 | 2026-10-12 10:00:00 |

CHECK：cutoff_month为1号；场景与方法符合字典。跨行校验：目标年与截止月规则一致；情景引用基础run，截止月、目标年保持一致，引用自身不允许；实际月份不写入未来预测明细。第一版方法为last_year_same_month/recent_mean/driver_based。

## 13. forecast_sales：销售预测（阶段9）

粒度：运行×未来月×商品×渠道×区域。PK/UK为上述组合。FK：run_id→forecast_runs.run_id，product_id→products.product_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| run_id | BIGINT | 否 | 预测运行 | 1 |
| month | DATE | 否 | 未来月首 | 2026-10-01 |
| product_id | VARCHAR(32) | 否 | 商品 | P001 |
| channel_code | VARCHAR(8) | 否 | 渠道 | C01 |
| region_code | VARCHAR(8) | 否 | 区域 | R01 |
| forecast_quantity | INT | 否 | 预计成交件数 | 6 |
| net_unit_price | DECIMAL(18,4) | 否 | 折后退款前单价假设 | 110.0000 |
| unit_cost | DECIMAL(18,4) | 否 | 单位成本假设 | 70.0000 |
| refund_amount | DECIMAL(18,2) | 否 | 当月退款预测 | 110.00 |
| cogs_reversal_amount | DECIMAL(18,2) | 否 | 当月成本转回预测 | 70.00 |

CHECK：月首、驱动值>=0、代码有效。跨表检查month>cutoff_month且属于target_year。索引(month,product_id)。预计件数采用固定的非负四舍五入规则，基准与情景统一，规则在阶段9回测中记录。

## 14. forecast_expenses：费用预测（阶段9）

粒度：运行×未来月×类别×部门×归属。PK/UK=(run_id,month,expense_category,department,channel_scope,region_scope)。FK=run_id→forecast_runs.run_id。

| 字段 | 类型 | 可空/默认 | 含义 | 示例 |
|---|---|---|---|---|
| run_id | BIGINT | 否 | 预测运行 | 1 |
| month | DATE | 否 | 未来月份 | 2026-10-01 |
| expense_category | VARCHAR(24) | 否 | 费用类别 | marketing |
| department | VARCHAR(8) | 否 | 部门 | D01 |
| channel_scope | VARCHAR(8) | 否 | 渠道或ALL | ALL |
| region_scope | VARCHAR(8) | 否 | 区域或ALL | ALL |
| amount | DECIMAL(18,2) | 否 | 未来费用 | 100.00 |

CHECK：月首、amount>=0、代码有效。跨表检查未来月边界；不同时插入共同费用和包含该费用的总计。索引(month,expense_category)。

## 15. 受控编码字典

| 字段类别 | 允许值 | 说明 |
|---|---|---|
| 渠道 | C01、C02、C03 | 自营商城、平台商城、直播渠道 |
| 区域 | R01、R02、R03、R04 | 华东、华南、华北、西部 |
| 商品类别 | STORAGE、CLEANING、KITCHEN | 收纳、清洁、厨房用品 |
| 部门 | D01、D02、D03、D04 | 市场、销售、运营、管理 |
| 费用类别 | marketing、platform_commission、logistics、payroll、administration | 营销、平台佣金、物流、人工、管理 |
| 退款原因 | return_resalable、return_unsellable、compensation | 可回库/部分可回库退货、不可回库退货、无退货补偿 |
| 订单状态 | pending、completed、cancelled | 未确认、已确认、取消 |
| 批次状态 | pending、running、completed、completed_with_errors、failed | 待处理、运行、完成、含异常完成、失败 |
| dataset_type | products、customers、orders、order_items、returns、expenses、budget_sales、budget_expenses | 导入目标表，样本使用同一类别并单独文件 |
| 场景 | base、optimistic、cautious、custom | 基础、乐观、谨慎、自定义 |
| 费用共同归属 | 实际NULL，预算/预测ALL | 仅表示共同费用组，禁止把总计当事实行 |

第一版使用字典加CHECK/导入校验，不额外创建编码表。扩大编码范围时同步更新规则和校验。商品销售渠道/区域不得使用ALL或NULL。

## 16. 完整性核对清单

| 编号 | 校验内容 | 阶段3验证方法 |
|---|---|---|
| DQ01 | 主键和组合业务键不重复 | 尝试插入重复样本 |
| DQ02 | 外键引用有效 | 尝试未知客户、订单、商品、明细 |
| DQ03 | 数量、金额、折扣和状态组合合法 | 非法单行样本、CHECK与质量查询 |
| DQ04 | 每个有效订单至少有一条明细 | 订单左连接明细找缺失 |
| DQ05 | 退款属于已确认销售，日期不早于确认 | 关联查询 |
| DQ06 | 多次退款累计数量、金额、成本不超原交易 | 先按明细聚合退款，再比较原明细 |
| DQ07 | 成本转回有可回库数量依据 | 逐事件与原成本快照比较 |
| DQ08 | 日历完整、预算月首、版本一致 | 日历生成核对与预算查询 |
| DQ09 | 共同费用不与总计重复，来源行唯一 | 费用来源重复检查、汇总核对 |
| DQ10 | 批次及业务ID可追踪、导入冲突不覆盖 | 重复文件与不同内容同ID样本；自动化阶段5实施 |

预算合计和公司费用合计从明细算出，不能仅凭主键唯一证明不存在“明细+总计”重复，需要核对源数据含义。

## 17. 需求覆盖与建表边界

- Q01/Q02：orders+order_items+returns+products+dim_date；公司利润另加expenses。
- Q03：月度实际驱动字段+budget_sales，费用比较另用budget_expenses。
- Q04/Q05：阶段9使用本地JSON预测版本；forecast_runs、forecast_sales、forecast_expenses保留为后续关系数据库实现方案。
- F01：import_batches+业务ID/来源行唯一键+异常文件。
- F05：分析结果导出，不单独存另一份月报数字。

阶段3建立前10张表并导入小样本，后3张表本阶段仅完成设计。索引是初始方案，查询性能需要真实执行计划和数据量验证后调整。

技术依据：金额采用精确小数类型见[MySQL DECIMAL](https://dev.mysql.com/doc/refman/8.4/en/fixed-point-types.html)；表关系见[外键](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)；单行约束的适用范围见[CHECK](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html)；唯一索引空值行为见[CREATE INDEX](https://dev.mysql.com/doc/refman/8.4/en/create-index.html)。这些是设计依据，尚未证明本机版本已支持或执行所有约束。
