"""Strategy layer — Lab Assignment #12 (Behavioral pattern).

Different deployments want different rules for "when is a host unhealthy?".
Dev may be happy with 90 % CPU, production SRE may want to alert at 70 %.
We swap behaviour without touching callers by picking a different
``MetricEvaluationStrategy`` implementation.
"""
from .metrics_strategy import (
    MetricEvaluationStrategy,
    DefaultThresholdStrategy,
    StrictAlertStrategy,
    MetricStatus,
    MetricEvaluation,
    get_strategy,
)

__all__ = [
    "MetricEvaluationStrategy",
    "DefaultThresholdStrategy",
    "StrictAlertStrategy",
    "MetricStatus",
    "MetricEvaluation",
    "get_strategy",
]
