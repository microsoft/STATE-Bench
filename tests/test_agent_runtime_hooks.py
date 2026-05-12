from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from state_bench.agents.base import Agent, AgentPricing, AgentRuntimeContext, AgentTurnResponse
from state_bench.orchestrator import run_task
from state_bench.scripts.run_batch import _build_agent_pricing as _build_batch_agent_pricing
from state_bench.scripts.run_batch import _build_run_dirs, _parse_task_ids, _resolve_task_files


def test_run_batch_builds_run_subdirectories_for_single_train_run(tmp_path):
    base_output = tmp_path / "train_trajectories"

    assert _build_run_dirs(base_output, [1]) == {1: base_output / "run1"}
    assert _build_run_dirs(base_output, [3]) == {3: base_output / "run3"}
    assert _build_run_dirs(base_output, [1, 2]) == {
        1: base_output / "run1",
        2: base_output / "run2",
    }


def test_run_batch_resolves_requested_task_files(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "task-a.json").write_text("{}")
    (tasks_dir / "task-b.json").write_text("{}")

    assert _parse_task_ids(" task-a,task-b ,, ") == ["task-a", "task-b"]
    assert _resolve_task_files(tasks_dir, ["task-a", "task-b"]) == [
        tasks_dir / "task-a.json",
        tasks_dir / "task-b.json",
    ]


def test_run_batch_rejects_missing_requested_task_ids(tmp_path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "task-a.json").write_text("{}")

    with pytest.raises(ValueError, match=r"task ID\(s\) not found: missing-task"):
        _resolve_task_files(tasks_dir, ["task-a", "missing-task"])


def _runtime_context_with_pricing() -> AgentRuntimeContext:
    return AgentRuntimeContext(
        task_id="task-1",
        user_id="user_001",
        domain="travel",
        now="2026-06-15T10:00:00",
        agent_pricing=AgentPricing(
            model_name="test-model",
            input_cost_per_1m_tokens=1.25,
            output_cost_per_1m_tokens=10.0,
            cached_input_cost_per_1m_tokens=0.13,
        ),
    )


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


class HarnessToolAgent(Agent):
    def __init__(self, runtime_context=None):
        super().__init__(runtime_context=runtime_context)
        self.calls = 0

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        self.calls += 1
        if self.calls == 1:
            return AgentTurnResponse(
                text="Checking that now.",
                tool_calls=[{"name": "lookup", "arguments": {"id": "BK-1"}}],
            )
        return AgentTurnResponse(text="Done.")


class BadToolAgent(Agent):
    def generate_next_turn(self, *, system_prompt, conversation, tools):
        return {"text": "bad", "tool_calls": [{"name": "delete_everything", "arguments": {}}]}


class MemoryToolOnlyAgent(Agent):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def memory_tool_schemas(self):
        return [
            {
                "type": "function",
                "name": "retrieve_memories",
                "description": "Retrieve read-only memories.",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
            }
        ]

    def memory_tool_handlers(self):
        return {"retrieve_memories": lambda args: {"memories": [f"memory for {args['query']}"]}}

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        self.calls += 1
        if self.calls == 1:
            return {
                "text": "Looking up memory.",
                "tool_calls": [{"name": "retrieve_memories", "arguments": {"query": "refund"}}],
            }
        return {"text": "I found the relevant memory."}


class DummyEnvData:
    def deep_copy(self):
        return self


class DummyEnv:
    def __init__(self, env_data, now):
        self.tool_handlers = {"lookup": lambda args: {"id": args["id"], "status": "ok"}}

    def get_full_snapshot(self):
        return {}


class DummyTask:
    task_id = "task-1"
    task_summary = "Task summary"
    user_simulator = type("Sim", (), {"user_sim_context": "User simulator context"})()
    user_id = "user_001"
    now = "2026-06-15T10:00:00"
    opening_message = "hello"
    state_requirements = []
    task_requirements = []
    tags = {}


