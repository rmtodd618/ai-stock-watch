import pytest

import src.handler as handler

NEWS_CFG = {
    "api_key_ssm_param_env_var": "ANTHROPIC_API_KEY_SSM_PARAM",
    "api_key_env_var": "ANTHROPIC_API_KEY",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY_SSM_PARAM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_ssm_is_preferred(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY_SSM_PARAM", "/ai-stock-watch/key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")  # present but should be ignored
    monkeypatch.setattr(handler.ssm, "get_secure_parameter", lambda name, region=None: "ssm-key")
    assert handler._resolve_anthropic_key(NEWS_CFG, None) == "ssm-key"


def test_falls_back_to_env_when_ssm_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY_SSM_PARAM", "/ai-stock-watch/key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    monkeypatch.setattr(handler.ssm, "get_secure_parameter", lambda name, region=None: None)
    assert handler._resolve_anthropic_key(NEWS_CFG, None) == "env-key"


def test_no_ssm_param_does_not_call_ssm(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

    def _boom(*args, **kwargs):
        raise AssertionError("SSM should not be called when no param name is set")

    monkeypatch.setattr(handler.ssm, "get_secure_parameter", _boom)
    assert handler._resolve_anthropic_key(NEWS_CFG, None) == "env-key"
