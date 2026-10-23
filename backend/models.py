from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Enum, Boolean
from sqlalchemy.orm import relationship
import datetime
from database import Base
import enum

class RoleEnum(str, enum.Enum):
    editor = "editor"
    viewer = "viewer"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(RoleEnum), default=RoleEnum.viewer, nullable=False)

class Host(Base):
    __tablename__ = "hosts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)
    ip_address = Column(String, nullable=True)
    api_token = Column(String, unique=True, index=True, nullable=False)
    is_online = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    metrics = relationship("HostMetric", back_populates="host", cascade="all, delete-orphan")

class HostMetric(Base):
    __tablename__ = "host_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_id = Column(Integer, ForeignKey("hosts.id"))
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)
    disk_percent = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    host = relationship("Host", back_populates="metrics")
    container_metrics = relationship("ContainerMetric", back_populates="parent_metric", cascade="all, delete-orphan")

class ContainerMetric(Base):
    __tablename__ = "container_metrics"
    id = Column(Integer, primary_key=True, index=True)
    host_metric_id = Column(Integer, ForeignKey("host_metrics.id"))
    container_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    state = Column(String, nullable=False) # running, exited, etc.
    cpu_percent = Column(Float, nullable=False)
    ram_percent = Column(Float, nullable=False)

    parent_metric = relationship("HostMetric", back_populates="container_metrics")