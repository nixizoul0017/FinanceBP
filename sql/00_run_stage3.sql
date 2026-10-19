-- 手动教学入口：在项目根目录启动 mysql，执行 SOURCE sql/00_run_stage3.sql;
-- 自动验证和一键执行使用 scripts/run_stage3.ps1：合并SQL后以批量输入运行，报错停止。
-- 手动SOURCE执行时需检查每一步输出；不要在已有同名库中重跑。
SOURCE sql/00_create_database.sql;
SOURCE sql/01_create_tables.sql;
SOURCE sql/02_seed_sample.sql;
SOURCE sql/03_quality_checks.sql;
SOURCE sql/04_verify_samples.sql;
SOURCE sql/05_constraint_tests.sql;
SELECT 'STAGE3_COMPLETED' AS result, VERSION() AS server_version, DATABASE() AS project_database;

