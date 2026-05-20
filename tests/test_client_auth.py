import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from state_bench.client import (
    BaseLLMClient,
    LLMClient,
    PooledLLMClient,
    build_llm_client,
    build_locked_judge_client,
    build_user_sim_client,
)


class NoArgClient(BaseLLMClient):
    pass


def test_base_llm_client_defaults():
    client = NoArgClient.from_env()

    assert isinstance(client, NoArgClient)
    assert client.provider_name == "NoArgClient"
    assert client.model_name is None


def test_importing_client_does_not_load_dotenv(tmp_path):
    (tmp_path / ".env").write_text('STATE_BENCH_IMPORT_DOTENV_SENTINEL="loaded"\n')
    env = os.environ.copy()
    env.pop("STATE_BENCH_IMPORT_DOTENV_SENTINEL", None)
    env["PYTHONPATH"] = os.getcwd()

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import state_bench.client; print(os.environ.get('STATE_BENCH_IMPORT_DOTENV_SENTINEL'))",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert proc.stdout.strip() == "None"


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


def test_azure_openai_client_uses_openai_v1_base_url(monkeypatch):
    monkeypatch.setenv("STATE_BENCH_TEST_API_KEY", "test-key")

    with patch("state_bench.client.OpenAI") as openai_client:
        LLMClient(
            endpoint="https://example.openai.azure.com",
            deployment="gpt-5.1",
            provider="azure_openai",
            api_key_var="STATE_BENCH_TEST_API_KEY",
        )

    openai_client.assert_called_once_with(
        base_url="https://example.openai.azure.com/openai/v1/",
        api_key="test-key",
    )


def test_build_llm_client_returns_single_client_for_one_agent_deployment(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_AGENT_ENDPOINT", "https://one.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_AGENT_DEPLOYMENTS", "gpt-5.1")
    monkeypatch.setenv("STATE_BENCH_AGENT_API_KEY", "test-key")

    with patch("state_bench.client.OpenAI"):
        client = build_llm_client(api_key_var="STATE_BENCH_AGENT_API_KEY")

    assert isinstance(client, BaseLLMClient)
    assert isinstance(client, LLMClient)
    assert client.deployments == ["gpt-5.1"]


def test_build_llm_client_returns_pool_for_multiple_agent_deployments(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_AGENT_ENDPOINT", "https://one.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_AGENT_DEPLOYMENTS", "gpt-5.1-a,gpt-5.1-b")
    monkeypatch.setenv("STATE_BENCH_AGENT_API_KEY", "test-key")

    with patch("state_bench.client.OpenAI"):
        client = build_llm_client(api_key_var="STATE_BENCH_AGENT_API_KEY")

    assert isinstance(client, BaseLLMClient)
    assert isinstance(client, PooledLLMClient)
    assert client.deployments == ["gpt-5.1-a", "gpt-5.1-b"]


def test_locked_eval_clients_share_state_bench_eval_config(monkeypatch):
    _clear_numbered_azure_env(monkeypatch)
    monkeypatch.setenv("STATE_BENCH_EVAL_ENDPOINT", "https://eval.openai.azure.com")
    monkeypatch.setenv("STATE_BENCH_EVAL_DEPLOYMENTS", "gpt-5.1-eval")
    monkeypatch.setenv("STATE_BENCH_EVAL_API_KEY", "test-key")

    with patch("state_bench.client.OpenAI") as openai_client:
        user_sim_client = build_user_sim_client()
        judge_client = build_locked_judge_client()

    assert isinstance(user_sim_client, LLMClient)
    assert isinstance(judge_client, LLMClient)
    assert user_sim_client.deployments == ["gpt-5.1-eval"]
    assert judge_client.deployments == ["gpt-5.1-eval"]
    assert openai_client.call_count == 2


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


def test_complete_with_tools_omits_temperature_when_reasoning_set(monkeypatch):
    """Bug-fix regression: GPT-5.1 reasoning models reject `temperature` + `reasoning`."""
    from unittest.mock import MagicMock

    from state_bench.client import LLMClient

    inner = MagicMock()
    inner.responses.create.return_value = MagicMock(
        output=[], output_text="", status="completed", incomplete_details=None
    )
    client = LLMClient.__new__(LLMClient)
    client._client = inner
    client.deployment = "gpt-5.1"
    client.endpoint = "https://example/"
    client.api_version = "2025-03-01-preview"

    client.complete_with_tools(instructions="x", input=[], tools=[], reasoning_effort="high")
    _, kwargs = inner.responses.create.call_args
    assert "temperature" not in kwargs
    assert kwargs["reasoning"] == {"effort": "high"}

    inner.responses.create.reset_mock()
    client.complete_with_tools(instructions="x", input=[], tools=[])
    _, kwargs = inner.responses.create.call_args
    assert kwargs.get("temperature") == 0
    assert "reasoning" not in kwargs
