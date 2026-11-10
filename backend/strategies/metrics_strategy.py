"""Metric evaluation — Behavioral / Strategy pattern.

The hub needs to label every host snapshot with a status like
"ok / warning / critical" for the dashboard and for alerting. But what
counts as a "warning CPU" differs per deployment:

  • DefaultThresholdStrategy — lenient, dev-friendly (70 % warn / 90 % crit)
  • StrictAlertStrategy      — tight, SRE-grade (60 % warn / 80 % crit)

Both implement the same ``MetricEvaluationStrategy`` interface, so the
telemetry pipeline and the host-list endpoint can call ``.evaluate(...)``
without knowing which policy is active. The active strategy is chosen
from the ``METRIC_STRATEGY`` environment variable (default = ``default``).
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MetricStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class MetricEvaluation:
    """Result of evaluating one metric snapshot.

    Attributes are intentionally JSON-friendly so the endpoint layer
    can embed the evaluation in an API response without any adapter.
    """

    status: MetricStatus
    cpu_status: MetricStatus
    ram_status: MetricStatus
    disk_status: MetricStatus
    reasons: list[str]  # human-readable, e.g. "CPU 92% ≥ 90% crit"

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "cpu_status": self.cpu_status.value,
            "ram_status": self.ram_status.value,
            "disk_status": self.disk_status.value,
            "reasons": self.reasons,
        }


# ─── Interface ─────────────────────────────────────────────────────────
class MetricEvaluationStrategy(ABC):
    """Strategy interface. Concrete strategies plug different thresholds."""

    name: str = "abstract"

    @abstractmethod
    def evaluate(
        self,
        *,
        cpu_percent: Optional[float],
        ram_percent: Optional[float],
        disk_percent: Optional[float],
    ) -> MetricEvaluation:
        """Return a status + per-resource breakdown + reasons list."""

    # ─── Shared helper: pick the worst of several statuses ─────────────
    @staticmethod
    def _worst(*statuses: MetricStatus) -> MetricStatus:
        order = {MetricStatus.OK: 0, MetricStatus.WARNING: 1, MetricStatus.CRITICAL: 2}
        return max(statuses, key=lambda s: order[s])


# ─── Concrete strategy #1: lenient / default ───────────────────────────
class DefaultThresholdStrategy(MetricEvaluationStrategy):
    """Lenient dev-friendly thresholds."""

    name = "default"
    CPU_WARN, CPU_CRIT = 70.0, 90.0
    RAM_WARN, RAM_CRIT = 75.0, 90.0
    DISK_WARN, DISK_CRIT = 80.0, 95.0

    def _classify(self, value: Optional[float], warn: float, crit: float) -> MetricStatus:
        if value is None:
            return MetricStatus.OK
        if value >= crit:
            return MetricStatus.CRITICAL
        if value >= warn:
            return MetricStatus.WARNING
        return MetricStatus.OK

    def evaluate(
        self,
        *,
        cpu_percent: Optional[float],
        ram_percent: Optional[float],
        disk_percent: Optional[float],
    ) -> MetricEvaluation:
        cpu_s = self._classify(cpu_percent, self.CPU_WARN, self.CPU_CRIT)
        ram_s = self._classify(ram_percent, self.RAM_WARN, self.RAM_CRIT)
        disk_s = self._classify(disk_percent, self.DISK_WARN, self.DISK_CRIT)
        reasons: list[str] = []
        if cpu_s != MetricStatus.OK and cpu_percent is not None:
            reasons.append(
                f"CPU {cpu_percent:.0f}% ≥ "
                f"{self.CPU_CRIT if cpu_s == MetricStatus.CRITICAL else self.CPU_WARN}%"
            )
        if ram_s != MetricStatus.OK and ram_percent is not None:
            reasons.append(
                f"RAM {ram_percent:.0f}% ≥ "
                f"{self.RAM_CRIT if ram_s == MetricStatus.CRITICAL else self.RAM_WARN}%"
            )
        if disk_s != MetricStatus.OK and disk_percent is not None:
            reasons.append(
                f"Disk {disk_percent:.0f}% ≥ "
                f"{self.DISK_CRIT if disk_s == MetricStatus.CRITICAL else self.DISK_WARN}%"
            )
        return MetricEvaluation(
            status=self._worst(cpu_s, ram_s, disk_s),
            cpu_status=cpu_s,
            ram_status=ram_s,
            disk_status=disk_s,
            reasons=reasons,
        )


# ─── Concrete strategy #2: strict / production SRE ─────────────────────
class StrictAlertStrategy(DefaultThresholdStrategy):
    """Tighter thresholds for prod environments where early warning matters."""

    name = "strict"
    CPU_WARN, CPU_CRIT = 60.0, 80.0
    RAM_WARN, RAM_CRIT = 65.0, 85.0
    DISK_WARN, DISK_CRIT = 70.0, 90.0


# ─── Registry / selector ───────────────────────────────────────────────
_STRATEGIES: dict[str, type[MetricEvaluationStrategy]] = {
    DefaultThresholdStrategy.name: DefaultThresholdStrategy,
    StrictAlertStrategy.name: StrictAlertStrategy,
}


def get_strategy(name: Optional[str] = None) -> MetricEvaluationStrategy:
    """Resolve a strategy instance by name.

    Falls back to the ``METRIC_STRATEGY`` env var, and ultimately to
    ``DefaultThresholdStrategy`` when nothing is specified. Unknown names
    also fall back to the default — never raise, since this runs on the
    telemetry hot-path.
    """
    key = (name or os.getenv("METRIC_STRATEGY") or DefaultThresholdStrategy.name).strip().lower()
    cls = _STRATEGIES.get(key, DefaultThresholdStrategy)
    return cls()
