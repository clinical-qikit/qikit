import math

import pytest

from conformance_helpers import extract, fixture_paths, run_fixture

FIXTURES = fixture_paths()


def test_fixtures_are_found():
    # A cwd-relative glob once collected nothing from another directory and passed.
    assert len(FIXTURES) > 50


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture(path):
    fix, result = run_fixture(path)
    for key, spec in fix["check"].items():
        actual = extract(result, key)
        if isinstance(spec, list):  # [value, tolerance]
            assert math.isclose(actual, spec[0], abs_tol=spec[1]), \
                f"{key}: {actual} != {spec[0]} (±{spec[1]})"
        else:
            assert actual == spec, f"{key}: {actual} != {spec}"
