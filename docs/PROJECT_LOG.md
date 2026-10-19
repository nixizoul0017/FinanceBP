# 项目日志

这是项目持续更新的主记录。新任务追加到文末，版本变化同时写入根目录CHANGELOG.md；不删除历史决定。文件路径均相对项目根目录，迁移对应关系见[路径变更表](PATHS.md)。

当前应用版本：1.0.0，公开发布标识为v1.0.0-rc.1体验版。Windows日常入口：安装后的FinanceBP桌面图标；Windows/Mac源码入口另见SOURCE_RUN.md。范围：个人模拟电商经营分析；另一台实体电脑和真实企业适配仍待实际确认。阶段1—10按开发顺序汇总，具体日期以原始档案为准，不推测未记录的日期；后续版本按日期追加。

## 阶段1：确定业务问题与口径

目标是完成从SQL取数到经营分析和预算预测的个人作品。明确虚构企业星辰优选、人民币不含税、确认销售/退款/费用的规则，以及收入、毛利、预算和未来假设五类管理问题。费用没有可靠分摊规则时保留公司口径。

产物：[业务规则](reference/business_rules.md)、[需求清单](reference/requirements.md)、[财务口径](reference/financial_rules.md)。原始学习过程见[阶段1指南](history/stages/05_第一阶段操作指南.md)，原始总计划见[开发计划档案](history/stages/01_详细开发计划.md)。

## 阶段2：数据库设计

明确订单、明细、退款事件、费用、销售预算与费用预算的粒度；使用键和约束防止重复、孤立记录及多表连接放大。销售成本保留历史快照，退款按发生月并关联原交易维度。

产物：[数据库设计](reference/database.md)、[数据字典](reference/data_dictionary.md)、[学习档案](history/stages/09_阶段2学习与下一步.md)。后续SQL在sql目录实施。

## 阶段3：SQL建表、小样本和约束

在MySQL建立演示库，导入可手算的小样本，验证约束、质量与同名库保护。用户在原3306服务执行成功。当前样本基准为tests/fixtures/sample_sql_reference.json：2026-09净收入3,240、净成本2,055、毛利1,185、费用400、经营利润785元。

入口：scripts/run_stage3.ps1；SQL：sql/00_create_database.sql至05_constraint_tests.sql。[操作](history/stages/10_阶段3操作与学习指南.md) · [验收](history/stages/11_阶段3验收记录.md)。

## 阶段4：SQL经营分析

建立明细、月度、维度、趋势和预算视图，使用连续月历处理缺月份，避免把上一次有交易月份误当作上月。各类事实分别汇总后组合，形成独立财务基准。

入口：scripts/run_stage4.ps1；SQL：sql/stage4。[操作](history/stages/12_阶段4操作与学习指南.md) · [验收](history/stages/13_阶段4验收记录.md)。历史查询日志留在本机outputs/stage4，固定基准已迁至tests/fixtures。

## 阶段5：数据处理、完整模拟与通用接入

生成33个月、50,000条原始订单明细；处理取消、跨月退款、重复导入、失败回滚和重试。配置映射将两套异名来源转换为同一标准事实，MySQL分析读取使用只读事务。更换企业仍需核对语义，不能只改标签。

模块：src/etl；入口：scripts/run_stage5.ps1；数据：data/demo、data/sample；配置：configs。[操作](history/stages/15_阶段5操作与学习指南.md) · [验收](history/stages/16_阶段5验收记录.md) · [接入设计](reference/architecture.md) · [可选Notebook练习](history/notebooks/阶段5_Python读取与校验.ipynb)。Notebook编辑器为学习工具，日常程序不依赖它。

## 阶段6：统一财务计算

建立收入、成本、毛利、费用、经营利润、趋势和预算计算。区分确定为零与缺数据；销售维度筛选不会造成公司费用分摊。金额尽量保持精确类型，显示时才舍入。

模块：src/analysis/metrics.py、comparison.py、service.py；入口：scripts/run_stage6.ps1。[操作](history/stages/17_阶段6操作与学习指南.md) · [验收](history/stages/18_阶段6验收记录.md)。

## 阶段7：浏览器工作台

用Streamlit和Plotly提供可筛选的经营分析页面、来源切换、数据校验与下载。切换来源清理旧快照，数据读取失败清理旧结果。后续阶段扩展到七页。

入口代码：app.py；展示模块：src/dashboard；当前日常入口START.cmd调用scripts/manage.ps1，再启动scripts/run_stage7.ps1。[操作档案](history/stages/19_阶段7操作与学习指南.md) · [验收](history/stages/20_阶段7验收记录.md) · [截图](assets/overview.jpg)。

## 阶段8：预算驱动拆解

建立收入PVM、毛利桥与公司利润桥，按总销量→结构→均价拆解共同商品，新增/退出及退款分开处理；舍入尾差不当作经营因素。金额贡献支持调查，不直接证明业务因果。

模块：src/analysis/pvm.py、variance.py；SQL：sql/stage8；12场景、5,083项独立SQL核对通过，阶段11重新执行。[操作](history/stages/21_阶段8操作与学习指南.md) · [验收](history/stages/22_阶段8验收记录.md) · [截图](assets/revenue_bridge.jpg)。

## 阶段9：预测、回测和未来情景

实现上年同月、近期均值、业务驱动三种方法，以历史截止点回测评估；未来情景只改剩余月份，历史实际不改写。版本按内容保存，不覆盖已冻结结果。

模块：src/analysis/forecast.py、scenario.py、forecast_store.py；当前输出outputs/forecasts，版本在runs子目录；旧outputs/stage9/runs的3份版本保留并复制到新位置。阶段11重新通过3,648项SQL数值核对。[操作](history/stages/23_阶段9操作与学习指南.md) · [验收](history/stages/24_阶段9验收记录.md) · [截图](assets/forecast.png)。

