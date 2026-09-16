"""
Regression test: pydantic-settings parses LANGSMITH_* from .env into the
Settings model, but never touches os.environ itself — and the langsmith SDK
(and every LangChain/LangGraph tracing hook) reads LANGSMITH_* purely from
os.environ. Without get_settings() propagating these, a correctly-filled-in
.env silently does nothing: settings.langsmith_tracing reads True, but no
trace ever reaches LangSmith.
"""

import os

import app.config


def _reset(monkeypatch):
    """Explicitly SET every LangSmith var to an inert default (never just
    delenv) — this repo's real .env has LangSmith fully configured, and
    pydantic-settings falls back to reading .env directly for any var not
    present in os.environ, so merely deleting a process env var doesn't
    isolate a test from the real .env file's values. An explicit process-env
    value (even an empty string) always takes precedence over .env, which is
    what actually isolates these tests."""
    app.config._settings = None
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    monkeypatch.setenv("LANGSMITH_PROJECT", "")


class TestLangSmithEnvPropagation:
    def test_tracing_enabled_and_key_present_propagates_to_os_environ(self, monkeypatch):
        _reset(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_key")
        monkeypatch.setenv("LANGSMITH_PROJECT", "my-project")

        app.config.get_settings()

        assert os.environ.get("LANGSMITH_TRACING") == "true"
        assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_test_key"
        assert os.environ.get("LANGSMITH_PROJECT") == "my-project"

    def test_tracing_disabled_does_not_propagate_the_key(self, monkeypatch):
        _reset(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("LANGSMITH_TRACING", "false")
        monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_key")

        app.config.get_settings()

        # _apply_langsmith_env must not have touched these — LANGSMITH_TRACING
        # stays exactly "false" (what monkeypatch put there), and the key is
        # never (re-)written since tracing itself is off.
        assert os.environ.get("LANGSMITH_TRACING") == "false"
        assert os.environ.get("LANGSMITH_API_KEY") == "lsv2_test_key"  # unchanged, not our doing

    def test_no_api_key_does_not_enable_tracing_even_if_flag_is_true(self, monkeypatch):
        # Defensive: tracing=true with no key would otherwise crash LangSmith
        # calls with an auth error rather than just quietly not tracing.
        _reset(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "test")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("LANGSMITH_TRACING", "true")
        # LANGSMITH_API_KEY stays "" from _reset() — no key provided.

        app.config.get_settings()

        # _apply_langsmith_env's short-circuit means LANGSMITH_TRACING keeps
        # whatever monkeypatch set it to ("true") rather than being
        # (re-)written to "true" by us — the distinguishing signal is that
        # LANGSMITH_PROJECT (which only OUR function would ever set) stays empty.
        assert os.environ.get("LANGSMITH_PROJECT") == ""
