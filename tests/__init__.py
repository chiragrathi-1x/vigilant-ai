"""
Test package initialization for the vigilant-ai monitoring engine.
This file defines shared constants, environment configurations, and sample data 
used across multiple test modules (e.g., test_checker.py and test_analyzer.py).
"""

import os
from pathlib import Path
from typing import Final

# Force testing environment variables to prevent accidental 
# interference with production databases or configurations.
os.environ["VIGILANT_ENV"] = "testing"
os.environ["SQLALCHEMY_WARN_20"] = "1"

# Path definitions
TEST_ROOT: Final[Path] = Path(__file__).parent.resolve()
PROJECT_ROOT: Final[Path] = TEST_ROOT.parent

# Test Database URL - using in-memory SQLite for speed and isolation
# Using aiosqlite as the async driver for SQLAlchemy
TEST_DB_URL: Final[str] = "sqlite+aiosqlite:///:memory:"

# Mocking constants for checkers
DEFAULT_MOCK_URL: Final[str] = "https://status.vigilant-ai.local"
DEFAULT_TIMEOUT: Final[float] = 5.0

# -----------------------------------------------------------------------------
# Heuristic Test Data
# Used by test_analyzer.py to verify soft-failure detection algorithms.
# -----------------------------------------------------------------------------

# A standard successful page structure
SAMPLE_HEALTHY_PAGE: Final[str] = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Production Dashboard</title>
</head>
<body>
    <header><h1>System Status: All Green</h1></header>
    <main>
        <p>All microservices are reporting healthy status codes.</p>
        <div id="data-grid">Real-time telemetry data active.</div>
    </main>
    <footer>Version 1.0.4</footer>
</body>
</html>
""".strip()

# A page that returns 200 OK but displays a visual error message (Soft Failure)
SAMPLE_SOFT_FAILURE_PAGE: Final[str] = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Production Dashboard</title>
</head>
<body>
    <header><h1>System Status</h1></header>
    <main>
        <div class="error-container" style="color: red;">
            <h2>Internal Server Error (500)</h2>
            <p>Exception: Database connection refused at 10.0.4.12.</p>
            <pre>stacktrace: ...</pre>
        </div>
    </main>
</body>
</html>
""".strip()

# A page that is broken due to unrendered template tags (Soft Failure)
SAMPLE_UNRENDERED_TEMPLATE: Final[str] = """
<!DOCTYPE html>
<html>
<head><title>{{ site_title }}</title></head>
<body>
    <ul>
    {% for item in items %}
        <li>{{ item.name }}</li>
    {% endfor %}
    </ul>
</body>
</html>
""".strip()

# A page with significant content drift (too short compared to baseline)
SAMPLE_MINIMAL_RESPONSE: Final[str] = "<html><body>Error</body></html>"

def get_test_resource_path(filename: str) -> Path:
    """
    Helper to locate static test resources if needed in the future.
    """
    return TEST_ROOT / "resources" / filename
