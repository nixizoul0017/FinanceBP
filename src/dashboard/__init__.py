"""看板的展示适配层；财务口径由analysis模块统一提供。"""

from .view_model import (
    budget_rows,
    chart_frame,
    csv_bytes,
    detail_tables,
    money_text,
    monthly_trend,
    percent_text,
    safe_export_name,
)

__all__ = [
    "budget_rows", "chart_frame", "csv_bytes", "detail_tables", "money_text",
    "monthly_trend", "percent_text", "safe_export_name",
]
