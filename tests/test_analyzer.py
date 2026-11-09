import pytest
import math
from typing import List
from src.vigilant_ai.analyzer import Analyzer
from src.vigilant_ai.models import CheckResult, Site

@pytest.fixture
def analyzer():
    """Returns a standard Analyzer instance for testing."""
    return Analyzer()

@pytest.fixture
def mock_site():
    """Mock site object with basic configuration."""
    return Site(
        id=1,
        url="https://example.com",
        name="Example Site",
        expected_status=200,
        drift_threshold=0.3  # 30% change allowed
    )

def test_keyword_detection_matches(analyzer):
    """Ensure that known error keywords in the body trigger a soft failure."""
    body_with_error = "<html><body><h1>Welcome</h1><p>Internal Server Error</p></body></html>"
    # We expect a high score or a specific flag for keyword matches
    is_soft_failure, reason = analyzer.check_for_error_keywords(body_with_error)
    assert is_soft_failure is True
    assert "Internal Server Error" in reason

def test_keyword_detection_clean(analyzer):
    """Ensure that healthy content does not trigger keyword flags."""
    healthy_body = "<html><body><h1>Operations Dashboard</h1><p>Systems are nominal.</p></body></html>"
    is_soft_failure, reason = analyzer.check_for_error_keywords(healthy_body)
    assert is_soft_failure is False
    assert reason == ""

def test_calculate_z_score(analyzer):
    """Test the statistical Z-score calculation for latency anomalies."""
    history = [100.0, 105.0, 98.0, 102.0, 110.0]  # Mean: 103, StdDev: ~4.3
    current_latency = 200.0  # Clearly an outlier
    
    z_score = analyzer.calculate_z_score(current_latency, history)
    
    # Calculation check: (200 - 103) / 4.3 = ~22.5
    assert z_score > 3.0  # Standard threshold for statistical significance

def test_calculate_z_score_insufficient_data(analyzer):
    """Z-score should return 0 if there isn't enough history to compute variance."""
    history = [100.0]
    z_score = analyzer.calculate_z_score(150.0, history)
    assert z_score == 0.0

def test_content_drift_significant(analyzer, mock_site):
    """Test that significant changes in body content are detected."""
    baseline = "This is the original content of the landing page."
    new_content = "Something went wrong. Access Denied. Contact Admin."
    
    # We use a simple Jaccard similarity or Levenshtein-based heuristic in the analyzer
    drift_score = analyzer.calculate_content_drift(baseline, new_content)
    
    # drift_score should be high (closer to 1.0) because strings are very different
    assert drift_score > mock_site.drift_threshold
    assert analyzer.is_drift_anomalous(drift_score, mock_site.drift_threshold) is True

def test_content_drift_minimal(analyzer, mock_site):
    """Test that minor changes (like timestamps) do not trigger drift alerts."""
    baseline = "Welcome to our site. Last updated: 2023-01-01 10:00:00"
    new_content = "Welcome to our site. Last updated: 2023-01-01 10:01:00"
    
    drift_score = analyzer.calculate_content_drift(baseline, new_content)
    
    # drift_score should be very low
    assert drift_score < mock_site.drift_threshold
    assert analyzer.is_drift_anomalous(drift_score, mock_site.drift_threshold) is False

def test_analyze_full_result_healthy(analyzer, mock_site):
    """Integration test for the analyze method with a healthy result."""
    check_result = CheckResult(
        site_id=mock_site.id,
        status_code=200,
        response_time=105.0,
        response_body="<html><body>All systems go.</body></html>"
    )
    
    # History of latencies
    history = [100.0, 102.0, 101.0, 99.0, 104.0]
    # Baseline body
    baseline_body = "<html><body>All systems go.</body></html>"
    
    analysis = analyzer.analyze(check_result, history, baseline_body, mock_site)
    
    assert analysis["is_anomalous"] is False
    assert analysis["status"] == "healthy"
    assert len(analysis["alerts"]) == 0

def test_analyze_full_result_soft_failure(analyzer, mock_site):
    """Integration test identifying a 'soft failure' (200 OK but error content)."""
    check_result = CheckResult(
        site_id=mock_site.id,
        status_code=200,
        response_time=110.0,
        response_body="<html><body>Error: Database connection failed.</body></html>"
    )
    
    history = [100.0, 102.0, 101.0, 99.0, 104.0]
    baseline_body = "<html><body>Welcome to the Dashboard</body></html>"
    
    analysis = analyzer.analyze(check_result, history, baseline_body, mock_site)
    
    assert analysis["is_anomalous"] is True
    # Should identify both keyword match and content drift
    reasons = [a["type"] for a in analysis["alerts"]]
    assert "keyword_match" in reasons
    assert "content_drift" in reasons

def test_analyze_full_result_latency_anomaly(analyzer, mock_site):
    """Integration test identifying a latency spike."""
    check_result = CheckResult(
        site_id=mock_site.id,
        status_code=200,
        response_time=5000.0, # Massive spike
        response_body="<html><body>Welcome to the Dashboard</body></html>"
    )
    
    history = [100.0, 110.0, 105.0, 115.0, 102.0]
    baseline_body = "<html><body>Welcome to the Dashboard</body></html>"
    
    analysis = analyzer.analyze(check_result, history, baseline_body, mock_site)
    
    assert analysis["is_anomalous"] is True
    assert any(a["type"] == "latency_anomaly" for a in analysis["alerts"])
    assert analysis["latency_z_score"] > 5.0

def test_jaccard_similarity_logic(analyzer):
    """Test the underlying similarity logic directly."""
    str1 = "The quick brown fox jumps over the lazy dog"
    str2 = "The quick brown fox jumps over the lazy dog"
    str3 = "A completely different set of words that do not match"
    
    sim_identical = analyzer._calculate_similarity(str1, str2)
    sim_different = analyzer._calculate_similarity(str1, str3)
    
    assert sim_identical == 1.0
    assert sim_different < 0.2

def test_empty_body_handling(analyzer, mock_site):
    """Check how the analyzer handles empty or null response bodies."""
    check_result = CheckResult(
        site_id=mock_site.id,
        status_code=200,
        response_time=100.0,
        response_body=""
    )
    
    analysis = analyzer.analyze(check_result, [], None, mock_site)
    # An empty body when we expect content is usually considered drift/anomaly
    assert analysis["is_anomalous"] is True
    assert any(a["type"] == "empty_body" for a in analysis["alerts"])

def test_status_code_mismatch(analyzer, mock_site):
    """Traditional monitoring test: Status code doesn't match expected."""
    check_result = CheckResult(
        site_id=mock_site.id,
        status_code=500,
        response_time=50.0,
        response_body="Internal Error"
    )
    
    analysis = analyzer.analyze(check_result, [], "Baseline", mock_site)
    assert analysis["is_anomalous"] is True
    assert any(a["type"] == "status_code_mismatch" for a in analysis["alerts"])
