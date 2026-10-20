"""Keep the developer's real .env out of the unit tests.

Importing google-adk loads the repo's ``.env`` into ``os.environ`` as a side effect, so
``POLICY_API_*`` values from a deployed demo leak into tests that build the policy API and
make them fail depending on test order. Every test starts without those variables and
leaves the environment as it found it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_DEPLOYMENT_PREFIXES = ("POLICY_API_", "TF_VAR_")


@pytest.fixture(autouse=True)
def _isolate_deployment_env() -> Iterator[None]:
    saved = dict(os.environ)
    for key in [k for k in os.environ if k.startswith(_DEPLOYMENT_PREFIXES)]:
        del os.environ[key]
    yield
    os.environ.clear()
    os.environ.update(saved)