## 阶段10：经营点评与月报

用户确认Excel作为当次快照，改假设后从网页重新导出。通过openpyxl生成10表月报、Markdown和精确JSON；每条数值点评绑定事实ID及来源，区分事实、金额分解、模型测算和调查建议。未接外部大模型。

模块：src/reporting；入口：scripts/run_stage10.ps1；当前命令行输出outputs/reports。默认报告包含26项事实引用，报告身份R10_2d54d27c9ecd3bef3cea585c，固定快照在tests/fixtures/report_reference.json。[操作档案](history/stages/25_阶段10操作与学习指南.md) · [验收](history/stages/26_阶段10验收记录.md) · [截图](assets/report.png)。

## 2026-10-14 · 阶段11：整体验收与作品材料

在本机独立目录、新.venv和临时MySQL33324重建。原项目与新环境各143项回归通过；独立SQL、导入回滚、预算驱动、预测、10表月报和真实浏览器下载一致性核对通过。此为本机独立环境，另一台实体电脑尚未实际操作。

完整文件验收17组通过；新目录单次耗时62.863秒。首次8批数据共93,841条源记录，批次耗时合计14.527秒；这些是本机模拟数据实测，不用于推断企业效率提升。临时数据库与临时看板已关闭，原用户MySQL保留。

产物：[验收档案](history/stages/28_阶段11整体验收记录.md)、[原迁移指南](history/stages/27_阶段11操作与迁移指南.md)、[三案例](examples/business_cases.md)、[演示稿](examples/demo_script.md)。旧证据在本机outputs/stage11，当前复验入口为START菜单3，结果写入outputs/validation。

## 2026-10-14 · 0.1.0目录整理与本地交付

**用户目标**：形成整体项目文件，准备GitHub所需README、启动入口和可持续项目日志，先不上传。

**实施**：根目录提供START.cmd、README、CHANGELOG和VERSION；安装、启动、验收和打包集中在一个菜单。原30份文档按当前参考、案例和历史阶段分类，完整过程汇入本日志。三份固定基准迁至tests/fixtures，四张截图迁至docs/assets；旧预测版本保留并复制。新包不含个人运行环境、输出或日志。

**路径与交付**：参见[PATHS](PATHS.md)和history/path_changes.json。源码包统一为dist/FinanceBP-v0.1.0.zip，包含整个可运行项目；上传时应提交解压后的源码目录。没有执行GitHub创建、提交或推送。

**验证**：目录调整后143项回归全部通过（164.472秒）。在含中文与空格的独立解压目录重新安装Python依赖，依赖一致性检查通过；通过统一入口执行17组文件验收全部通过（20.049秒），报告身份仍为R10_2d54d27c9ecd3bef3cea585c。实际浏览器打开该目录的看板，2026-09净收入267,927.12、毛利102,104.16、经营利润41,599.42均与基准一致。START菜单退出、环境检查、学习Notebook的5个代码单元均通过。文档链接、Python语法和发布清单通过检查；私有配置/输出排除、模板含密码拒绝、缺少固定基准拒绝三项打包保护验证通过。生成ZIP时核验CRC及逐文件SHA-256。

**证据**：本机outputs/organization下的full_tests.log、relocated_verify.log、package_guards.json、menu.log；独立验收结果在outputs/organization/验收 空格/FinanceBP/outputs/validation。最终结构检查与发布清单在outputs/validation。发布包不携带本机测试目录。此次未重跑MySQL验收，数据库结果引用阶段11记录；另一台实体电脑仍待实际操作。

**下一步**：用户按使用指南亲自操作、另一台实体电脑验证；有新功能时按下面模板追加记录。用户学习与里程碑A/B/C不由自动检查代替。

## 2026-10-14 · 0.1.1双系统启动入口

**目标**：同一个项目包提供Windows和Mac启动入口，分类写明打开方式与运行环境。

**改动与路径**：新增根目录START.command、.gitattributes和scripts/manage.py；Windows继续用START.cmd→scripts/manage.ps1，Mac用START.command→scripts/manage.py。README、USER_GUIDE、DEVELOPMENT、文档首页同步区分系统。修改scripts/package_project.py和check_project.py，将两个入口设为必需文件，检查Mac换行，ZIP保存其执行位；版本更新为0.1.1，交付路径dist/FinanceBP-v0.1.1.zip。

**决定**：两个系统共享Python业务代码、模拟数据和requirements.txt，分别在本机创建.venv；要求Python3.14、pip、venv与可用包源。Mac入口核对解释器版本，等待服务健康响应后打开浏览器。实体Mac、芯片架构对应依赖安装和最低macOS版本尚未实测，不将Windows运行或静态检查视作Mac通过。

**验证**：新增启动入口的6项专项检查通过，覆盖端口占用、启动退出/超时、失败不打开浏览器且清理进程、就绪后打开浏览器、验收失败传递。Windows本机运行新管理入口菜单与环境检查通过；通过该入口运行17组文件验收全部通过（22.342秒），月报身份不变。实际启动自动避开原8501服务，选择8502，健康响应HTTP200/ok；原8501仍为HTTP200/ok。文档链接/源代码语法/必需入口与Mac换行检查通过。打包时核对逐文件哈希及ZIP中START.command的0755执行位。当前Windows未提供Bash，未执行Mac的Shell入口，也未在实体Mac安装依赖；不计为Mac运行通过。

**证据**：本机outputs/organization/platform_launchers下的tests.log、menu.log、check.log、verify.log、startup.log、package.log、archive_check.json；最终发布清单在outputs/validation/release_manifest.json。关闭本次临时8502服务，保留用户正在使用的8501。

**后续**：在实体Mac解压本包，完成首次安装、菜单启动、默认指标与月报验收，再记录芯片、macOS、Python版本及依赖安装结果。

