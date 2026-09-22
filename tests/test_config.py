import os

import pytest

from src.config import _apply_env_overrides


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "EARNINGS_GUARD_ENABLED",
        "MACRO_OVERLAY_ENABLED",
        "NEWS_SENTIMENT_ENABLED",
        "SAVE_TO_S3",
    ):
        monkeypatch.delenv(var, raising=False)


def test_unset_env_leaves_config_value():
    cfg = {"features": {"news_sentiment": True}}
    _apply_env_overrides(cfg)
    assert cfg["features"]["news_sentiment"] is True


def test_env_true_enables(monkeypatch):
    monkeypatch.setenv("NEWS_SENTIMENT_ENABLED", "true")
    cfg = {"features": {"news_sentiment": False}}
    _apply_env_overrides(cfg)
    assert cfg["features"]["news_sentiment"] is True


def test_env_false_disables(monkeypatch):
    monkeypatch.setenv("MACRO_OVERLAY_ENABLED", "false")
    cfg = {"features": {"macro_overlay": True}}
    _apply_env_overrides(cfg)
    assert cfg["features"]["macro_overlay"] is False


def test_overlay_creates_features_block_if_missing(monkeypatch):
    monkeypatch.setenv("EARNINGS_GUARD_ENABLED", "true")
    cfg = {}
    _apply_env_overrides(cfg)
    assert cfg["features"]["earnings_guard"] is True


def test_save_to_s3_can_be_enabled_by_env(monkeypatch):
    """The Lambda ships config.example.yaml, so archiving has to be env-driven."""
    monkeypatch.setenv("SAVE_TO_S3", "true")
    cfg = {"report": {"save_to_s3": False}}
    _apply_env_overrides(cfg)
    assert cfg["report"]["save_to_s3"] is True


def test_save_to_s3_unset_leaves_config_value():
    cfg = {"report": {"save_to_s3": True}}
    _apply_env_overrides(cfg)
    assert cfg["report"]["save_to_s3"] is True
