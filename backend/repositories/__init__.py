"""Repository layer — Lab Assignment #12 (Architectural / Structural pattern).

Encapsulates every ``db.query(...)`` call that used to live inline in
``main.py``. Each repository owns one aggregate (User / Host / Metric)
and exposes a narrow, intention-revealing API. Routes become thin HTTP
adapters: they parse the request, call a repository, format the response.

Benefits:
  * One place to change a query shape (ordering, filters, joins).
  * Testable in isolation — swap the Session for a fake / in-memory one.
  * No business logic lives in controllers any more.
"""
from .user_repository import UserRepository
from .host_repository import HostRepository
from .metric_repository import MetricRepository

__all__ = ["UserRepository", "HostRepository", "MetricRepository"]
