import numpy as np
import pandas as pd
import pytest

from src.features.vectors import similarity_pct, total_variation
from src.models.similarity import SimilarityIndex


def test_similarity_pct_definition():
    q = np.array([0.55, 0.25, 0.20])
    pool = np.array([[0.55, 0.25, 0.20], [0.57, 0.25, 0.18], [0.75, 0.15, 0.10]])
    tv = total_variation(q, pool, "1x2")
    assert tv[0] == pytest.approx(0.0)
    assert tv[1] == pytest.approx(0.02)   # 2 pp of probability mass moved
    assert similarity_pct(q, pool, "1x2")[1] == pytest.approx(98.0)
    assert similarity_pct(q, pool, "1x2")[2] == pytest.approx(80.0)


def test_similarity_pct_ou_is_market_average():
    q = np.array([0.5, 0.3, 0.2, 0.5, 0.5])
    pool = np.array([[0.5, 0.3, 0.2, 0.6, 0.4]])  # 1X2 identical, O/U 10 pp apart
    assert similarity_pct(q, pool, "1x2_ou")[0] == pytest.approx(95.0)


def test_no_lookahead_strict_date(history):
    idx = SimilarityIndex(history, "1x2")
    as_of = pd.Timestamp("2016-03-01")
    vec = np.array([0.5, 0.27, 0.23])
    res = idx.query(vec, as_of, k=100, metric="manhattan")
    assert len(res.indices) == 100
    assert (idx.dates[res.indices] < np.datetime64(as_of)).all()
    # same-day matches are excluded too
    same_day = idx.df[idx.df["date"] == as_of]
    assert not set(same_day.index) & set(res.indices)


def test_query_is_sorted_and_same_league_scope(history):
    idx = SimilarityIndex(history, "1x2")
    vec = np.array([0.5, 0.27, 0.23])
    res = idx.query(vec, pd.Timestamp("2020-01-01"), k=50, metric="euclidean", scope="same_league", league="E0")
    assert (np.diff(res.distances) >= 0).all()
    assert (idx.leagues[res.indices] == "E0").all()
    assert res.similarity.max() <= 100.0


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "cosine", "mahalanobis"])
def test_all_metrics_run(history, metric):
    idx = SimilarityIndex(history, "1x2")
    res = idx.query(np.array([0.4, 0.3, 0.3]), pd.Timestamp("2021-01-01"), k=25, metric=metric)
    assert len(res.indices) == 25
    assert np.isfinite(res.distances).all()


def test_empty_pool_before_first_match(history):
    idx = SimilarityIndex(history, "1x2")
    res = idx.query(np.array([0.4, 0.3, 0.3]), pd.Timestamp("2000-01-01"), k=25)
    assert len(res.indices) == 0 and res.n_candidates == 0


def test_min_similarity_floor(history):
    idx = SimilarityIndex(history, "1x2")
    res = idx.query(np.array([0.5, 0.27, 0.23]), pd.Timestamp("2021-01-01"), k=500, min_similarity=98.0)
    assert (res.similarity >= 98.0).all()


def test_query_batch_matches_single_queries(history):
    idx = SimilarityIndex(history, "1x2")
    vecs = np.array([[0.5, 0.27, 0.23], [0.3, 0.3, 0.4]])
    as_of = pd.Timestamp("2019-06-01")
    b_idx, b_d, b_s = idx.query_batch(vecs, as_of, 20, "manhattan")
    for i in range(2):
        single = idx.query(vecs[i], as_of, k=20, metric="manhattan")
        assert np.allclose(np.sort(b_d[i]), np.sort(single.distances))


def test_tolerance_matching_counts_grow_with_tolerance(history):
    idx = SimilarityIndex(history, "1x2")
    row = idx.df.iloc[2000]
    odds = row[["cons_h", "cons_d", "cons_a"]].to_numpy(dtype=float)
    probs = row[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    res = idx.tolerance_match(odds, probs, row["date"], [0.01, 0.02, 0.05])
    counts = [len(res["probs"][t]) for t in (0.01, 0.02, 0.05)]
    assert counts == sorted(counts)
    assert all(idx.dates[i] < np.datetime64(row["date"]) for i in res["probs"][0.05])
