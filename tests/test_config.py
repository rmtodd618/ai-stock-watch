import os

import pytest

from src.config import _apply_feature_env_overrides


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EARNINGS_GUARD_ENABLED", "MACRO_OVERLAY_ENABLED", "NEWS_SENTIMENT_ENABLED"):
        monkeypatch.delenv(var, raising=False)


def test_unset_env_leaves_config_value():
    cfg = {"features": {"news_sentiment": True}}
    _apply_feature_env_overrides(cfg)
    assert cfg["features"]["news_sentiment"] is True


def test_env_true_enables(monkeypatch):
    monkeypatch.setenv("NEWS_SENTIMENT_ENABLED", "true")
    cfg = {"features": {"news_sentiment": False}}
    _apply_feature_env_overrides(cfg)
    assert cfg["features"]["news_sentiment"] is True


def test_env_false_disables(monkeypatch):
    monkeypatch.setenv("MACRO_OVERLAY_ENABLED", "false")
    cfg = {"features": {"macro_overlay": True}}
    _apply_feature_env_overrides(cfg)
    assert cfg["features"]["macro_overlay"] is False


def test_overlay_creates_features_block_if_missing(monkeypatch):
    monkeypatch.setenv("EARNINGS_GUARD_ENABLED", "true")
    cfg = {}
    _apply_feature_env_overrides(cfg)
    assert cfg["features"]["earnings_guard"] is True
