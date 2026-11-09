import logging
import re
import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

@dataclass
class AnalysisResult:
    """Encapsulates the findings of a site check analysis."""
    is_healthy: bool
    status_label: str  # e.g., "healthy", "soft_failure", "latency_anomaly", "down"
    score: float       # 0.0 to 1.0 (1.0 being perfect)
    reason: Optional[str] = None
    metrics: Optional[Dict] = None

class ContentAnalyzer:
    """
    Analyzes page content for 'soft failures' where the server returns 200 OK
    but the page contains error messages or significant structural drift.
    """
    
    # Common strings that indicate a failure even if the HTTP status is 200
    ERROR_KEYWORDS = [
        r"database error",
        r"sql state",
        r"connection refused",
        r"internal server error",
        r"stack trace",
        r"exception occurred",
        r"access denied",
        r"unauthorized access",
        r"maintenance mode",
        r"service unavailable",
        r"site under maintenance",
        r"nginx error",
        r"apache error",
        r"404 not found",  # Sometimes 404s are returned as 200s by bad CMS configs
        r"backend fetch failed",
        r"error processing request"
    ]

    def __init__(self, drift_threshold: float = 0.4):
        """
        Args:
            drift_threshold: Maximum allowed structural change (0.0 to 1.0).
                             Higher means more sensitive to change.
        """
        self.drift_threshold = drift_threshold
        self._regex_patterns = [re.compile(p, re.IGNORECASE) for p in self.ERROR_KEYWORDS]

    def check_for_error_keywords(self, html_content: str) -> Tuple[bool, Optional[str]]:
        """Scans content for known error signatures."""
        if not html_content:
            return False, None

        for pattern in self._regex_patterns:
            if pattern.search(html_content):
                return True, f"Detected error keyword pattern: '{pattern.pattern}'"
        
        return False, None

    def calculate_drift(self, current_content: str, baseline_content: Optional[str]) -> float:
        """
        Calculates the similarity between current content and baseline content.
        Returns a float between 0 (identical) and 1 (completely different).
        """
        if not baseline_content:
            return 0.0
        
        # We use a ratio-based approach. For production efficiency with large pages,
        # we focus on a sample or structural signature if this were a heavy-load service.
        # Here we use SequenceMatcher for a robust heuristic.
        matcher = SequenceMatcher(None, current_content[:10000], baseline_content[:10000])
        similarity = matcher.ratio()
        
        return 1.0 - similarity

class PerformanceAnalyzer:
    """
    Uses statistical methods to detect latency anomalies.
    """

    def __init__(self, z_score_threshold: float = 3.0, min_observations: int = 5):
        """
        Args:
            z_score_threshold: Number of standard deviations to trigger an anomaly.
            min_observations: Minimum data points required before performing Z-score analysis.
        """
        self.z_score_threshold = z_score_threshold
        self.min_observations = min_observations

    def analyze_latency(self, current_latency_ms: float, historical_latencies: List[float]) -> Tuple[bool, float]:
        """
        Determines if the current latency is a statistical outlier.
        Returns (is_anomaly, z_score).
        """
        if len(historical_latencies) < self.min_observations or len(historical_latencies) < 2:
            return False, 0.0

        mean = statistics.mean(historical_latencies)
        stdev = statistics.stdev(historical_latencies)

        if stdev == 0:
            return False, 0.0

        z_score = abs(current_latency_ms - mean) / stdev
        
        is_anomaly = z_score > self.z_score_threshold
        return is_anomaly, z_score

class VigilantAnalyzer:
    """
    The main orchestration engine for analyzing a check result.
    Combines keyword detection, drift analysis, and performance metrics.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.content_analyzer = ContentAnalyzer(
            drift_threshold=self.config.get("drift_threshold", 0.4)
        )
        self.perf_analyzer = PerformanceAnalyzer(
            z_score_threshold=self.config.get("z_score_threshold", 3.0)
        )

    def analyze(
        self, 
        status_code: int, 
        latency_ms: float, 
        content: str, 
        historical_latencies: List[float],
        baseline_content: Optional[str] = None
    ) -> AnalysisResult:
        """
        Performs a full heuristic analysis on a site response.
        """
        # 1. Hard Failure Check
        if not (200 <= status_code < 300):
            return AnalysisResult(
                is_healthy=False,
                status_label="down",
                score=0.0,
                reason=f"HTTP Status {status_code}",
                metrics={"latency": latency_ms}
            )

        # 2. Keyword Failure Check (Soft Failure)
        has_error_keyword, reason = self.content_analyzer.check_for_error_keywords(content)
        if has_error_keyword:
            return AnalysisResult(
                is_healthy=False,
                status_label="soft_failure",
                score=0.2,
                reason=reason,
                metrics={"latency": latency_ms}
            )

        # 3. Content Drift Check
        drift_score = 0.0
        if baseline_content:
            normalized_content = self.generate_baseline(content)
            normalized_baseline = self.generate_baseline(baseline_content)
            drift_score = self.content_analyzer.calculate_drift(normalized_content, normalized_baseline)
            if drift_score > self.content_analyzer.drift_threshold:
                return AnalysisResult(
                    is_healthy=False,
                    status_label="soft_failure",
                    score=0.4,
                    reason=f"Content drift detected ({drift_score:.2f} > {self.content_analyzer.drift_threshold})",
                    metrics={"latency": latency_ms, "drift": drift_score}
                )

        # 4. Latency Anomaly Check
        is_latency_anomaly, z_score = self.perf_analyzer.analyze_latency(latency_ms, historical_latencies)
        if is_latency_anomaly:
            # We flag this but might not mark the site as completely "unhealthy" 
            # unless it's sustained. For now, we report it as an anomaly.
            return AnalysisResult(
                is_healthy=True, # Site is serving content, but slow
                status_label="latency_anomaly",
                score=0.7,
                reason=f"Significant latency spike (Z-score: {z_score:.2f})",
                metrics={"latency": latency_ms, "z_score": z_score, "drift": drift_score}
            )

        # 5. All checks passed
        return AnalysisResult(
            is_healthy=True,
            status_label="healthy",
            score=1.0,
            reason=None,
            metrics={"latency": latency_ms, "drift": drift_score}
        )

    def generate_baseline(self, content: str) -> str:
        """
        Cleans and prepares content to be used as a structural baseline.
        In a production-grade tool, we might strip CSRF tokens or timestamps.
        """
        # Basic normalization: remove script tags and style tags content which changes often
        cleaned = re.sub(r'<(script|style).*?>.*?</\1>', '', content, flags=re.DOTALL | re.IGNORECASE)
        # Remove common dynamic noise like CSRF tokens or session IDs in hidden inputs
        cleaned = re.sub(r'value="[a-zA-Z0-9]{32,}"', 'value="REDACTED"', cleaned)
        return cleaned.strip()
