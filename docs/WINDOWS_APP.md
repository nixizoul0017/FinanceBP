# Windows 独立应用

**[下载 Windows 1.2.2 体验版 EXE](https://github.com/nixizoul0017/FinanceBP/releases/download/v1.2.2-rc.1/FinanceBP-1.2.2-windows-x64-setup.exe)** · [版本说明](https://github.com/nixizoul0017/FinanceBP/releases/tag/v1.2.2-rc.1) · [模拟数据说明](DEMO_DATA.md)

当前版本1.2.2：首次上传订单表推荐财务字段和月份，数量可默认1，单日数据进入文件内已知交易分析；保留编号合并、支付时间识别、[全部表头分类和改名](HEADER_CATALOG.md)、[业务文件导入](FILE_IMPORT.md)及加载遮罩修复。发布标签v1.2.2-rc.1；旧1.0附件保留。继续按未签名体验版交付，不提前标记正式版。1.2.2仅完成指定文件接入核对，未重跑全套功能、冻结EXE或安装后验收。

运行要求：Windows 11 x64；无需 Python、Excel 或开发工具。安装包内置 Python 3.13 和应用依赖，缺少 WebView2 时使用随包的微软离线组件。演示分析无需联网，远程数据库需要相应网络权限。

打开 `FinanceBP-1.2.2-windows-x64-setup.exe` 安装，完成后双击 FinanceBP 桌面图标。独立窗口会自动启动本机分析进程，不需要再打开 START 或输入网址。关闭窗口会结束本应用的后台分析。

从旧版更新时，关闭应用，可先用“文件”菜单备份，再运行 `FinanceBP-1.2.2-windows-x64-setup.exe` 按向导更新，从同一个桌面图标打开；个人数据默认保留。左侧“自定义配置”上传订单文件后会推荐财务设置；核对表头、分类、日期、金额及数量默认方式后确认，无需自己编写JSON。

“文件”菜单提供个人数据备份、恢复和导入旧项目数据；“帮助”菜单提供重新加载、日志与关于。预算、方案、预测版本和偏好位于 `%LOCALAPPDATA%\FinanceBP`。升级或卸载默认保留该目录。导入旧项目时选择包含 `outputs` 的项目根目录，先备份再合并，同名记录优先保留当前记录，旧文件不删除。

导出按钮打开系统“另存为”，完成、取消或失败都有提示。预算模板、分类方案、配置及业务表使用系统文件窗口；业务表支持多选。上传业务表复制到本机个人数据目录的imports，映射保存在profiles/business_imports；高级JSON中的文件路径请使用绝对路径。业务文件不进入安装包或个人备份，换电脑时请另外保留原始文件。

本次程序未购买或配置代码签名证书，安装器及应用均为未签名的个人展示构建。不要为运行它关闭系统安全功能。第三方许可证随应用保存在 `_internal/resources/third_party`。

构建与实际验收记录见 [Windows 验收清单](WINDOWS_ACCEPTANCE.md)。源码网页运行、Mac 源码入口继续保留，见 [使用说明](USER_GUIDE.md)。
