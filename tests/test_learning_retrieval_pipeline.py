from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from state_bench.agents.state_bench import RETRIEVE_LEARNINGS_TOOL_NAME, StateBenchAgent
from state_bench.client import PooledLLMClient, build_llm_client
from state_bench.domain import get_domain_config
from state_bench.env_loader import load_task_environment
from state_bench.orchestrator import run_task
from state_bench.paths import domain_tasks_dir
from state_bench.schemas import TaskDefinition

REAL_DOMAIN_NAME = "travel"
REAL_TASK_ID = "101-challenge_mixed_strategy_shared_budget"


def _make_response(response_id: str, output_items: list, output_text: str = "") -> MagicMock:
    response = MagicMock()
    response.id = response_id
    response.output = output_items
    response.output_text = output_text
    response.status = "completed"
    response.incomplete_details = None
    response.usage = None
    return response


def _make_text_item(text: str) -> MagicMock:
    item = MagicMock()
    item.type = "message"
    item.text = text
    return item


def _make_function_call(call_id: str, name: str, arguments: str) -> MagicMock:
    item = MagicMock()
    item.type = "function_call"
    item.call_id = call_id
    item.name = name
    item.arguments = arguments
    return item


class DummyLearningAgent(StateBenchAgent):
    learnings_path = None

    @staticmethod
    def build_learnings(trajectories_dir, output_path=None):
        learnings = ["No learnings present"]
        if output_path is not None:
            from pathlib import Path

            Path(output_path).write_text(json.dumps(learnings) + "\n")
        return learnings

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        if self.learnings_path is None:
            return []
        from pathlib import Path

        return json.loads(Path(self.learnings_path).read_text())[:top_k]


def _load_real_task_and_env():
    domain = get_domain_config(REAL_DOMAIN_NAME)
    task = TaskDefinition.load(domain_tasks_dir(REAL_DOMAIN_NAME) / f"{REAL_TASK_ID}.json")
    env_data, _env_path = load_task_environment(domain, task)
    return domain, task, env_data


def test_state_bench_agent_learning_retrieval_pipeline_end_to_end(tmp_path):
    domain, task, env_data = _load_real_task_and_env()
    train_dir = tmp_path / "train_trajectories"
    train_dir.mkdir()
    (train_dir / f"{REAL_TASK_ID}.json").write_text('{"conversation": []}\n')
    learnings_path = tmp_path / "learnings.json"

    learnings = DummyLearningAgent.build_learnings(train_dir, learnings_path)
    DummyLearningAgent.learnings_path = learnings_path

    retrieve_call = _make_function_call(
        "call_learnings",
        RETRIEVE_LEARNINGS_TOOL_NAME,
        json.dumps({"query": "dummy task", "top_k": 3}),
    )
    final_text = _make_text_item("Done.")
    mock_complete = MagicMock(
        side_effect=[
            _make_response("resp_001", [retrieve_call]),
            _make_response("resp_002", [final_text], "Done."),
        ]
    )

    pinned_client = MagicMock()
    pinned_client.complete_with_tools = mock_complete
    pinned_ctx = MagicMock()
    pinned_ctx.__enter__ = MagicMock(return_value=pinned_client)
    pinned_ctx.__exit__ = MagicMock(return_value=False)
    client = MagicMock(spec=PooledLLMClient)
    client.pinned.return_value = pinned_ctx

    simulator = MagicMock()
    simulator.respond.return_value = "[TASK_DONE]"

    with patch("state_bench.orchestrator.UserSimulator", return_value=simulator):
        trajectory = run_task(
            task=task,
            env_data=env_data,
            user_id=task.user_id,
            client=client,
            simulator_client=MagicMock(),
            domain=domain,
            agent_class=DummyLearningAgent,
            retrieve_learnings_top_k=3,
        )

    assert learnings == ["No learnings present"]
    assert json.loads(learnings_path.read_text()) == ["No learnings present"]
    assert trajectory.conversation[1]["content"] == "Done."
    assert trajectory.conversation[1]["tool_calls"] == [
        {
            "name": RETRIEVE_LEARNINGS_TOOL_NAME,
            "arguments": {"query": "dummy task", "top_k": 3},
            "result": {"learnings": ["No learnings present"]},
        }
    ]
    first_call = mock_complete.call_args_list[0].kwargs
    assert RETRIEVE_LEARNINGS_TOOL_NAME in {tool["name"] for tool in first_call["tools"]}
    assert "Procedural Learning Retrieval" in first_call["instructions"]


@pytest.mark.skipif(
    os.environ.get("STATE_BENCH_RUN_LIVE_LEARNING_RETRIEVAL_TEST") != "1",
    reason="Set STATE_BENCH_RUN_LIVE_LEARNING_RETRIEVAL_TEST=1 to run the live LLM retrieval test.",
)
def test_live_agent_calls_retrieve_learnings_tool(tmp_path):
    domain, task, env_data = _load_real_task_and_env()
    train_dir = tmp_path / "train_trajectories"
    train_dir.mkdir()
    (train_dir / f"{REAL_TASK_ID}.json").write_text('{"conversation": []}\n')
    learnings_path = tmp_path / "learnings.json"
    DummyLearningAgent.build_learnings(train_dir, learnings_path)
    DummyLearningAgent.learnings_path = learnings_path

    client = build_llm_client(
        provider=os.environ.get("STATE_BENCH_AGENT_PROVIDER", "azure_openai"),
        api_key_var=os.environ.get("STATE_BENCH_AGENT_API_KEY_VAR", "STATE_BENCH_AGENT_API_KEY"),
    )

    trajectory = run_task(
        task=task,
        env_data=env_data,
        user_id=task.user_id,
        client=client,
        simulator_client=client,
        domain=domain,
        agent_class=DummyLearningAgent,
        retrieve_learnings_top_k=3,
    )

    tool_calls = [tool_call for message in trajectory.conversation for tool_call in (message.get("tool_calls") or [])]
    retrieve_calls = [tool_call for tool_call in tool_calls if tool_call["name"] == RETRIEVE_LEARNINGS_TOOL_NAME]

    print("retrieve_learnings calls:")
    for call in retrieve_calls:
        print(json.dumps(call["arguments"], sort_keys=True))

    assert retrieve_calls, "Live agent did not call retrieve_learnings"
    assert retrieve_calls[0]["result"] == {"learnings": ["No learnings present"]}