## 2026-10-14 · 0.1.2一键打开与错误提示

**背景**：用户Mac已有Python3.13，旧0.1.1入口只允许3.14；Windows启动后查看旧网址仍可能连接失败。用户要求双击后直接使用默认浏览器进入页面，并在环境出错时清楚弹窗。

**路径与改动**：Windows根目录START.cmd改为调用新增scripts/launch_windows.ps1；Mac的START.command默认调用新增scripts/desktop_launcher.py，两系统共用图形进度、环境检查、自动安装依赖和就绪后打开浏览器。scripts/manage.py/manage.ps1保留为高级维护入口。新增tests/test_desktop_launcher.py，扩展test_launcher.py；README、USER_GUIDE、DEVELOPMENT、PATHS、CHANGELOG与发布清单同步更新，版本包为dist/FinanceBP-v0.1.2.zip。

**决定**：支持完整64位Python3.13/3.14，图形入口要求Tk；不自动安装系统Python。缺Python/Tk用系统弹窗，其他问题区分项目文件、创建环境、pip、依赖安装/加载、服务和浏览器，显示原因、处理办法和日志。首次运行自动创建.venv并补全锁定依赖；既有同项目服务必须核对进程命令与健康响应后才复用。环回健康检查绕过HTTP代理；Windows停止时处理自身进程树，避免只关闭venv父进程而留下服务。

**验证**：Windows实际运行一键引导，图形窗口显示“程序已就绪”，系统默认Edge自动打开经营分析页面，用户无需输入数字或网址。Python3.13.16在独立测试环境安装全部锁定依赖成功，完整157项回归通过（171.190秒），17组文件验收通过（20.392秒），报告身份保持R10_2d54d27c9ecd3bef3cea585c。新增进程树检查后的最终15项启动专项检查在Python3.13与3.14各自通过。新控制器实际启动8510服务、核对已运行实例成功、关闭后健康检查不再响应；未遗留自己的服务进程。137个文档链接、源代码语法与发布结构检查通过，ZIP核对逐文件哈希和Mac入口的执行位。

**证据与边界**：outputs/organization/python313保存安装、tests_host.log、verify.log；outputs/organization/one_click保存最终启动测试、集成及包检查；运行日志在outputs/runtime。图形正常就绪已观察，缺文件错误弹窗的视觉验收因用户按Escape中止，未声明完成；错误分阶段传递已有专项测试。没有在实体Mac安装依赖、运行Tk或浏览器，没有重跑MySQL验收。测试目录/运行日志不随ZIP分发，也未上传GitHub。

**后续**：用户用新版完整ZIP替换旧分发目录，在Mac Python3.13下双击START.command完成实体Mac验证；如果弹窗报告组件或安装问题，保留日志补充验证记录。

## 2026-10-15 · 0.1.3修复Windows误报未找到Python

**用户现象**：这台Windows电脑已有Python，双击START仍弹出“Python环境：未找到Python”。

**确切原因**：入口由START.cmd调用系统Windows PowerShell5.1；它在原生命令参数中去掉了探测代码内嵌的双引号，使`struct.calcsize("P")`变成`struct.calcsize(P)`，Python因此报NameError。入口隐藏了探测的标准错误，将检测失败误报成没有Python。此前在PowerShell7里直接调用脚本的验证没有充分覆盖此边界。

**修改与路径**：scripts/launch_windows.ps1改用不含内嵌字符串的sys.maxsize探测64位，增加-CheckOnly供无弹窗验证；同步修复scripts/manage.ps1和setup_python.ps1中的同类参数引号。新增tests/test_windows_bootstrap.py，更新VERSION、CHANGELOG、README与当前指南，发布包dist/FinanceBP-v0.1.3.zip。未修改财务计算或依赖。

**实际验证**：用系统powershell.exe 5.1.26100.9444复现原NameError和退出码1；修复后同入口输出PYTHON_READY。Python3.13与3.14下各2项实际Windows5.1回归通过，覆盖现有环境、带空格且没有.venv的新目录、指定及自动查找Python；15项原启动专项检查通过。直接运行START.cmd后出现图形窗口，实际服务http://127.0.0.1:8501健康检查返回HTTP200/ok。通过系统5.1运行维护打包入口，再检查ZIP哈希与必需入口。

**证据**：本机outputs/organization/windows_detection下的before.log、after.log、tests313.log、tests314.log、launcher_tests.log、actual_start.json及package.log；发布结构和清单在outputs/validation。用户无需重装Python。此修复只针对已复现的Windows入口问题，实体Mac仍待验证，未重跑财务全套/MySQL验收，也未上传GitHub。

## 2026-10-15 · 0.2.0三色经营驾驶舱

**用户决定**：深海蓝驾驶舱、松石青、石墨紫三种配色均加入正式程序，提供随时切换的颜色按钮，形成新版项目包。

**实现与路径**：新增src/dashboard/theme.py（Palette令牌、偏好白名单与原子保存）、src/dashboard/cockpit.css（驾驶舱界面）；app.py增加侧栏“外观配色”按钮并将趋势、维度、预算桥与预测图接入主题。默认配置同步为深海蓝；src/dashboard/theme.py、cockpit.css设为必要发布文件。新增tests/test_dashboard_theme.py，实机截图在docs/assets/cockpit-navy.jpg、cockpit-teal.jpg、cockpit-plum.jpg、cockpit-colors.jpg。README、USER_GUIDE、DEVELOPMENT、PATHS与CHANGELOG同步更新，交付dist/FinanceBP-v0.2.0.zip。

