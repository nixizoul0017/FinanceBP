# 开发与维护指南

## Windows 独立应用构建

使用 Windows x64、Python 3.13 和隔离构建环境，按 `requirements-desktop-lock.txt` 安装锁定依赖；不要用用户的财务运行环境构建。构建入口 `scripts/build_windows_app.py` 调用 PyInstaller 与 Inno Setup，正式运行端不会安装依赖。

构建工具放在 outputs/desktop_build/tools：Inno Setup 6.7.3 编译器目录 InnoSetup、微软签名的 MicrosoftEdgeWebView2RuntimeInstallerX64.exe。分别从 [Inno Setup 官网](https://jrsoftware.org/isdl.php) 与 [微软 WebView2 分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) 获取；发布前检查 Authenticode 与构建清单中的 SHA256。依赖许可证随安装资源保存。

先用 `python scripts/run_tests.py` 运行完整回归，再执行 scripts/stage11.py，随后构建并在隔离个人目录中执行冻结程序的 `--self-test`。回归入口把偏好、方案和工作区放进临时目录，避免测试改掉日常布局。该诊断会生成模拟月报、校验3240/2940/4300元基准、预算往返及迁移恢复，不替代九页交互或独立干净系统验收。最终安装包、校验文件放 dist，构建证据放 outputs/desktop_build。Windows 验收状态见 [清单](WINDOWS_ACCEPTANCE.md)。

## 每次更新

1. 在PROJECT_LOG.md追加任务，写明目标、模块和预计改变的路径。
2. 修改代码/配置/文档。迁移路径时同步更新引用、文档链接、打包清单和PATHS.md。
3. 按改动测试；财务或输入输出路径变化时运行完整回归及文件验收。
4. 在同一日志条目记录实际命令、结果、产物路径、限制和下一步。
5. 发布时更新VERSION、CHANGELOG.md，通过维护菜单4或manage.py的Package操作生成新ZIP。

## 文件约定

业务代码在src，管理脚本在scripts，测试及固定基准在tests/fixtures。当前指南在docs，财务口径在reference，案例在examples，阶段档案在history/stages，截图在assets。根目录提供Windows的START.cmd、Mac的START.command、README、CHANGELOG和VERSION。Windows先调用launch_windows.ps1，两系统最终调用desktop_launcher.py自动启动；manage.py/manage.ps1为可选维护入口。

要求64位Python3.13/3.14，图形入口使用标准Tk组件。入口不自动安装系统Python或修改系统安全设置；自动创建本机.venv、补全pip和锁定依赖。启动日志与同项目服务状态记录位于outputs/runtime；复用服务前核对进程命令及健康响应，不能只凭端口开放判断。

Windows入口必须通过系统powershell.exe（5.1）实际执行验证，不能只在PowerShell7里调用.ps1代替双击START.cmd。5.1向原生程序传参时可能丢掉内嵌双引号；版本/位数探测命令避免内嵌字符串，独立回归在tests/test_windows_bootstrap.py。`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/launch_windows.ps1 -CheckOnly`可无弹窗检查识别结果。

运行不能依赖旧outputs。固定核对输入只从tests/fixtures读取，不在普通测试中覆盖；变更财务口径须先独立核对预期，再记录基准变更原因。

日常结果在outputs/reports、outputs/forecasts、outputs/validation。旧阶段脚本可能仍生成outputs/stageN，为兼容保留的本地诊断。用户私有数据与*.local.json不进入发布包。

## 验证

分组导航在src/dashboard/navigation.py，使用原生按钮、稳定的page会话状态和独立nav_键。新增页面时同步更新GROUPS与集成导航检查。0.5.1的筛选区使用st.fragment局部更新，filter_state.py规范化/校验请求，dimension_ui.py分别维护_filter_draft与_filter_applied；图表及导出只读后者。result_cache.py按快照与计算条件缓存趋势、分组、预测情景及历史桥，排除单位、位置顺序和主题。cockpit.css的遮罩由明确业务事件设置data-active，禁止重新绑定任何脚本运行状态；app.py用finally清除遮罩；升级Streamlit后必须实际验证点击即时出现、完成/失败自动消失、侧栏收起时位置正确及减少动态效果设置。不得为展示加载而增加固定等待。

外观令牌与偏好读写在src/dashboard/theme.py，原生控件样式在cockpit.css，图表直接使用同一Palette。只接受三种白名单键，偏好失败不阻塞分析；测试应隔离PREFERENCE_PATH，不能覆盖用户显示偏好。不要把主题加入财务缓存键或报告内容身份，也不要在颜色切换回调中清空数据、筛选和报告。

在项目目录的PowerShell执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage.ps1 -Action Check
.\.venv\Scripts\python.exe scripts/run_tests.py
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\manage.ps1 -Action Verify
.\.venv\Scripts\python.exe scripts/check_project.py
```

Mac在项目目录终端执行：

```bash
bash START.command --action Check
.venv/bin/python scripts/run_tests.py
bash START.command --action Verify
```

分别验证入口环境、核心/页面回归、文件至报告流程、文档链接与打包排除规则。START.command必须使用LF换行、UTF-8无BOM；.gitattributes保留此规则。ZIP将其标为可执行，Git源码提交时还应记录执行位，例如 `git update-index --chmod=+x START.command`。GitHub自动生成的源码ZIP解压后可能仍需chmod。临时MySQL检查为scripts/validate_stage11_mysql.ps1，通过-MySqlDirectory指定安装位置，仅用于Windows专用临时实例。

test_dashboard_theme.py覆盖三色×九页、切换后图表数值/筛选/缓存不变、月报快照与假设保留、刷新恢复和偏好文件异常。界面样式调整还需真实浏览器检查控件文字对比度和金额可读性。

新解压目录启动验证时核对默认金额与月报，关闭测试服务后保留用户看板。本机独立目录不等于另一台实体电脑验证。

## 打包与GitHub发布

维护菜单4按VERSION生成ZIP，写入release_manifest.json并逐文件校验哈希。Windows可用`.\.venv\Scripts\python.exe scripts/manage.py --action Package`；Mac用`bash START.command --action Package`。ZIP在dist，含压缩包哈希的本地记录在outputs/validation/release_manifest.json。发布清单必须包含两个入口、Windows引导脚本、图形启动代码和维护脚本，区分Windows/Python版本实测与实体Mac待验收。

包内保留源码、模拟数据、固定基准、历史档案和当前文档；排除.venv、outputs、dist、日志、缓存、目录链接、secrets.toml和本地配置。configs仅允许明确列出的模拟/示例配置。新增公开配置或必要目录时更新打包允许清单并记录用途。

公开仓库为 `nixizoul0017/FinanceBP`，默认分支main。只按scripts/package_project.py的release_files白名单提交源码，不能直接把整个工作目录加入Git。仓库根README优先展示EXE，源码环境与Windows/Mac浏览器入口见[源码运行说明](SOURCE_RUN.md)，数据用途与复现见[模拟数据说明](DEMO_DATA.md)。

Windows体验版标签为 `v1.0.0-rc.1`，应用内部版本保持1.0.0，Release标记为预发布。EXE超过普通Git文件大小限制，应连同源码ZIP及两份SHA256文件放入Release附件，不进入Git历史；体验版下载按钮使用指定标签地址，不能依赖latest正式版地址。安装包保持已验收内容，文档变动后重新生成源码ZIP及其校验值。

`.gitignore`排除本机环境、输出和私有文件，提交前仍须扫描公开文件。不要自动新增开源许可证；第三方组件许可证继续随应用保留。实际推送与附件状态记录在[项目日志](PROJECT_LOG.md)，未验证远端下载前不标记发布完成。

## 0.4.0动态分类维护

接入/目录在src/etl/dimensions.py，统一筛选和联合分组在src/analysis/metrics.py，网页控件、映射确认与私有记忆分别在src/dashboard/dimension_ui.py、dimension_setup.py、dimension_store.py。导出同步修改src/reporting/service.py及tables.py；不要把销售维度加入公司费用粒度。

维度稳定id用于匹配；label可改。新增分类不能覆盖金额、日期和业务键。退款分类从原销售取，附加表必须唯一关联。预算可用字段按版本保存，预测建模粒度固定在接入配置与快照中，界面位置不改变训练粒度。

## 0.5.0财务工作区维护

`src/finance/store.py`集中维护本机SQLite事务、草稿/发布状态、确认修订、人工跟进和追加日志；数据在outputs/runtime/finance_workspace.sqlite3，公开包必须排除。`budgets.py`维护模板、导入和只读引擎叠加，不更新来源表。发布清单改变时更新分析身份；实际月份快照独立于预算和全量来源摘要，避免未来月份新增误判旧月。

`src/etl/controls.py`在标准化及维度关联前独立汇总读取控制数；`finance/reconciliation.py`同时核对标准明细和引擎金额，独立外部参考必须由人员提供。`analysis/historical.py`复用有理数PVM计算历史实际差异，对外字段与文案使用“基期”；`finance/issues.py`分别维护系统事实、覆盖不足和人工记录。`dashboard/finance_ui.py`提供新界面，报告可选workflow/historical参数保持默认CLI基准兼容。

新增tests/test_finance_workflow.py及test_finance_workflow_app.py，覆盖金额/驱动预算、公司/细分类粒度、模板往返/错误公式、发布锁定和并发、来源勾稽、确认变更/解除、历史金额恒等式、跨月退款、双阈值、范围隔离、人工保留、实际页面及月报失效。修改后运行全套test_*.py及scripts/stage11.py，源数据库不得在验收中被改写。界面仍需实际浏览器检查三色和窄窗口，实体Mac不得用Windows的Python3.13测试代替。

新增独立样例可运行scripts/generate_multidimensional_demo.py；全套回归仍使用 `python -m unittest discover -s tests -p "test_*.py"`，新增用例在tests/test_dynamic_dimensions.py及test_dynamic_dimensions_app.py。独立MySQL总验收入口scripts/validate_stage11_mysql.ps1已包含多维验证，仅使用33324临时实例。发布脚本已白名单纳入configs/multidimensional_files.json，outputs/runtime中的本机映射和方案必须排除。

当前交付包含Windows/Mac启动入口；Python3.13的本机回归不等于实体Mac验收。月报身份按实际筛选与有序分组产生，改条件后提示重新生成。

## 0.5.1交互回归

tests/test_filter_apply.py覆盖连续编辑后统一提交、同值禁用、取消/切页、方案待选与记忆、候选快照复用、单位/顺序缓存复用、联合分组、刷新失效不扩大范围、旧月报及失败后加载清除。旧页面财务断言先选择再调用apply_filters；不要把待选控件值直接用于下载身份。完整回归仍需加上scripts/stage11.py和浏览器实机检查。AppTest的.run会运行完整脚本，实际局部更新另通过浏览器验证图表保留及无全屏遮罩。
