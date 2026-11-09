from datetime import datetime
from typing import List, Optional

from sqlalchemy import Index, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models in Vigilant AI."""
    pass


class Site(Base):
    """
    Represents a target endpoint being monitored.
    Stores configuration for frequency, expectations, and anomaly thresholds.
    """
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    
    # Monitoring frequency
    interval_seconds: Mapped[int] = mapped_column(Integer, default=300)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Heuristic configuration
    # Soft-failure keywords (e.g., "database error", "maintenance mode")
    forbidden_keywords: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    # Required keywords (e.g., "Login", "Welcome")
    required_keywords: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    
    # Thresholds for anomaly detection
    latency_threshold_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    z_score_threshold: Mapped[float] = mapped_column(Float, default=3.0)
    
    # Tracking
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    results: Mapped[List["CheckResult"]] = relationship(
        "CheckResult", back_populates="site", cascade="all, delete-orphan"
    )
    alerts: Mapped[List["Alert"]] = relationship(
        "Alert", back_populates="site", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Site(name='{self.name}', url='{self.url}', active={self.is_active})>"


class CheckResult(Base):
    """
    Stores the outcome of a single monitoring probe.
    Used for historical analysis and Z-score calculation.
    """
    __tablename__ = "check_results"

    __table_args__ = (Index('ix_site_timestamp', 'site_id', 'timestamp'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now(), index=True)

    # Network metadata
    status_code: Mapped[int] = mapped_column(Integer)
    response_time_ms: Mapped[float] = mapped_column(Float)
    
    # Content metadata for drift detection
    content_length: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Analysis results
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    anomaly_score: Mapped[float] = mapped_column(Float, default=0.0)
    failure_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # e.g., "SOFT_FAILURE", "TIMEOUT", "DRIFT"
    
    # Raw breakdown of what the heuristic engine found
    analysis_details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="results")
    alerts: Mapped[List["Alert"]] = relationship("Alert", back_populates="check_result")

    def __repr__(self) -> str:
        return f"<CheckResult(site_id={self.site_id}, status={self.status_code}, anomaly={self.is_anomaly})>"


class Alert(Base):
    """
    Records an alert event triggered by the analysis engine.
    Tracks whether the user has been notified.
    """
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    check_result_id: Mapped[int] = mapped_column(ForeignKey("check_results.id"), nullable=False, index=True)
    
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    
    severity: Mapped[str] = mapped_column(String(20), default="WARNING")  # INFO, WARNING, CRITICAL
    message: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Notification status
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_channels: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)  # e.g., ["slack", "email"]
    
    # Relationships
    site: Mapped["Site"] = relationship("Site", back_populates="alerts")
    check_result: Mapped["CheckResult"] = relationship("CheckResult", back_populates="alerts")

    def __repr__(self) -> str:
        return f"<Alert(site_id={self.site_id}, severity='{self.severity}', notified={self.notified})>"


class GlobalConfig(Base):
    """
    Persisted global application settings.
    """
    __tablename__ = "global_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<GlobalConfig(key='{self.key}', value='{self.value}')>"
