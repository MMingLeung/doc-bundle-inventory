"""Pytest fixtures."""

from __future__ import annotations

import importlib.util

import pytest

from tests.ziputil import REPO_ROOT


@pytest.fixture(scope="session")
def sample_tools():
    path = REPO_ROOT / "examples" / "build_sample_bundle.py"
    spec = importlib.util.spec_from_file_location("build_sample_bundle", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
