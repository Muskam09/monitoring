from pydantic import BaseModel
from typing import List

class ContainerMetricCreate(BaseModel):
    container_id: str
    name: str
    state: str
    cpu_percent: float
    ram_percent: float

class HostMetricCreate(BaseModel):
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    containers: List[ContainerMetricCreate] = []