**界面与口径**：使用深色侧栏、浅色画布、白色指标卡及统一金额排版；保留销售筛选范围与公司全口径分区，避免将公司费用/利润混入销售维度。配色回调只保存显示偏好，不清空engine、筛选、分析/预测缓存和报告。预算桥有利/不利仍为统一绿/红，实际/预测保留实线/虚线。使用原生可键盘操作的颜色单选控件。

**本机偏好**：outputs/runtime/ui_preferences.json仅记录版本与白名单主题键，不含业务数据或凭据；刷新、重启时读取，损坏时默认深海蓝，不可写时当前会话照常生效并提示。文件不随ZIP分发，新电脑默认深海蓝。截图验证后本机恢复深海蓝。

**实际验证**：168项完整回归全部通过（382.215秒）；8项新增配色专项在Python3.14通过、在Python3.13独立环境再次通过（47.779秒），覆盖三色×七页、图表x/y及指标值不变、筛选/单位/缓存保留、生成的Excel字节与报告身份不变、假设保留、刷新恢复和异常偏好回退。17组文件验收通过（56.797秒），报告身份仍为R10_2d54d27c9ecd3bef3cea585c。真实浏览器实际切换三种颜色，核对弹层、数据来源文字、金额字号、默认值及恢复，并保存实机截图。

**证据与交付**：本机outputs/organization/theme_release中的full_tests.log、theme_tests.log、theme_tests313.log、acceptance.log及package.log；最终结构与发布清单在outputs/validation。打包检查包含主题源码、样式和截图，排除本机偏好，核对ZIP逐文件哈希与Mac入口执行位。未重跑MySQL专用验收，实体Mac仍待实测；未上传GitHub。

## 2026-10-15 · 0.3.0驾驶舱布局与显著加载

**目标与背景**：用户要求删除顶部被遮挡的小字，按已选效果图重新落实正式界面，侧栏改为分组图标导航，切换时明确显示正在加载，并检查整体布局。

**改动与路径**：app.py重排白色顶栏、页面标题/月报快捷入口、集中筛选栏、四个核心指标、收入面积趋势和预算执行进度；销售范围改为可展开筛选。新增src/dashboard/navigation.py，使用三组原生图标按钮与page会话状态替代圆点单选导航。src/dashboard/cockpit.css统一留白、卡片、数字单位、按钮对齐、窗口适配及加载遮罩；保留三色和启动入口。更新tests/test_stage7_app.py、test_stage9_app.py、test_stage10_app.py、test_dashboard_theme.py与validate_stage7_mysql.py的界面驱动，原始金额基准显式采用元。

**口径与交互决定**：核心指标为当前销售范围的净收入、毛利和毛利率，加公司全口径经营利润；费用未分摊，利润不随销售维度筛选变化。成本与公司费用仍可在总览下方核对。完整模拟数据默认万元，小样本默认元，切换仅格式化显示。预算未知仍为“—”并明确说明，不以缺失替代零；进度条仅将视觉长度限制为0—100%，标签保留实际完成率。加载遮罩跟随Streamlit实际运行状态立即出现、完成或失败后退出，不加入固定等待；支持减少动态效果设置。

**布局复核**：真实浏览器检查三色、页面切换、加载状态与指标显示；检查1280、1000、740及390像素窗口，适配四列、两列及单列指标。收起侧栏时发现统一隐藏工具栏也隐藏了展开入口，已改为仅隐藏部署/菜单项，保留原生展开按钮；窄窗口为按钮预留位置。预算进度条进一步统一主题色，移除底层默认蓝色残留。实机截图更新于docs/assets/cockpit-*.jpg，新增cockpit-loading.jpg。

**验证结果**：170项完整回归通过（110.901秒）；最终10项界面专项通过（13.269秒），同10项在独立Python3.13通过（13.360秒），覆盖三色×七页、导航后筛选/缓存保留、月报快捷入口、单位切换与报告快照。17组文件验收通过（14.061秒），报告身份仍为R10_2d54d27c9ecd3bef3cea585c。界面检查证据与测试日志在outputs/ui_validation，结构与发布清单在outputs/validation。

**交付与边界**：README、USER_GUIDE、DEVELOPMENT、PATHS、CHANGELOG与VERSION同步更新，当前完整包为dist/FinanceBP-v0.3.0.zip。Windows/Mac入口、依赖及财务模型保持兼容；实体Mac和真实企业接入仍待验收。本次未重跑MySQL专项，未上传GitHub。

## 2026-10-15 · 0.3.1侧栏留白与重叠修正

**现象与原因**：用户指出品牌说明挨着配色按钮、导航分组标题挨着选中按钮。实际浏览器测量发现原生Markdown容器默认负底边距为-16px，但本项目的品牌/企业信息/分组标题使用没有段落底边距的HTML，导致品牌说明与按钮重叠约4px，分组标题也被后续按钮压住。

**修改与路径**：仅调整src/dashboard/cockpit.css，针对三个HTML区块取消原生负底边距；明确品牌名称与副标题行高，品牌区下方增加18px内留白，导航标题采用内部上下留白。侧栏内容横向边界约24px，企业信息单独分区，根容器间距8px；移除对所有嵌套容器一律5px的挤压。更新docs/assets/cockpit-*.jpg截图、README、PATHS、CHANGELOG与VERSION，形成dist/FinanceBP-v0.3.1.zip。

**验证范围**：真实浏览器核对品牌副标题与配色按钮间隔为26px，分组标题区块与首个按钮之间为8px，文字另有10px底部内留白；已无上述重叠，桌面无横向溢出。配色和导航继续使用原生控件。此版本只改样式，没有改动财务计算或交互逻辑，未重复运行0.3.0的170项财务/功能回归；另在740px、390px窗口展开侧栏核对文字、按钮边界和分组间距，并恢复默认窗口；三色实机截图已更新。项目结构与ZIP完整性已检查，证据在outputs/ui_validation/sidebar_spacing.json及spacing_package.log。

