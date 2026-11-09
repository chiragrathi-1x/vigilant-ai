# vigilant-ai 🕵️‍♂️

**A production-grade monitoring engine that identifies "soft failures" beyond simple status codes.**

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Standard uptime monitors notify you when a site returns a 500 error or goes offline. `vigilant-ai` is designed for the modern web, where single-page applications (SPAs) or misconfigured CDNs often return a `200 OK` status code while displaying "Application Error," "Database Connection Failed," or a completely broken layout.

By utilizing lightweight natural language heuristics and rolling statistical analysis, `vigilant-ai` detects semantic drift and performance anomalies before your users do.

---

## 🚀 Features

- **Asynchronous Execution:** Built on `httpx` and `asyncio` to monitor hundreds of endpoints concurrently without blocking.
- **Soft-Failure Detection:** Identifies "Error-in-Success" patterns where pages return 200 OK but contain failure keywords or significantly altered content structures.
- **Performance Anomaly Detection:** Uses rolling Z-score analysis to identify latency spikes that deviate from historical norms, rather than just hitting static thresholds.
- **Semantic Drift Analysis:** Uses similarity metrics (e.g., Levenshtein or Jaccard distance) to detect unexpected page changes. Unlike binary hash comparisons, this allows for the fine-tuned sensitivity required to detect partial renders or broken layouts.
- **Extensible Notifications:** Built-in support for Slack and Webhooks with a plug-and-play architecture for custom alerts.
- **SQLite Persistence:** Keeps a local record of all checks, latencies, and failures for trend analysis and historical reporting.

---

## 🏗 Architecture

The system is composed of several specialized modules:

- **CLI Entry Point (`vigilant_ai/main.py`):** The primary command-line interface for managing monitored sites and initializing the async engine loop.
- **Engine (`vigilant_ai/engine.py`):** The heart of the service. It manages the scheduling loop and dispatches tasks to the checkers.
- **Checker (`vigilant_ai/checker.py`):** Handles the low-level I/O. It captures status codes, headers, and response bodies while timing the request.
- **Analyzer (`vigilant_ai/analyzer.py`):** The logic layer. It runs heuristic checks against the response body and compares current latency against historical data stored in the DB.
- **Models & DB (`vigilant_ai/models.py`, `vigilant_ai/database.py`):** SQLAlchemy-based persistence layer using SQLite for low-overhead state management.

---

## 📦 Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-org/vigilant-ai.git
   cd vigilant-ai
   ```

2. **Set up a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

---

## 🛠 Usage

### Initialization
First, initialize your monitoring database and add your first site:
```bash
# Add a site to monitor
python3 -m vigilant_ai.main add --name "Marketing Site" --url "https://example.com" --interval 60
```

### Starting the Daemon
Run the monitoring engine to start the async check loop:
```bash
python3 -m vigilant_ai.main start
```

### Management Commands
```bash
# List all monitored sites and their current status
python3 -m vigilant_ai.main status

# Remove a site
python3 -m vigilant_ai.main remove --id 1
```

---

## ⚙️ Configuration

`vigilant-ai` can be configured via environment variables or a `.env` file.

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLAlchemy connection string | `sqlite:///./vigilant_ai.db` |
| `SLACK_WEBHOOK_URL` | Optional Slack integration | `None` |
| `LOG_LEVEL` | Logging verbosity (DEBUG/INFO/ERROR) | `INFO` |
| `DRIFT_THRESHOLD` | Sensitivity for content change detection | `0.15` |
| `Z_SCORE_THRESHOLD` | Standard deviations for latency alerts | `3.0` |

---

## 🔬 How Anomaly Detection Works

### 1. Semantic Soft-Failure
The analyzer scans the response body for a configurable list of "failure indicators" (e.g., "SQL Error," "Connection Refused," "Unexpected Token"). Even if the HTTP status is `200`, the presence of these strings triggers a high-severity alert.

### 2. Statistical Latency (Z-Score)
Rather than setting a static timeout of 2 seconds (which might be normal for some endpoints but slow for others), we calculate the mean ($\mu$) and standard deviation ($\sigma$) of the last 50 requests. If:
$$\frac{x - \mu}{\sigma} > Threshold$$
...an anomaly is logged. This allows the system to adapt to the "natural" speed of your services.

### 3. Content Drift
We compute similarity metrics (e.g., Levenshtein or Jaccard distance) between the current response body and the known baseline. Because a simple hash comparison is binary (match or no-match), it is incompatible with the decimal `DRIFT_THRESHOLD`. By calculating the relative distance between states, `vigilant-ai` can flag significant deviations—such as a 50KB page suddenly dropping to 2KB or a critical JS bundle missing—even if the status remains `200 OK`.

---

## 🧪 Testing

The project uses `pytest` with `pytest-asyncio` for testing concurrent logic.

```bash
# Run all tests
pytest tests/

# Run specific analyzer tests
pytest tests/test_analyzer.py
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
