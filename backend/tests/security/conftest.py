"""Shared setup for the sandbox security tests.

- Makes the `app` package importable when pytest runs from backend/ or from the repo root.
- Registers the `docker` marker. Docker-only cases are skipped unless DCE_TEST_DOCKER=1 and are meant
  for the Vultr VM, where the real worker image runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "docker: needs a real Docker host and the worker image (Vultr VM only)")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("DCE_TEST_DOCKER") == "1":
        return
    skip = pytest.mark.skip(reason="Docker-only test: set DCE_TEST_DOCKER=1 on a host with Docker")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)
