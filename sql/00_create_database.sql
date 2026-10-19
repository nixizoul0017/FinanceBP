-- 阶段3：新建项目专用练习库。若同名库已存在，停止，不覆盖旧数据。
-- 首次运行入口：00_run_stage3.sql。需要 CREATE 权限。
CREATE DATABASE finance_bp_stage3
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs;
USE finance_bp_stage3;
SET NAMES utf8mb4;
SET SESSION time_zone = '+08:00';
SET SESSION sql_mode = 'STRICT_TRANS_TABLES,ONLY_FULL_GROUP_BY,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

