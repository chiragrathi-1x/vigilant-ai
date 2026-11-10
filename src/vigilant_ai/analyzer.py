import logging
import re
import statistics
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

@dataclass
class AnalysisResult:
    is_healthy: bool
    failure_reason: Optional[str] = None
    metrics_meta: Optional[Dict] = None
    is_hard_failure: bool = False

class ContentAnalyzer:
    ERROR_KEYWORDS = [
        r"database error", r"sql state", r"connection refused", r"internal server error",
        r"stack trace", r"exception occurred", r"access denied", r"unauthorized access",
        r"maintenance mode", r"service unavailable", r"site under maintenance"
    ]

    def __init__(self, drift_threshold: float = 0.4):
        self.drift_threshold = drift_threshold
        self._regex_patterns = [re.compile(p, re.IGNORECASE) for p in self.ERROR_KEYWORDS]

    def check_for_error_keywords(self, html_content: str) -> Tuple[bool, Optional[str]]:
        if not html_content: return False, None
        for pattern in self._regex_patterns:
            if pattern.search(html_content):
                return True, f"Detected error keyword: '{pattern.pattern}'"
        return False, None

    def calculate_drift(self, current_content: str, baseline_content: Optional[str]) -> float:
        if not baseline_content: return 0.0
        matcher = SequenceMatcher(None, current_content[:10000], baseline_content[:10000])
        return 1.0 - matcher.ratio()

class PerformanceAnalyzer:
    def __init__(self, z_score_threshold: float = 3.0, min_observations: int = 5):
        self.z_score_threshold = z_score_threshold
        self.min_observations = min_observations

    def analyze_latency(self, current_latency_ms: float, historical_latencies: List[float]) -> Tuple[bool, float]:
        if len(historical_latencies) < self.min_observations or len(historical_latencies) < 2:
            return False, 0.0
        mean = statistics.mean(historical_latencies)
        stdev = statistics.stdev(historical_latencies)
        if stdev == 0: return False, 0.0
        z_score = abs(current_latency_ms - mean) / stdev
        return z_score > self.z_score_threshold, z_score

class AnomalyAnalyzer:
    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self.content_analyzer = ContentAnalyzer(drift_threshold=self.config.get("drift_threshold", 0.4))
        self.perf_analyzer = PerformanceAnalyzer(z_score_threshold=self.config.get("z_score_threshold", 3.0))

    def analyze(self, response: Any, history: List[Any], baseline_content: Optional[str] = None) -> AnalysisResult:
        if not (200 <= response.status_code < 300):
            return AnalysisResult(is_healthy=False, failure_reason=f"Status {response.status_code}", is_hard_failure=True)

        has_error_keyword, reason = self.content_analyzer.check_for_error_keywords(response.content)
        if has_error_keyword:
            return AnalysisResult(is_healthy=False, failure_reason=reason, metrics_meta={"latency": response.latency_ms})

        historical_latencies = [r.response_time_ms for r in history if hasattr(r, 'response_time_ms')]
        is_lat_anomaly, z_score = self.perf_analyzer.analyze_latency(response.latency_ms, historical_latencies)
        if is_lat_anomaly:
            return AnalysisResult(is_healthy=True, failure_reason=f"Latency spike (Z: {z_score:.2f})", metrics_meta={"z_score": z_score})

        return AnalysisResult(is_healthy=True, metrics_meta={"latency": response.latency_ms})

    def generate_baseline(self, content: str) -> str:
        cleaned = re.sub(r'<(script|style).*?>.*?</\1>', '', content, flags=re.DOTALL | re.IGNORECASE)
        return cleaned.strip()
