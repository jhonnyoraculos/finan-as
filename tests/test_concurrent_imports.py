"""Regression test for Streamlit's concurrent first-load imports."""

from pathlib import Path
import subprocess
import sys


def test_application_packages_can_be_imported_concurrently() -> None:
    script = r'''
from concurrent.futures import ThreadPoolExecutor
import importlib
import threading

modules = (
    "database.connection",
    "database.models",
    "database.repository",
    "services.application_service",
    "services.forecast_query_service",
    "components.navigation",
    "components.cards",
    "views.home",
)
barrier = threading.Barrier(len(modules))

def load(name):
    barrier.wait()
    return importlib.import_module(name).__name__

with ThreadPoolExecutor(max_workers=len(modules)) as executor:
    assert list(executor.map(load, modules)) == list(modules)
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