## 2026-10-15 · 0.3.2连接表单文字与光标修正

**用户现象与原因**：侧栏将所有input文字设成白色，而Streamlit 1.65的普通文本框使用React Aria与stTextInputRootElement，仍为浅色背景；原有BaseWeb输入框选择器未覆盖它。文字和继承文字颜色的原生光标因此在浅底上不可见。

**修改与路径**：src/dashboard/cockpit.css移除侧栏input一律白字的规则，普通文本、密码及端口采用白底与主题深色文字，明确caret-color和文本光标。聚焦时使用focus-within边框及侧栏浅色轮廓；补充占位文字、选中文字、密码眼睛按钮及数字按钮的颜色。来源下拉保留深底白字和白色光标，读取按钮使用主题底色和白字。未新增模拟光标或固定闪烁动画，使用浏览器原生可编辑输入框。

**实际检查**：在独立浏览器会话打开MySQL表单，核对三色下五个输入项的文字/背景/光标颜色与可编辑状态；实际输入演示数据库名，点击后输入框获得焦点、选区收拢并显示深色竖线及聚焦边框；核对Ctrl+A选中、Tab切换、空密码框及密码显示/隐藏按钮。只检查本地表单，没有提交连接、输入真实密码或读写数据库。实机截图为docs/assets/mysql-input-focus.jpg，检查记录在outputs/ui_validation/input_contrast.json。

**交付与验证边界**：更新README、USER_GUIDE、PATHS、CHANGELOG和VERSION，形成dist/FinanceBP-v0.3.2.zip。项目结构与ZIP完整性检查作为本次发布验证；本次为样式修正，财务/连接逻辑沿用0.3.0验证，未重复运行财务全套回归，未上传GitHub。

## 2026-10-15 · 0.4.0动态分类与分析方案

**目标**：执行已确认的动态分类计划，将固定商品/渠道/地区升级为来源决定的目录，贯通七页筛选、独立联合分组、预算与预测边界、长期布局记忆及命名方案；保留双系统一键入口，不做桌面封装，不上传GitHub。

**接入与计算**：新增src/etl/dimensions.py，实现字段推荐、稳定编号、编码/名称映射、数值编码归一、多对一关联和行数金额校验；src/etl/sources.py兼容v1/v2，MySQL按配置表只读取样、读取类型与注释，空CSV保留字段。src/analysis/metrics.py提供统一目录、动态Filters及有序分组，退款沿原销售归属，缺失进入未归属。comparison.py、variance.py按各预算版本粒度比较；forecast.py、scenario.py固定模型粒度、限制截止时点，历史归属不足或模型不支持时保留未知。较粗模型与细粒度预算按共有粒度检查覆盖，不生成不存在的细分预测。预测分类汇总保留缺失成本，避免把未知求和为0。

**界面与记忆**：新增src/dashboard/dimension_setup.py、dimension_ui.py、dimension_store.py，三个常驻位置、横向额外分类行及默认展开；更换/移除清除旧对象，收起保留摘要。独立分组可选多个字段，图表前20组，表格/下载保留全部。按企业与稳定接入配置保存布局、分组和方案身份，方案支持另存/更新/重命名/删除/导入导出。输出只在outputs/runtime/dimension_views.json，原子保存，公开包排除；不长期保存具体对象、月份、密码或预测假设。新增月份文件仍保留原布局；来源主动修改分类后，不用旧本机映射恢复已删除维度。实机修正下拉框旧显示与后台新状态不同步的问题，并明确配色初始选中项。

**导出与样例**：app.py七页、src/dashboard/view_model.py及src/reporting/service.py、tables.py同步新维度。月报记录实际筛选、分组、目录和模型/预算粒度；条件或分组改变后提示重新生成，Excel仍10张表。新增configs/multidimensional_files.json、data/demo/multidimensional/及scripts/generate_multidimensional_demo.py，含252销售、1跨调岗退款、21费用、192销售预算、24费用预算、6员工，覆盖缺失归属、两种预算粒度及模型未采用的客户类型；原样本与原完整数据未修改。

**实际验证**：Windows Python3.14完整回归201项通过，新增用例在tests/test_dynamic_dimensions.py（25项）和test_dynamic_dimensions_app.py（6项）；Python3.13独立环境25项多维专项通过。scripts/stage11.py继续17组通过，报告R10_2d54d27c9ecd3bef3cea585c及财务基准不变。scripts/validate_stage11_mysql.ps1在独立33324临时实例通过原有导入/回滚、14组财务验证、5083项驱动SQL、3648项预测SQL及月报比对，并新增tests/validate_dynamic_mysql.py的7项多维检查；临时服务已关闭清理，没有使用3306用户库。

**实机与证据**：三色、1280/740/390像素窗口、侧栏、第四位恢复展开、人员名称、方案保存/恢复、部门＋销售员联合汇总、加载遮罩、输入深色文字与深色光标已检查。当前联合分析截图docs/assets/dynamic-dimensions.png。详细日志与结果保留outputs/dynamic_dimensions/final_regression.log、python313_multidimensional.log、legacy_acceptance.log、mysql_regression.log、mysql_acceptance.json、browser_layout_checks.json、acceptance_summary.json；本机日志不进入公开包。

**文档和交付**：更新README、USER_GUIDE、DEVELOPMENT、PATHS、CHANGELOG、VERSION，新增docs/reference/dynamic_dimensions.md作为统一分类说明。scripts/package_project.py白名单纳入新配置，生成dist/FinanceBP-v0.4.0.zip，保留START.cmd/START.command、源码、模拟数据、文档、测试和逐文件校验清单，排除本机记忆、凭据、缓存和运行环境。项目结构、文档链接与ZIP完整性检查在outputs/validation中。 另将ZIP解压到独立目录，使用随包多维配置计算销售员1的2026-09净收入4300元验证通过，记录在outputs/dynamic_dimensions/release_smoke.json。