class DummyDomain:
    name = "travel"
    tool_schemas = []
    agent_system_prompt = "You are an agent for {user_id} at {now}."
    environment_class = DummyEnv
    max_agent_turns = 1
    check_termination = None

    @staticmethod
    def build_simulator_prompt(task, env_data, user_id):
        return "sim prompt"


def test_custom_agent_can_use_own_client_and_harness_executes_tools():
    simulator = MagicMock()
    simulator.respond.return_value = "[TASK_DONE]"

    from unittest.mock import patch

    agent = HarnessToolAgent(
        runtime_context=AgentRuntimeContext(
            task_id="task-1", user_id="user_001", domain="travel", now="2026-06-15T10:00:00"
        )
    )
    with patch("state_bench.orchestrator.UserSimulator", return_value=simulator):
        trajectory = run_task(
            task=DummyTask(),
            env_data=DummyEnvData(),
            user_id="user_001",
            client=None,
            simulator_client=MagicMock(),
            domain=DummyDomain(),
            agent=agent,
            env=DummyEnv(DummyEnvData(), now="2026-06-15T10:00:00"),
        )

    assistant_turn = trajectory.conversation[1]
    assert assistant_turn["content"] == "Done."
    assert assistant_turn["tool_calls"] == [
        {"name": "lookup", "arguments": {"id": "BK-1"}, "result": {"id": "BK-1", "status": "ok"}}
    ]
    assert trajectory.efficiency.tool_calls == 1


def test_harness_rejects_disallowed_custom_tool():
    from unittest.mock import patch

    with patch("state_bench.orchestrator.UserSimulator", return_value=MagicMock()):
        with pytest.raises(ValueError, match="disallowed tool"):
            run_task(
                task=DummyTask(),
                env_data=DummyEnvData(),
                user_id="user_001",
                client=None,
                simulator_client=MagicMock(),
                domain=DummyDomain(),
                agent=BadToolAgent(),
                env=DummyEnv(DummyEnvData(), now="2026-06-15T10:00:00"),
            )


def test_harness_allows_declared_memory_retrieval_tool():
    from unittest.mock import patch

    with patch("state_bench.orchestrator.UserSimulator", return_value=MagicMock()):
        trajectory = run_task(
            task=DummyTask(),
            env_data=DummyEnvData(),
            user_id="user_001",
            client=None,
            simulator_client=MagicMock(),
            domain=DummyDomain(),
            agent=MemoryToolOnlyAgent(),
            env=DummyEnv(DummyEnvData(), now="2026-06-15T10:00:00"),
        )

    tool_calls = trajectory.conversation[1]["tool_calls"]
    assert tool_calls == [
        {
            "name": "retrieve_memories",
            "arguments": {"query": "refund"},
            "result": {"memories": ["memory for refund"]},
        }
    ]


def test_agent_pricing_defaults_to_protocol_model_config():
    args = type(
        "Args",
        (),
        {
            "agent_model_name": None,
            "agent_input_cost_per_1m": None,
            "agent_output_cost_per_1m": None,
            "agent_cached_input_cost_per_1m": None,
        },
    )()

    pricing = _build_batch_agent_pricing(args, "gpt-5.1")

    assert pricing.model_name == "gpt-5.1"
    assert pricing.input_cost_per_1m_tokens == 1.25
    assert pricing.output_cost_per_1m_tokens == 10.0
    assert pricing.cached_input_cost_per_1m_tokens == 0.13
    assert pricing.source == "pricing_config:pricing.yaml"


def test_agent_pricing_args_require_model_input_and_output_together():
    args = type(
        "Args",
        (),
        {
            "agent_model_name": "test-model",
            "agent_input_cost_per_1m": 1.0,
            "agent_output_cost_per_1m": None,
            "agent_cached_input_cost_per_1m": None,
        },
    )()

    with pytest.raises(ValueError, match="--agent-output-cost-per-1m"):
        _build_batch_agent_pricing(args)
