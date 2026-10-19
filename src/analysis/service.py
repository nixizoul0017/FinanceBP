from .comparison import company_budget_comparison, sales_budget_comparison, trend_comparison, year_to_date
from .metrics import Filters, month_date


def analysis_pack(engine, month, filters=Filters(), version="B2026_V1"):
    month = month_date(month)
    company_budget = company_budget_comparison(engine, month, version=version)
    return {
        "metadata": {"entity_id": engine.entity_id, "rule_version": engine.metadata["rule_version"], "source_fingerprint": engine.metadata.get("source_fingerprint"), "coverage": engine.metadata["coverage"], "semantics": engine.metadata.get("semantics"), "month": month, "filters": filters.as_dict(), "budget_version": version},
        "selected_scope": engine.summary(month, filters=filters),
        "company_scope": engine.summary(month),
        "selected_trends": trend_comparison(engine, month, filters),
        "selected_ytd": year_to_date(engine, month, filters),
        "selected_budget": company_budget["sales"] if filters.is_company else sales_budget_comparison(engine, month, version=version, filters=filters),
        "company_budget": company_budget,
        "dimensions": {name: engine.dimensions(month, by=name, filters=filters).to_dict("records") for name in engine.dimension_ids},
        "company_expense_details": engine.expense_details(month).to_dict("records"),
    }
