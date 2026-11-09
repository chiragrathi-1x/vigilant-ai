import os
from pathlib import Path
from typing import List, Optional

class Settings:
    """
    Configuration loader for the Vigilant AI monitoring engine.
    Values are loaded from environment variables with sensible defaults 
    tailored for production-grade reliability.
    """

    # Project Structure
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"

    # Database
    # Defaulting to a local SQLite database for simplified state management
    DATABASE_URL: str = os.getenv(
        "VIGILANT_DATABASE_URL", 
        f"sqlite:///{DATA_DIR}/vigilant_ai.db"
    )

    # Monitoring Execution
    CHECK_INTERVAL_SECONDS: int = int(os.getenv("VIGILANT_CHECK_INTERVAL", "60"))
    MAX_CONCURRENT_CHECKS: int = int(os.getenv("VIGILANT_MAX_CONCURRENCY", "20"))
    HTTP_TIMEOUT: float = float(os.getenv("VIGILANT_HTTP_TIMEOUT", "10.0"))
    USER_AGENT: str = os.getenv(
        "VIGILANT_USER_AGENT", 
        "VigilantAI/1.0 (Monitoring Engine; Anomaly Detection)"
    )

    # Anomaly Detection Heuristics
    # Sensitivity for statistical latency anomalies (Z-Score)
    # 2.0 = ~95% confidence, 3.0 = ~99% confidence
    LATENCY_Z_SCORE_THRESHOLD: float = float(os.getenv("VIGILANT_Z_SCORE_THRESHOLD", "2.5"))
    
    # Semantic Drift Threshold (0.0 to 1.0)
    # How much a page's structure/content can change before being flagged as a soft failure
    DRIFT_THRESHOLD: float = float(os.getenv("VIGILANT_DRIFT_THRESHOLD", "0.35"))

    # Natural Language Heuristics
    # Keywords that indicate a failure even if the status code is 200 OK
    SOFT_FAILURE_KEYWORDS: List[str] = [
        "sql error",
        "database connection failed",
        "unhandled exception",
        "access denied",
        "internal server error",
        "stack trace",
        "critical error occurred",
        "down for maintenance",
        "site under maintenance",
        "service unavailable"
    ]

    # Notification Settings
    SLACK_WEBHOOK_URL: Optional[str] = os.getenv("VIGILANT_SLACK_WEBHOOK_URL")
    WEBHOOK_NOTIFY_URL: Optional[str] = os.getenv("VIGILANT_WEBHOOK_NOTIFY_URL")

    # Logging
    LOG_LEVEL: str = os.getenv("VIGILANT_LOG_LEVEL", "INFO")

    def __init__(self):
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        """Creates the data directory if it doesn't exist to prevent SQLite initialization errors."""
        if self.DATABASE_URL.startswith("sqlite"):
            self.DATA_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def is_slack_enabled(self) -> bool:
        return bool(self.SLACK_WEBHOOK_URL)

    @property
    def is_webhook_enabled(self) -> bool:
        return bool(self.WEBHOOK_NOTIFY_URL)

# Global settings instance
settings = Settings()

# Validation for critical production configurations
if not settings.DATABASE_URL:
    raise ValueError("VIGILANT_DATABASE_URL must be set for the application to start.")

def get_fail_keywords() -> List[str]:
    """
    Returns a merged list of default and environment-specific keywords 
    used for identifying soft failures.
    """
    extra_keywords = os.getenv("VIGILANT_EXTRA_KEYWORDS", "")
    if extra_keywords:
        return settings.SOFT_FAILURE_KEYWORDS + [k.strip() for k in extra_keywords.split(",")]
    return settings.SOFT_FAILURE_KEYWORDS
