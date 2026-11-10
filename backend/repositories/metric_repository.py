"""HostMetric + ContainerMetric persistence."""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models
import schemas


class MetricRepository:
    """Repository for the ``HostMetric`` aggregate (and its child
    ``ContainerMetric`` rows)."""

    def __init__(self, db: Session):
        self.db = db

    # ─── Lookups ───────────────────────────────────────────────────────
    def latest_for_host(self, host_id: int) -> Optional[models.HostMetric]:
        return (
            self.db.query(models.HostMetric)
            .filter(models.HostMetric.host_id == host_id)
            .order_by(models.HostMetric.timestamp.desc())
            .first()
        )

    def latest_n_for_host(
        self, host_id: int, *, limit: int
    ) -> list[models.HostMetric]:
        """Return the newest ``limit`` metrics, capped at 240
        (10 minutes @ 15 s heartbeat)."""
        return (
            self.db.query(models.HostMetric)
            .filter(models.HostMetric.host_id == host_id)
            .order_by(models.HostMetric.timestamp.desc())
            .limit(min(limit, 240))
            .all()
        )

    def container_metrics_for(
        self, host_metric_id: int
    ) -> list[models.ContainerMetric]:
        return (
            self.db.query(models.ContainerMetric)
            .filter(models.ContainerMetric.host_metric_id == host_metric_id)
            .order_by(models.ContainerMetric.name.asc())
            .all()
        )

    # ─── Mutations ─────────────────────────────────────────────────────
    def record_telemetry(
        self, *, host_id: int, payload: schemas.HostMetricCreate
    ) -> models.HostMetric:
        """Persist a HostMetric + its ContainerMetric children in one shot.

        Called from the ``POST /api/telemetry`` handler.
        """
        host_metric = models.HostMetric(
            host_id=host_id,
            cpu_percent=payload.cpu_percent,
            ram_percent=payload.ram_percent,
            disk_percent=payload.disk_percent,
            inode_percent=payload.inode_percent,
            disk_read_bytes_per_sec=payload.disk_read_bytes_per_sec,
            disk_write_bytes_per_sec=payload.disk_write_bytes_per_sec,
            net_external_rx_bps=payload.net_external_rx_bps,
            net_external_tx_bps=payload.net_external_tx_bps,
            net_internal_rx_bps=payload.net_internal_rx_bps,
            net_internal_tx_bps=payload.net_internal_tx_bps,
        )
        self.db.add(host_metric)
        self.db.commit()
        self.db.refresh(host_metric)

        for container in payload.containers:
            self.db.add(
                models.ContainerMetric(
                    host_metric_id=host_metric.id,
                    container_id=container.container_id,
                    name=container.name,
                    state=container.state,
                    cpu_percent=container.cpu_percent,
                    ram_percent=container.ram_percent,
                )
            )
        self.db.commit()
        return host_metric
