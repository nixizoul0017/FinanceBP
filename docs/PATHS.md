# 路径变更表

## 2026-10-19 · 1.0.0 Windows 应用

| 路径 | 用途 |
|---|---|
| dist/FinanceBP-1.0.0-windows-x64-setup.exe | Windows 11 x64 独立应用安装包 |
| src/desktop/ | 安装资源/个人路径、窗口、后台、文件保存和迁移 |
| scripts/windows_app.py | 源码预览、冻结程序与后台的统一入口 |
| scripts/build_windows_app.py、scripts/windows_installer.iss | 固定环境的构建与安装脚本 |
| requirements-desktop-lock.txt | Windows Python 3.13 构建依赖锁定 |
| docs/WINDOWS_APP.md、docs/WINDOWS_ACCEPTANCE.md | 操作指南与实际验收状态 |
| %LOCALAPPDATA%/FinanceBP/runtime | 安装版预算/对账SQLite、分类方案、偏好 |
| %LOCALAPPDATA%/FinanceBP/forecasts/runs | 已保存的预测版本 |
| %LOCALAPPDATA%/FinanceBP/backups、exports、logs | 备份、默认导出位置、诊断日志 |
| outputs/desktop_build/ | 构建环境、工具、回归与隔离验收证据；不进入公开包 |
| dist/archive/FinanceBP-v0.*.zip | 历史源码包归档，保留原名 |
| dist/FinanceBP-v1.0.0.zip | 当前完整源码包，含独立的逐文件校验清单 |

源码模式的 outputs 路径和 START 入口保留；企业来源文件不移动、不打包。

整理日期：2026-10-14。路径相对项目根目录。文档已移动；基准和截图复制到发布位置；旧运行输出保留在本机，不随ZIP分发。

| 原路径 | 当前路径 |
|---|---|
| `docs/01_详细开发计划.md` | `docs/history/stages/01_详细开发计划.md` |
| `docs/02_数据库设计草案.md` | `docs/reference/database.md` |
| `docs/03_财务指标与模型口径.md` | `docs/reference/financial_rules.md` |
| `docs/04_执行清单.md` | `docs/history/stages/04_执行清单.md` |
| `docs/05_第一阶段操作指南.md` | `docs/history/stages/05_第一阶段操作指南.md` |
| `docs/06_业务规则.md` | `docs/reference/business_rules.md` |
| `docs/07_需求清单.md` | `docs/reference/requirements.md` |
| `docs/08_数据字典.md` | `docs/reference/data_dictionary.md` |
| `docs/09_阶段2学习与下一步.md` | `docs/history/stages/09_阶段2学习与下一步.md` |
| `docs/10_阶段3操作与学习指南.md` | `docs/history/stages/10_阶段3操作与学习指南.md` |
| `docs/11_阶段3验收记录.md` | `docs/history/stages/11_阶段3验收记录.md` |
| `docs/12_阶段4操作与学习指南.md` | `docs/history/stages/12_阶段4操作与学习指南.md` |
| `docs/13_阶段4验收记录.md` | `docs/history/stages/13_阶段4验收记录.md` |
| `docs/14_通用接入与最终产品设计.md` | `docs/reference/architecture.md` |
| `docs/15_阶段5操作与学习指南.md` | `docs/history/stages/15_阶段5操作与学习指南.md` |
| `docs/16_阶段5验收记录.md` | `docs/history/stages/16_阶段5验收记录.md` |
| `docs/17_阶段6操作与学习指南.md` | `docs/history/stages/17_阶段6操作与学习指南.md` |
| `docs/18_阶段6验收记录.md` | `docs/history/stages/18_阶段6验收记录.md` |
| `docs/19_阶段7操作与学习指南.md` | `docs/history/stages/19_阶段7操作与学习指南.md` |
| `docs/20_阶段7验收记录.md` | `docs/history/stages/20_阶段7验收记录.md` |
| `docs/21_阶段8操作与学习指南.md` | `docs/history/stages/21_阶段8操作与学习指南.md` |
| `docs/22_阶段8验收记录.md` | `docs/history/stages/22_阶段8验收记录.md` |
| `docs/23_阶段9操作与学习指南.md` | `docs/history/stages/23_阶段9操作与学习指南.md` |
| `docs/24_阶段9验收记录.md` | `docs/history/stages/24_阶段9验收记录.md` |
| `docs/25_阶段10操作与学习指南.md` | `docs/history/stages/25_阶段10操作与学习指南.md` |
| `docs/26_阶段10验收记录.md` | `docs/history/stages/26_阶段10验收记录.md` |
| `docs/27_阶段11操作与迁移指南.md` | `docs/history/stages/27_阶段11操作与迁移指南.md` |
| `docs/28_阶段11整体验收记录.md` | `docs/history/stages/28_阶段11整体验收记录.md` |
| `docs/29_阶段11经营案例与面试材料.md` | `docs/examples/business_cases.md` |
| `docs/30_阶段11五分钟演示稿.md` | `docs/examples/demo_script.md` |
| `outputs/stage10/ (default CLI)` | `outputs/reports/` |
| `outputs/stage10/report_page.png` | `docs/assets/report.png` |
| `outputs/stage10/report_result.json` | `tests/fixtures/report_reference.json` |
| `outputs/stage11/ (file acceptance)` | `outputs/validation/` |
| `outputs/stage4/reference_results.json` | `tests/fixtures/sample_sql_reference.json` |
| `outputs/stage5/demo_monthly.json` | `tests/fixtures/monthly_reference.json` |
| `outputs/stage7/overview.jpg` | `docs/assets/overview.jpg` |
| `outputs/stage8/revenue_bridge.jpg` | `docs/assets/revenue_bridge.jpg` |
| `outputs/stage9/ (default CLI)` | `outputs/forecasts/` |
| `outputs/stage9/forecast_page.png` | `docs/assets/forecast.png` |
| `outputs/stage9/runs/` | `outputs/forecasts/runs/` |

