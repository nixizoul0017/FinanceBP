"""统一财务计算：只接收标准事实，不依赖企业原始表名。"""

from .metrics import FinancialEngine, Filters

__all__ = ["FinancialEngine", "Filters"]
