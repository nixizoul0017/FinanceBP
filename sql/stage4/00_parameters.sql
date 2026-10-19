-- 每次新登录后先执行本文件；参数只对当前连接有效。
USE finance_bp_stage3;
-- 与阶段3表的文字比较规则保持一致，尤其用于预算版本参数比较。
SET NAMES utf8mb4 COLLATE utf8mb4_0900_as_cs;
SET @analysis_month=DATE('2026-09-01');
SET @actual_start_month=DATE('2026-09-01');
SET @actual_end_month=DATE('2026-09-01');
SET @budget_version='B2026_V1';
-- 以上起止月声明“连续且完整载入”的实际数据范围。
-- 日期表中有某个月，不等于该月业务数据已载入。10月边界样本不在完整范围。

