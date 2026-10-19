# Windows 独立应用

**[下载 Windows 1.0 体验版 EXE](https://github.com/nixizoul0017/FinanceBP/releases/download/v1.0.0-rc.1/FinanceBP-1.0.0-windows-x64-setup.exe)** · [版本说明](https://github.com/nixizoul0017/FinanceBP/releases/tag/v1.0.0-rc.1) · [模拟数据说明](DEMO_DATA.md)

版本：1.0.0。当前为待完成安装后与独立干净系统验收的候选构建，不提前标记正式版。

运行要求：Windows 11 x64；无需 Python、Excel 或开发工具。安装包内置 Python 3.13 和应用依赖，缺少 WebView2 时使用随包的微软离线组件。演示分析无需联网，远程数据库需要相应网络权限。

打开 `FinanceBP-1.0.0-windows-x64-setup.exe` 安装，完成后双击 FinanceBP 桌面图标。独立窗口会自动启动本机分析进程，不需要再打开 START 或输入网址。关闭窗口会结束本应用的后台分析。

“文件”菜单提供个人数据备份、恢复和导入旧项目数据；“帮助”菜单提供重新加载、日志与关于。预算、方案、预测版本和偏好位于 `%LOCALAPPDATA%\FinanceBP`。升级或卸载默认保留该目录。导入旧项目时选择包含 `outputs` 的项目根目录，先备份再合并，同名记录优先保留当前记录，旧文件不删除。

导出按钮打开系统“另存为”，完成、取消或失败都有提示。预算模板、分类方案、数据源配置使用系统文件选择窗口。自定义文件源请使用绝对路径；企业原始文件不会复制到安装包或个人备份。

本次程序未购买或配置代码签名证书，安装器及应用均为未签名的个人展示构建。不要为运行它关闭系统安全功能。第三方许可证随应用保存在 `_internal/resources/third_party`。

构建与实际验收记录见 [Windows 验收清单](WINDOWS_ACCEPTANCE.md)。源码网页运行、Mac 源码入口继续保留，见 [使用说明](USER_GUIDE.md)。