当前日常入口：Windows用根目录START.cmd→scripts/launch_windows.ps1→scripts/desktop_launcher.py；Mac用根目录START.command→scripts/desktop_launcher.py。scripts/manage.py与manage.ps1保留为可选维护入口；原scripts/run_stage系列的.ps1供Windows学习/开发。新文档从[文档首页](README.md)查找，后续改动写入[项目日志](PROJECT_LOG.md)。

阶段5 Notebook从notebooks/阶段5_Python读取与校验.ipynb归入docs/history/notebooks/阶段5_Python读取与校验.ipynb，查找项目根目录的代码已适配更深的目录。原空notebooks目录已移除。

旧GitHub准备包outputs/stage11/release/FinanceBP_Stage11.zip作为阶段产物保留；旧版本包为历史交付，当前三色驾驶舱及Python3.13/3.14一键入口以最新版本段落列出的ZIP为准。主题代码在src/dashboard/theme.py及cockpit.css，本机显示偏好在outputs/runtime/ui_preferences.json，不进入发布包。

0.3.0的分组导航在src/dashboard/navigation.py，布局仍在app.py与src/dashboard/cockpit.css，加载截图为docs/assets/cockpit-loading.jpg；本次验证日志统一放outputs/ui_validation。

## 2026-10-15 · 0.4.0新增路径

| 路径 | 内容 |
|---|---|
| src/etl/dimensions.py | 动态目录、字段推荐、安全关联和归属校验 |
| src/dashboard/dimension_setup.py | 首次扫描与分类映射确认 |
| src/dashboard/dimension_ui.py | 分类位置、筛选和方案界面 |
| src/dashboard/dimension_store.py | 本机映射、最近布局、命名方案原子保存 |
| configs/multidimensional_files.json | 独立多维样例v2接入配置 |
| data/demo/multidimensional/ | 新样例，原演示数据未移动 |
| docs/reference/dynamic_dimensions.md | 当前分类操作与配置说明 |
| outputs/runtime/dimension_views.json | 本机私有记忆，不进入项目ZIP |
| outputs/dynamic_dimensions/ | 本次验收、日志与截图，不随公开ZIP分发 |
| dist/FinanceBP-v0.4.0.zip | 新版完整项目包 |

根目录启动入口和原文档路径保留，后续分类相关更新继续追加项目日志。

## 2026-10-16 · 0.5.0新增路径

| 路径 | 内容 |
|---|---|
| src/finance/ | 本机预算、对账确认、异常及操作追溯 |
| src/etl/controls.py | 标准化/分类关联前独立来源控制数 |
| src/analysis/historical.py | 历史实际环比/同比差异桥 |
| src/dashboard/finance_ui.py | 预算工作台、对账与跟进、历史比较界面 |
| docs/reference/finance_workflow.md | 新四项功能的统一操作说明 |
| outputs/runtime/finance_workspace.sqlite3 | 本机私有财务记录，不进入公开项目包 |
| outputs/finance_workflow/ | 本次验收日志、模板预览和回归证据 |
| dist/FinanceBP-v0.5.0.zip | 0.5.0历史完整项目包，双系统入口保留 |

原阶段文档继续留在history，不再增加根目录启动文件。

## 2026-10-16 · 0.5.1统一应用筛选

| 路径 | 用途 |
|---|---|
| src/dashboard/filter_state.py | 已应用请求规范化、校验和失效后待选修复 |
| src/dashboard/dimension_ui.py | 局部更新筛选区、待选/已应用分离及方案操作 |
| src/dashboard/result_cache.py | 计算条件独立于外观的会话缓存 |
| tests/test_filter_apply.py | 统一应用交互回归 |
| docs/reference/dynamic_dimensions.md | 分类、方案及应用/取消统一操作说明 |
| outputs/filter_apply | 本次验收日志与浏览器证据（本机，不入包） |
| dist/FinanceBP-v0.5.1.zip | 当前完整项目包；Windows/Mac入口保留 |

本次未移动原始样本、启动入口或阶段文档；项目日志仍统一追加。