**验证边界与后续**：已验证Windows及本机Python3.13/3.14；实体Mac、另一台实体电脑、真实企业数据尚未实测。历史部门必须由交易时点快照提供，不能从员工当前部门推断；一对多归属和分配规则、其他财务口径仍需另行定义。后续变更继续在本日志追加，不改写阶段档案。

## 2026-10-16 · 0.5.0预算、对账、经营变化与跟进

**授权与目标**：用户同意优先补齐四项财务能力：预算维护、对账和月份确认、无预算的历史经营变化解释、异常及后续行动。保留单机网页形式、三色驾驶舱和双系统入口，不封装桌面应用，不上传GitHub。

**预算与数据边界**：新增src/finance/budgets.py、store.py，下载企业模板，独立选择销售/费用粒度，校验编码、重复、金额、年度和公式缓存。支持金额预算与驱动预算；空成本保持未知，公司预算不分摊到销售员。草稿、发布原始预算、关联调整版本分别保存；发布不可覆盖，草稿采用修订检查。发布清单叠加只读FinancialEngine并隔离缓存，不修改源表。comparison.py、variance.py、forecast.py、scenario.py适配金额预算及公司费用合计粒度，金额预算不编造PVM驱动。

**对账与月份确认**：src/etl/controls.py在标准化及分类关联前独立保存读取控制数；src/finance/reconciliation.py核对来源、标准明细与分析结果，再与人员录入的独立参考比较。完整月份、必要来源、历史成本、内部勾稽和五项参考均通过才可确认。SQLite保存明细、金额、确认人、依据和修订；刷新检测同月新增/删除/修改，预算更新及其他月份变化不误报。解除需填写人及原因并保留旧快照。确认是本程序管理记录，不冻结数据库，不代替审计。

**历史差异与行动**：src/analysis/historical.py复用Fraction精确分解环比/同比实际，基期不会冒充预算，单列未成交商品、退款、成本转回及公司费用。src/finance/issues.py实施金额与比例双阈值，毛利率采用百分点及影响金额，缺基期不强算比例。人工原因、核实证据、负责人、行动、截止日、解决/忽略理由及复盘单列；扫描只更新事实，保留人工状态，不同扫描范围互不清除。事务及过期修订检查避免静默覆盖，操作记录集中追加。

**页面与导出**：src/dashboard/finance_ui.py新增“预算工作台”“对账与跟进”，月度趋势增加历史差异桥。新两个页面把销售筛选收进展开区，明确不作用于预算编制和公司对账。预算预览使用中文名称，上传入口和解析均限20MB，未知显示破折号，金额至分，原精度在版本及JSON中保留；差异桥表单列显示舍入尾差。Excel仍10张表，历史桥与对账/确认/人工跟进进入既有“驱动因素”“口径与追溯”，每个事项标明原范围；Markdown和JSON一致，改变记录后旧月报需重新生成。异常可导出CSV及JSON。

**验证结果**：Python3.14完整228项回归通过（237.143秒），原17组文件验收通过（19.947秒），完整模拟月报仍为R10_2d54d27c9ecd3bef3cea585c。新增23项底层＋4项实际页面用例通过；浏览器检查后补充中文预览/上传大小/事项范围/费用编码校验，27项再验通过（14.750秒），最终空表与金额显示优化后4项页面用例通过（28.733秒）。Python3.13复验发现同秒确认历史可能按随机编号倒序，已改为月份＋修订号排序，并用固定同秒时间重现验证；最终27项通过（41.689秒），固定同秒用例单独通过（0.163秒）。Python3.14最终底层23项再验通过（9.260秒），原月报及Excel18项专项通过（67.762秒）。日志统一在outputs/finance_workflow，文件分别为full-regression.log、legacy-acceptance.log、final-workflow-tests.log、final-ui-tests.log、python313-final.log、python313-same-second.log、final-model-tests.log、report-regression-final.log。

**实机核对**：浏览器检查三种配色、预算模拟文件上传校验、公司对账五项来源勾稽、无独立参考时禁用确认、异常工作区、历史实际差异桥、加载遮罩及输入颜色/原生光标。检查1280/740/390像素窗口，两新页面没有页面级横向溢出，窄窗口控件自动排列。预算模板四张工作表已渲染并目视核对，导入往返、日期/金额类型及无缓存公式拒绝在测试中验证；没有宣称完成实体Excel应用或实体Mac测试。新截图docs/assets/finance-workbench.png，测量记录outputs/finance_workflow/browser-layout.json，模板预览仅留outputs/finance_workflow。本次浏览器只上传模拟文件校验，没有保存到用户默认财务工作区。

**结构与维护**：本机所有新财务记录集中在outputs/runtime/finance_workspace.sqlite3，不进入公开包；源配置、分类布局及显示偏好保留原路径。新增docs/reference/finance_workflow.md为唯一新操作指南，README、USER_GUIDE、DEVELOPMENT、PATHS、文档首页、CHANGELOG和VERSION同步更新，不再向根目录增加学习/启动文件。后续修改继续追加本日志。

**发布与边界**：结构检查通过，216个公开文件、152个本地Markdown链接有效；生成dist/FinanceBP-v0.5.0.zip，另含逐文件校验清单。独立解压后仅使用包内源码和数据，完成模板往返、发布预算、来源/参考对账、月份确认、缺历史保持不可用和10表月报；模拟预算利润1150元、原样本实际净收入3240元均核对通过。记录在outputs/finance_workflow/release-smoke.json、browser-layout.json和outputs/validation的结构/发布清单。未在用户默认财务工作区写入验收记录；公开ZIP排除SQLite及其他本机数据，Mac入口执行位保留。仍未做实体Mac、另一台实体电脑、真实企业或多人审批授权验收，本次未重跑MySQL专项，未上传GitHub。

