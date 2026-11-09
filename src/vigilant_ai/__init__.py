"""
Vigilant AI - Intelligent Website Monitoring Engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A production-grade monitoring engine that goes beyond status codes. It uses 
lightweight natural language heuristics and statistical anomaly detection to 
identify 'soft failures' where a site returns 200 OK but displays error 
messages or broken layouts.

:copyright: (c) 2023 Vigilant AI Team
:license: MIT, see LICENSE for more details.
"""

import logging
import re
from typing import NamedTuple

# Versioning using SemVer
__version__ = "0.1.0"
__author__ = "Vigilant AI Team"


class VersionInfo(NamedTuple):
    major: int
    minor: int
    micro: int
    releaselevel: str


def _parse_version(version: str) -> VersionInfo:
    match = re.match(r"(\d+)\.(\d+)\.(\d+)(?:-(.+))?", version)
    if not match:
        return VersionInfo(0, 0, 0, "unknown")
    
    parts = match.groups()
    return VersionInfo(
        int(parts[0]), 
        int(parts[1]), 
        int(parts[2]), 
        parts[3] or "final"
    )


version_info = _parse_version(__version__)

# Configure a NullHandler for the logger to prevent "No handler found" 
# warnings in applications that do not configure logging themselves.
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Export primary interfaces for easier access when used as a library.
from .engine import MonitoringEngine
from .checker import SiteChecker
from .analyzer import DriftAnalyzer
from .config import settings

__all__ = [
    "MonitoringEngine",
    "SiteChecker",
    "DriftAnalyzer",
    "settings",
    "__version__",
    "version_info",
]
