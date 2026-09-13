from src.models.signal import classify_signal


def _sig(edge, n_eff=300, outside=True, sim=96.0, ok=True):
    return classify_signal({"home": edge, "draw": -edge / 2, "away": -edge / 2}, n_eff, {"home": outside, "draw": False, "away": False}, sim, ok)


def test_low_sample_dominates():
    s = _sig(9.0, n_eff=40)
    assert s.label == "LOW SAMPLE" and s.outcome == "home"


def test_strong_requires_all_gates():
    assert _sig(6.0).label == "STRONG HISTORICAL DEVIATION"
    assert _sig(6.0, ok=False).label == "MODERATE HISTORICAL DEVIATION"
    assert _sig(6.0, sim=92.0).label == "MODERATE HISTORICAL DEVIATION"
    assert _sig(6.0, outside=False).label == "NEUTRAL"


def test_moderate_and_neutral():
    assert _sig(3.5).label == "MODERATE HISTORICAL DEVIATION"
    assert _sig(1.0).label == "NEUTRAL"


def test_reasons_are_transparent():
    s = _sig(6.0, ok=False)
    text = s.as_text()
    assert "HOME +6.0 pp" in text and "backtest: no improvement" in text and "downgraded" in text


def test_no_analogues():
    s = classify_signal({"home": float("nan")}, 0, {}, float("nan"), True)
    assert s.label == "LOW SAMPLE"
