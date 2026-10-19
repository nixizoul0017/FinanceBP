# Windows 1.0 验收记录

本文件记录实际完成的检查。未执行项目保持“待验收”，不会以源码测试代替安装后的验证。

2026-10-19 实施前：238 项功能回归、17 组财务与月报验收通过；153 条文档链接检查通过。

| 项目 | 当前状态 |
|---|---|
| Python 3.13 独立构建环境 | 已准备 |
| 源码独立窗口启动、首屏 | 已通过；本机记录 18.750 秒 |
| 新增桌面数据与导出回归 | 21项通过；最终全套259项通过，1116.728秒（与构建、安装并行） |
| 冻结程序离线财务验收 | 最终程序13项通过；仅保留系统PATH，Python 3.13.16，10张Excel表 |
| 安装资源九页、三种配色与文件接口 | AppTest通过，89.964秒；包含中文路径、预算队列和方案 |
| 原生窗口逐页与文件窗口 | 已实际检查总览、趋势、维度、预算页及系统另存为；其余待核对 |
| 安装、同版本覆盖、卸载与重装 | 最终包12项通过；三个隔离个人数据文件的SHA256保持一致 |
| 跨版本升级 | 待后续真实版本验收；本次验证同版本覆盖，稳定AppId及数据目录保持不变 |
| 自有后台生命周期 | 最终程序10项通过：停止、重启、端口冲突、子进程崩溃、主进程退出后清理 |
| 打包后隔离 MySQL | 最终安装版33326独立实例，14项通过，净收入3240.00元；实例已清理 |
| 无 Python、无 Excel 的独立干净 Windows | 待验收；当前机器没有 Windows Sandbox |
| 实体 125%、150% 显示缩放 | 待验收 |

达到计划全部必要条件后才标记 Windows 正式版。候选安装包不等于全部验收已完成。

17组财务/月报验收通过（50.819秒），报告身份 R10_2d54d27c9ecd3bef3cea585c。源码首屏18.750秒、安装版10.927秒为本机单次记录；最终安装版与MySQL/进程测试并行时首屏53.574秒，说明负载会影响耗时，不作通用速度承诺。

原生窗口控制工具连续返回“user input was detected in this window”，刷新、重新定位与重试后仍失败，停止该部分自动操作。只将实际完成的四页及另存为窗口记为已检查，未把AppTest等同完整原生交互验收。系统文件保存成功/取消/权限失败已做接口回归，完整Windows文件窗口逐项操作仍待验收。

旧直接测试会写入默认显示与布局文件，现新增scripts/run_tests.py隔离入口；其配色与九页专项10项通过（113.544秒）。恢复预检时松石青及原有1148字节方案文件，测试产生的小样本布局移出默认文件，备份保留在outputs/desktop_build/defaults_preservation；默认财务SQLite未创建。

安装器及主程序未代码签名。最终安装包311646321字节，SHA256：`a44793c83a8e7b5d5919837c1b119525f5fd2e6427f833d534bbf0348b72497f`。当前临时验收安装会清理，个人数据与预览备份保留；日常使用请运行安装包，创建桌面图标。

证据集中于 outputs/desktop_build：desktop-tests-final.log、full-regression-candidate.log、legacy.log、final-frozen-selftest.json、installed-mysql-selftest.json、packaged-mysql-final.log、installed-resources.json、installation-lifecycle.json、frozen-processes.json、build-manifest.json及defaults_preservation。调试日志另留，不进入公开包。
