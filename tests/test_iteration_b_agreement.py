"""Cross-check with pinned Krippendorff 0.8.2 and non-estimable cases."""

import time

import krippendorff
import numpy as np
import pytest

from ecoalign_forge.storage.agreement import alpha_estimate, krippendorffs_alpha


@pytest.mark.parametrize("metric", ["nominal", "ordinal", "interval"])
def test_reference_random_missing_unequal_raters(metric):
    rng = np.random.default_rng(928)
    for size in [3, 17, 100]:
        values = rng.integers(0, 4, size=(size, 5)).astype(float)
        values[rng.random(values.shape) < 0.3] = np.nan
        matrix = [[None if np.isnan(v) else int(v) for v in row] for row in values]
        reference = krippendorff.alpha(
            reliability_data=values.T, value_domain=np.arange(4), level_of_measurement=metric
        )
        assert krippendorffs_alpha(matrix, metric=metric, categories=[0, 1, 2, 3]) == pytest.approx(
            reference
        )


def test_non_estimable_and_no_quadratic_item_pairs():
    assert alpha_estimate([["x", "x"]]).reason == "zero_expected_disagreement"
    assert alpha_estimate([[None, "x"], ["y", None]]).value is None
    started = time.monotonic()
    result = krippendorffs_alpha([[i % 4, (i + 1) % 4, None] for i in range(10000)])
    assert result is not None and time.monotonic() - started < 3
    with pytest.raises(ValueError, match="explicit category order"):
        krippendorffs_alpha([["x", "y"]], metric="ordinal")