## 2026-10-16 · 0.5.1统一应用筛选与局部更新

**目标与操作约定**：按用户确认，月份、预算版本、单位、分类及对象先选择，点击“应用筛选”统一生效；分析分组移至维度分析页顶部，独立于范围筛选、一起应用。切页放弃未应用内容，取消恢复已应用条件，相同有效条件禁用应用。预算编制与公司对账仍按原独立范围操作。

**实现路径**：src/dashboard/filter_state.py规范化请求、验证唯一分类/有效对象/月份/版本，dimension_ui.py维护待选和已应用副本，以st.fragment将控件交互限制在局部。更换分类、移除额外位置先清空待选对象，应用前原范围不变。候选值按数据快照缓存；编辑不重新读取来源。方案选择只填入待选区，应用后才记忆，保存/更新须先应用，原v1方案文件保持兼容；命名方案不被手动调整覆盖。navigation.py切页恢复已应用条件。来源刷新失效时保留原请求供核对，暂停结果/下载，修复后的控件必须明确重新应用。

**计算、输出与加载**：app.py图表、指标、范围、月报及导出只使用已应用条件；财务公式、预算适用范围及预测方法未改。result_cache.py按快照与计算条件缓存趋势、联合分组、预测情景及历史桥，单位、分类位置及主题不进入计算身份；finance_ui.py复用历史桥结果。待选变化不使旧月报失效，应用实际范围/月/预算/分组变化后仍提示重新生成。移除任何脚本运行都显示遮罩的规则，只有有效应用、导航和来源读取明确激活，app.py的finally明确写回关闭标记，正常结束与失败均清除。

**实际验证**：Windows Python3.14最终238项完整回归通过（228.942秒），含原228项及tests/test_filter_apply.py新增10项；三色循环扩至九页。Python3.13新增10项通过（25.834秒）。原scripts/stage11.py的17组文件验收通过（21.882秒），完整模拟报告身份仍为R10_2d54d27c9ecd3bef3cea585c，10张Excel表及财务基准不变。失败分支用受控计算异常核对遮罩关闭和恢复，测试还验证缓存复用、联合分组、未应用布局不写记忆、旧月报保留及刷新失效不扩大范围。调试中修正了测试把CSS选择器当成活动遮罩、以及恢复金额断言的基准值；最终套件无失败。

**浏览器核对**：实际打开/搜索/取消列表，选择待选对象及单位时无全屏遮罩，原趋势图modebar身份保持一致，金额和范围保持已应用条件；应用后统一更新。切页恢复原单位与对象。核对九个页面、三色主题，1280桌面及740/390宽度，窄窗口控件自动排列、没有页面横向溢出或控件重叠；分析分组位于顶部，应用/取消按钮明确，已恢复原配色、公司范围和默认窗口。实机截图docs/assets/filter-apply.png，图中P001为待选，下面公司指标尚未改变。未向用户默认财务工作区写验收记录。

**证据、文档与交付**：本次新证据集中outputs/filter_apply，完整回归为full-regression-final.log，兼容回归为python313-filter-apply.log，文件验收为legacy-acceptance.log及legacy子目录，浏览器为browser-checks.json。早期诊断日志另留outputs/finance_workflow的filter前缀文件，均不进入公开包。更新README、USER_GUIDE、动态分类说明、维护指南、路径索引、CHANGELOG和VERSION；根目录未增加启动或阶段文件，阶段原文仍在docs/history，后续继续追加此日志。发布为dist/FinanceBP-v0.5.1.zip，保留START.cmd与START.command、公开源码、样例和逐文件校验清单，排除本机记忆、财务工作区、日志与环境。

**最终包验收**：结构检查220个公开文件、153条本地Markdown链接通过。将0.5.1包完整解压到outputs/filter_apply/release-smoke，使用包内模块与模拟数据启动真实AppTest，核对原公司净收入3240元、待选不改变金额、应用商品后2940元、切页恢复单位、多维销售员1净收入4300元；ZIP路径/CRC/校验清单、Mac入口执行位及私有文件排除均通过。结果为release-smoke.json与release-smoke.log；验收期间只使用隔离记忆和工作区，没有向用户默认财务工作区写入记录。

**边界**：本次使用文件和隔离工作区验证，没有重跑MySQL专项、没有改写用户数据库；实体Mac、另一台实体电脑及真实企业仍未实测，不做桌面封装，不上传GitHub。

## 2026-10-19 · 1.0.0 Windows 独立应用候选构建

**目标与范围**：按确认方案制作 Windows 11 x64 独立窗口，保留九页、三种配色、统一应用筛选和全部财务口径。Mac 源码入口保留，不制作 Mac 应用，不上传 GitHub，不采购签名证书。

**实现路径**：src/desktop/ 增加 AppPaths、窗口与自有后台、单实例聚焦、真实启动阶段、文件队列和个人数据维护；scripts/windows_app.py 是冻结程序与后台的统一入口。以 Python 3.13.16、pywebview 6.2.1、PyInstaller 6.22.3 和 Inno Setup 6.7.3 构建，requirements-desktop-lock.txt 锁定实际依赖，安装包附微软签名的 WebView2 离线组件。桌面运行不执行 pip。安装文件在 dist，构建工具、环境和证据集中 outputs/desktop_build。

**个人数据与文件**：预算/对账SQLite、分类方案、显示偏好与预测记录改为 AppPaths 统一定位；桌面默认 %LOCALAPPDATA%/FinanceBP，源码仍使用 outputs。原生菜单提供备份、校验恢复、旧项目合并导入和数据/日志目录；导入前自动备份，旧文件保留，重复导入以现有记录为准，辅助文件路径重定位但保持企业/配置身份。所有业务下载接入 export_artifact，上传改用系统选择窗口；浏览器运行保留原接口。图表和表格工具栏也保留原生另存为。

