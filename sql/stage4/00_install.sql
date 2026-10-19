-- 手动学习入口：在项目根目录登录MySQL后SOURCE本文件。
SOURCE sql/stage4/00_parameters.sql;
SOURCE sql/stage4/01_analysis_views.sql;
SOURCE sql/stage4/02_detail_and_monthly.sql;
SOURCE sql/stage4/03_dimension_analysis.sql;
SOURCE sql/stage4/04_trends.sql;
SOURCE sql/stage4/05_budget_analysis.sql;
SOURCE sql/stage4/06_verify_baseline.sql;
SELECT 'STAGE4_COMPLETED' AS result,VERSION() AS server_version,DATABASE() AS project_database;
