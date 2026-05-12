from unittest.mock import patch

import pytest

from state_bench.client import (
    LLMClient,
    PooledLLMClient,
    build_llm_client,
    build_locked_judge_client,
    build_user_sim_client,
)


def _clear_numbered_azure_env(monkeypatch):
    for name in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_DEPLOYMENTS",
        "STATE_BENCH_AGENT_ENDPOINT",
        "STATE_BENCH_AGENT_DEPLOYMENTS",
        "STATE_BENCH_EVAL_ENDPOINT",
        "STATE_BENCH_EVAL_DEPLOYMENTS",
    ):
        monkeypatch.delenv(name, raising=False)
    for index in range(1, 11):
        monkeypatch.delenv(f"AZURE_OPENAI_ENDPOINT_{index}", raising=False)
        monkeypatch.delenv(f"AZURE_OPENAI_DEPLOYMENTS_{index}", raising=False)
        monkeypatch.delenv(f"STATE_BENCH_AGENT_ENDPOINT_{index}", raising=False)
        monkeypatch.delenv(f"STATE_BENCH_AGENT_DEPLOYMENTS_{index}", raising=False)
        monkeypatch.delenv(f"STATE_BENCH_EVAL_ENDPOINT_{index}", raising=False)
        monkeypatch.delenv(f"STATE_BENCH_EVAL_DEPLOYMENTS_{index}", raising=False)


def test_azure_openai_client_prefers_api_key_for_external_users(monkeypatch):
    monkeypatch.setenv("STATE_BENCH_TEST_API_KEY", "test-key")

    with patch("state_bench.client.AzureOpenAI") as azure_openai:
        LLMClient(
            endpoint="https://example.openai.azure.com",
            deployment="gpt-5.1",
            provider="azure_openai",
            api_key_var="STATE_BENCH_TEST_API_KEY",
        )

    azure_openai.assert_called_once_with(
        azure_endpoint="https://example.openai.azure.com",
        api_key="test-key",
        api_version="2025-03-01-preview",
    )


def test_build_llm_client_returns_single_client_for_one_agent_deployment(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_AGENT_ENDPOINT", "https://one.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_AGENT_DEPLOYMENTS", "gpt-5.1")
    monkeypatch.setenv("STATE_BENCH_AGENT_API_KEY", "test-key")

    with patch("state_bench.client.AzureOpenAI"):
        client = build_llm_client(api_key_var="STATE_BENCH_AGENT_API_KEY")

    assert isinstance(client, LLMClient)
    assert client.deployments == ["gpt-5.1"]


def test_build_llm_client_returns_pool_for_multiple_agent_deployments(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_AGENT_ENDPOINT", "https://one.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_AGENT_DEPLOYMENTS", "gpt-5.1-a,gpt-5.1-b")
    monkeypatch.setenv("STATE_BENCH_AGENT_API_KEY", "test-key")

    with patch("state_bench.client.AzureOpenAI"):
        client = build_llm_client(api_key_var="STATE_BENCH_AGENT_API_KEY")

    assert isinstance(client, PooledLLMClient)
    assert client.deployments == ["gpt-5.1-a", "gpt-5.1-b"]


def test_locked_eval_clients_share_state_bench_eval_config(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_EVAL_ENDPOINT", "https://eval.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_EVAL_DEPLOYMENTS", "gpt-5.1-eval")
    monkeypatch.setenv("STATE_BENCH_EVAL_API_KEY", "test-key")

    with patch("state_bench.client.AzureOpenAI") as azure_openai:
        user_sim_client = build_user_sim_client(api_version="2025-03-01-preview")
        judge_client = build_locked_judge_client(api_version="2025-03-01-preview")

    assert isinstance(user_sim_client, LLMClient)
    assert isinstance(judge_client, LLMClient)
    assert user_sim_client.deployments == ["gpt-5.1-eval"]
    assert judge_client.deployments == ["gpt-5.1-eval"]
    assert azure_openai.call_count == 2


def test_openai_client_uses_openai_api_key_and_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("STATE_BENCH_AGENT_MODEL", "gpt-4.1")

    with patch("state_bench.client.OpenAI") as openai_client:
        client = build_llm_client(provider="openai")

    assert isinstance(client, LLMClient)
    assert client.deployments == ["gpt-4.1"]
    openai_client.assert_called_once_with(api_key="test-key")


def test_openai_client_rejects_third_party_base_url(monkeypatch):
    monkeypatch.setenv("STATE_BENCH_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("STATE_BENCH_AGENT_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("STATE_BENCH_AGENT_MODEL", "model-a")

    with pytest.raises(ValueError, match="Third-party OpenAI-compatible base URLs are not supported"):
        build_llm_client(provider="openai")
