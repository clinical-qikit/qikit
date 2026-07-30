"""
Shared fixtures for qikit tests.
"""

import sys
from pathlib import Path

# Tests must exercise the checkout they live in. Both the repo .venv and the system
# Python carry editable installs of clinical-qikit whose .pth files hard-code the
# path of the primary checkout, so a run from a git worktree would otherwise import
# whatever branch that other tree is sitting on.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def normal_30(rng):
    """30 observations ~ N(10, 2)."""
    return rng.normal(loc=10, scale=2, size=30)


@pytest.fixture
def proportions():
    """Typical p-chart data: 20 subgroups of ~100 patients."""
    rng = np.random.default_rng(0)
    n = rng.integers(80, 120, size=20).astype(float)
    events = rng.binomial(n.astype(int), 0.1)
    return events / n, n


@pytest.fixture
def counts():
    """c-chart data: 20 count observations."""
    rng = np.random.default_rng(1)
    return rng.poisson(5, size=20).astype(float)


@pytest.fixture
def rates():
    """u-chart data: 20 rate observations."""
    rng = np.random.default_rng(2)
    n = rng.integers(50, 150, size=20).astype(float)
    events = rng.poisson(2 * n / 100)
    return events / n, n
