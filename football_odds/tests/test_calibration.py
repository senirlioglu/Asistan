import numpy as np
import pytest

from src.backtest.calibration_model import walk_forward_calibration
from src.models.calibration import BucketCalibrator, IsotonicCalibrator


def _calibrated_sample(n=6000, seed=3, bias=0.0):
    rng = np.random.default_rng(seed)
    p = rng.dirichlet([3, 2, 2], n)
    # optional home bias: favourites win more often than priced
    true = p.copy()
    true[:, 0] = np.clip(true[:, 0] + bias * (true[:, 0] - 0.4), 0.01, 0.98)
    true = true / true.sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=row) for row in true])
    return p, y


def test_isotonic_outputs_valid_probabilities():
    p, y = _calibrated_sample()
    cal = IsotonicCalibrator().fit(p, y)
    out = cal.predict(p[:100])
    assert out.shape == (100, 3)
    assert np.allclose(out.sum(axis=1), 1.0)
    assert (out > 0).all()


def test_bucket_calibrator_learns_a_bias():
    p, y = _calibrated_sample(n=20000, bias=0.3)
    cal = BucketCalibrator().fit(p, y)
    out = cal.predict(p)
    strong = p[:, 0] > 0.6
    assert out[strong, 0].mean() > p[strong, 0].mean()  # lifts strong favourites
    weak = p[:, 0] < 0.3
    assert out[weak, 0].mean() < p[weak, 0].mean()      # trims underdogs


def test_bucket_calibrator_keeps_market_for_unseen_buckets():
    p, y = _calibrated_sample(n=3000)
    cal = BucketCalibrator(min_bucket=100000).fit(p, y)  # no bucket qualifies
    out = cal.predict(p[:50])
    assert np.allclose(out, p[:50] / p[:50].sum(axis=1, keepdims=True), atol=1e-6)


def test_isotonic_needs_enough_data():
    p, y = _calibrated_sample(n=100)
    with pytest.raises(ValueError):
        IsotonicCalibrator(min_train=2000).fit(p, y)


def test_walk_forward_calibration_uses_only_earlier_seasons(history):
    seasons = sorted(history["season"].unique())
    test_seasons = seasons[-2:]
    test_df, preds = walk_forward_calibration(history, test_seasons, min_train_seasons=2)
    assert set(test_df["season"]) <= set(test_seasons)
    for m, p in preds.items():
        assert p.shape == (len(test_df), 3)
        assert np.allclose(p.sum(axis=1), 1.0)
    # on a calibrated synthetic market the calibrators stay close to the market
    market = test_df[["p_home", "p_draw", "p_away"]].to_numpy()
    assert np.abs(preds["bucket"] - market).mean() < 0.03