**实际修复**：源码预览发现 Windows Python 启动器多一层进程导致就绪判断不符，增加自有进程与会话身份检查；冻结版发现 Streamlit 默认进入开发模式，显式关闭后正常启动。新增恢复时的SQLite句柄释放、重复ZIP成员拒绝、文件后缀保留及启动失败重试；原下载调用的位置/命名参数分别保持兼容。调试失败记录保留，不以早期日志替代最终通过记录。

**已完成验证**：实施前238项回归与17组文件验收通过；适配后257项完整回归通过（295.247秒），桌面边界用例扩至21项并全部通过（2.247秒），最终259项全套结果另见验收清单。17组财务/月报再验收通过（50.819秒），报告身份仍为 R10_2d54d27c9ecd3bef3cea585c。打包程序在仅保留系统PATH时通过13项离线自检；净收入3240元、P001为2940元、多维销售员为4300元及10张月报表与网页基准一致。安装后程序连接隔离33326端口MySQL，14项自检通过，数据库净收入3240.00元；不连接或改写用户3306数据库。安装资源的九页三色、原生预算队列、中文文件读取和方案验证通过（89.964秒）；该项使用锁定构建环境AppTest，明确不等同原生窗口逐页手工验收。

**原生窗口与边界**：实机进入总览、月度趋势、维度分析、预算工作台并打开系统另存为窗口；记录源码完整模拟首屏18.750秒、安装版10.927秒，属本机单次观测，不能作为所有电脑的性能承诺。原生窗口完整九页及所有文件类型还需最终逐项核对；当前机器无Windows Sandbox，独立无Python/Excel的干净系统及实体125%/150%缩放尚未验收。安装、覆盖和卸载的最终记录、交付哈希均以 [Windows验收清单](WINDOWS_ACCEPTANCE.md) 和 outputs/desktop_build 最终证据为准。

**交付标识**：安装器及主程序未代码签名。必要条件未全部通过前标注候选版，不宣称Windows正式版。README、USER_GUIDE、DEVELOPMENT、PATHS、CHANGELOG与Windows应用指南同步更新，后续继续追加本日志。

**最终核验追加**：最终259项全套通过（1116.728秒，与构建/安装并行）；最终冻结包13项离线自检、隔离MySQL14项、安装覆盖卸载重装12项、自有后台生命周期10项全部通过。安装器311646321字节，SHA256 a44793c83a8e7b5d5919837c1b119525f5fd2e6427f833d534bbf0348b72497f。原生窗口工具连续检测到用户操作，重新定位重试后仍失败，停止余下原生抽查，保留待验收项。旧直接回归会写入默认偏好，增加scripts/run_tests.py隔离入口并完成10项专项，恢复原松石青及1148字节方案文件；默认财务SQLite未创建。保留隔离预览数据备份，清理测试安装记录，使用户首次安装使用默认位置和桌面图标设置。独立干净系统、完整原生交互、125%/150%缩放及后续跨版本升级未验收，仍为候选版，未上传GitHub。

**文件整理**：dist根目录保留1.0.0安装器、源码ZIP及各自校验文件；旧的dist/FinanceBP-v0.*.zip移入dist/archive原名保留，不删除历史版本。dist/windows为构建用目录模式文件，日常使用选择setup.exe；构建、个人备份和核验证据仍在outputs/desktop_build，不进入源码ZIP。244个公开文件和164条本地文档链接检查通过。

## 后续记录模板

```text
日期 / 版本 / 任务：
目标与背景：
完成的改动：
涉及路径（新增、修改、移动的旧→新路径）：
口径/兼容性决定：
验证命令、实际结果、证据路径：
限制或尚未完成：
下一步：
```

小改动也保留一条可追溯记录；不要把项目日志写成尚未执行的任务清单。


## 2026-10-19：Windows 1.0体验版公开发布整理

目标：在nixizoul0017/FinanceBP公开完整项目，首屏引导下载EXE、安装和桌面启动，并将“星辰优选”四套模拟样本一同交付。

改动：README改为桌面下载入口；docs/SOURCE_RUN.md承接原源码环境与启动说明；docs/DEMO_DATA.md说明完整、多维、异名和小样本的目录、配置、期间、行数、生成种子、预算粒度及基准；同步Windows指南、文档索引、维护指南及CHANGELOG。模拟数据保留现有内容，财务代码与已验收安装包不变。

版本：应用内部1.0.0；发布标签v1.0.0-rc.1，预发布且未签名。源码与安装包分开交付，后者不进入Git源码历史。仍须独立干净系统、完整原生窗口和125%/150%缩放验收后才能发布正式版。历史记录中的“未上传GitHub”为当时状态。

公开源按scripts/package_project.py白名单整理，不包含密码、本机接入配置、个人预算与方案、outputs、dist、虚拟环境或调试记录。安装包SHA256保持a44793c83a8e7b5d5919837c1b119525f5fd2e6427f833d534bbf0348b72497f。后续在本条目追加实际验证、提交身份和远端发布结果；准备阶段不声称上传成功。

本轮实际复核：60项样本与公开文件检查通过（四套配置全部可加载、manifest逐表行数及SHA256一致、异名事实等价、3240/4300及完整样本267927.12元基准、退款历史部门、缺失归属与预算粒度边界）；17组财务/月报验收重新通过，52.484秒，月报身份仍为R10_2d54d27c9ecd3bef3cea585c。公开文件246个，188条本地Markdown链接检查通过。证据保留在outputs/github_publish，不进入公开源码。远端创建、推送和附件下载校验尚未完成，待可用GitHub授权通路恢复后记录。
