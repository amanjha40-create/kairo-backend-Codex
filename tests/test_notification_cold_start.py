"""Notification hooks must not make fresh application imports order-dependent."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["app.main", "app.auth.service"])
def test_notification_hooks_allow_fresh_runtime_import(module):
    environment = {**os.environ, "APP_ENV": "test"}
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}; print('COLD_START_PASS')"],
        env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, "Fresh runtime import failed"
    assert "COLD_START_PASS" in result.stdout
