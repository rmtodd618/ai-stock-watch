from src.scoring.composite import composite_score
from src.scoring.sentiment import sentiment_tilt

CAP = 10


def test_none_result_no_tilt():
    tilt, summary = sentiment_tilt(None, CAP)
    assert tilt == 0.0
    assert summary is None


def test_material_catalyst_gets_full_weight():
    tilt, _ = sentiment_tilt(
        {"sentiment": 1.0, "material_catalyst": True, "summary": "x"}, CAP
    )
    assert tilt == CAP


def test_ambient_sentiment_dampened():
    tilt, _ = sentiment_tilt(
        {"sentiment": 1.0, "material_catalyst": False, "summary": "x"}, CAP
    )
    assert tilt == 6.0  # 1.0 * 10 * 0.6


def test_negative_and_clamped():
    tilt, _ = sentiment_tilt(
        {"sentiment": -3.0, "material_catalyst": True, "summary": "x"}, CAP
    )
    assert tilt == -CAP  # clamped from out-of-range input


def test_composite_clamps_to_range():
    assert composite_score(95, 8, 10) == 100.0
    assert composite_score(5, -8, -10) == 0.0
    assert composite_score(70, 8, -3) == 75.0
