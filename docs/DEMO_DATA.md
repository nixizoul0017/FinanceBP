# 星辰优选模拟数据说明

[返回项目首页](../README.md) · [Windows应用指南](WINDOWS_APP.md) · [财务口径](reference/financial_rules.md)

“星辰优选”为虚构企业。公开数据中的客户编码、员工名称、商品、订单、退款、费用和预算均为人工构造，用于学习、作品演示和功能验收，不含真实企业交易、客户隐私或数据库密码。模拟数据不证明真实企业因果，也不构成经营预测承诺。

## 安装后怎样体验

1. 从项目首页下载EXE，安装后点击桌面 **FinanceBP** 图标。
2. 保留左侧“数据来源”为 **完整模拟数据**，选择2026年9月，预算 `B2026_V1`，点击“应用筛选”。
3. 切换左侧九个功能页面体验；需要部门和销售员分析时，选择 **多维模拟数据**，再应用月份、预算、分类及分析分组。
4. 用 **小样本核对** 逐笔检查财务计算；用 **异名模拟数据** 检查改名后的字段映射。

以上均读取内置文件，不需要安装MySQL或导入SQL。程序使用已应用条件计算，待选修改不会立即改变指标与导出。

## 四套样本的位置和用途

以下路径均相对源码项目根目录；应用内置对应资源，日常使用不需要手动寻找这些文件。

| 界面数据来源 | 数据目录 | 接入配置 | 范围和用途 |
|---|---|---|---|
| 完整模拟数据 | `data/demo/` 下的8张CSV业务表 | [demo_files.json](../configs/demo_files.json) | `XCYX`，2024-01-01至2026-09-30，完整经营分析、回测与月报 |
| 多维模拟数据 | `data/demo/multidimensional/` | [multidimensional_files.json](../configs/multidimensional_files.json) | `MULTI_DEMO`，2025-01-01至2026-09-30，动态分类与关联验证 |
| 异名模拟数据 | `data/demo/alternate/` | [demo_renamed_files.json](../configs/demo_renamed_files.json) | 与完整样本同一企业、同一期间及标准事实，原始字段另行命名 |
| 小样本核对 | `data/sample/stage3/` | [sample_files.json](../configs/sample_files.json) | `XCYX_SAMPLE`，2026年9月完整实际，另含截至10月5日的跨月退款边界事件 |

### 完整样本：规模与字段

| 文件 | 行数（不含标题） | 主要字段/粒度 |
|---|---:|---|
| products.csv | 20 | 商品编码、名称、类别；一行一个商品 |
| customers.csv | 3,000 | 虚构客户编码、注册日期 |
| orders.csv | 35,056 | 订单编码、客户、确认日期、状态、渠道及地区 |
| order_items.csv | 50,000 | 订单行、商品、数量、售价、折扣和历史成本 |
| returns.csv | 2,390 | 原销售明细、退款日期、退货数量、退款及可冲回成本 |
| expenses.csv | 363 | 费用日期、类别、部门、范围及金额 |
| budget_sales.csv | 2,880 | 预算版本、月份、商品/渠道/地区、销量、价格、成本及退款 |
| budget_expenses.csv | 132 | 预算版本、月份、费用类别和金额 |

5万条是**原始订单明细**，包含尚未确认及取消订单；进入标准财务分析的确认销售为47,535条，不能把两者视为同一计数。完整连续实际共33个月；2026年预算版本为 `B2026_V1`，预算覆盖全年。

逐文件行数、SHA256、生成种子、覆盖期间和预算假设保存在 [manifest.json](../data/demo/manifest.json)。字段设计与来源粒度见[数据字典](reference/data_dictionary.md)，映射以各接入配置为准。

### 多维样本：业务边界

销售事实附加销售部门、员工编码、门店和客户类型；员工资料表提供编码与姓名的多对一关联，加上原商品、渠道、地区共7个维度。

- 员工1在2026年7月调岗；8月对其6月销售的退款仍沿用6月销售部门，避免历史归属漂移。
- 2026年8月包含缺失部门、销售员的销售，进入“未归属”，金额不丢弃。
- `B2026_TEAM` 提供销售部门、销售员预算；`B2026_COMPANY` 只有原三维预算。门店及客户类型无对应预算，不自动补造。
- 公司费用部门与销售部门分别识别，费用不会自动分摊。组合毛利率按合计收入和毛利重新计算。

该样本销售252行、退款1行、费用21行、销售预算192行、费用预算24行、员工6行；其规模独立于5万行完整样本。配置包含所需分类和预测粒度，详情见[动态分类说明](reference/dynamic_dimensions.md)。

## 金额与复核值

源文件金额为**人民币元、不含税**，以十进制文本保存；界面可切换元或万元。实际退款以正数事件保存，分析时从收入中扣减；成本冲回单独处理，历史销售使用交易时成本。无可靠分摊规则时，公司费用与经营利润保持全公司口径。

| 样本与条件 | 净收入/元 | 毛利/元 | 公司费用/元 | 公司经营利润/元 |
|---|---:|---:|---:|---:|
| 完整样本，2026-09，全部销售 | 267,927.12 | 102,104.16 | 60,504.74 | 41,599.42 |
| 小样本，2026-09，全部销售 | 3,240.00 | 1,185.00 | 400.00 | 785.00 |

多维样本2026-09筛选员工编码 `1`，净收入为 **4,300.00元**。员工筛选不会把公司经营利润转换为该员工利润。原始独立基准见 [sample_sql_reference.json](../tests/fixtures/sample_sql_reference.json)，完整月报基准见 [report_reference.json](../tests/fixtures/report_reference.json)。

## 可复现生成与校验（开发者可选）

完整样本由 [generate_demo_data.py](../scripts/generate_demo_data.py) 及 [generate.py](../src/etl/generate.py) 生成，默认随机种子 **20261012**，原始订单行数 **50000**；同一脚本还生成异名数据与对应配置。多维样本由 [generate_multidimensional_demo.py](../scripts/generate_multidimensional_demo.py) 按确定规则生成，不使用随机种子。小样本为人工固定JSON，与SQL种子脚本及测试基准共同维护。

在源码环境中可运行：

```text
python scripts/stage5.py demo
python scripts/stage11.py
python scripts/check_project.py
```

分别检查小样本独立SQL基准与异名等价、17组完整财务/月报验收、公开文件及文档链接。结果写入本机 `outputs`，不进入公开源码。

需要重新生成时，在**源码副本**中运行下面两行；它们会覆盖演示文件及公开接入配置，普通使用不需要执行：

```text
python scripts/generate_demo_data.py --lines 50000 --seed 20261012
python scripts/generate_multidimensional_demo.py
```

[scenario_truth.json](../data/demo/scenario_truth.json) 记录人为设置的旺季、成本、折扣及退款变化，仅供学习与验收。分析和预测模块不得读取它作为业务结论或训练输入。预算增长假设记录在manifest中，属于模拟设计，不能视为企业真实目标。

## SQL与MySQL体验（可选）

[建表脚本](../sql/01_create_tables.sql)、[小样本种子](../sql/02_seed_sample.sql)及 [SQL基准核对](../sql/04_verify_samples.sql) 已随项目提供。完整CSV的可选演示导入入口为 `scripts/stage5.py mysql-import`；它会创建/写入指定演示库，**不要指向企业生产库或已有业务库**。默认文件体验无需执行这些步骤。

MySQL配置仅包含本机示例地址和密码环境变量名；不携带用户数据库或密码。数据库路径和可选接入操作见[源码使用指南](USER_GUIDE.md)，原始SQL脚本及兼容性基准均保留。
