from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from state_bench.agents.base import AgentPricing, AgentRuntimeContext, AgentTurnResponse, BaseAgent
from state_bench.agents.loader import load_root_agent_class, load_root_client_class
from state_bench.client import BaseLLMClient, LLMClient
from state_bench.orchestrator import run_task
from state_bench.scripts.run_batch import _build_agent_pricing as _build_batch_agent_pricing
from state_bench.scripts.run_batch import _build_run_dirs, _parse_task_ids, _resolve_task_files
from state_bench.scripts.run_task import _build_agent_model_metadata, _validate_agent_client_args


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


class HarnessToolAgent(BaseAgent):
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


class BadToolAgent(BaseAgent):
    def generate_next_turn(self, *, system_prompt, conversation, tools):
        return {"text": "bad", "tool_calls": [{"name": "delete_everything", "arguments": {}}]}


class MemoryToolOnlyAgent(BaseAgent):
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


def test_state_bench_subclass_loaded_with_built_in_client_for_retrieval(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "memory_agent.py").write_text(
        "from state_bench.agents.state_bench import StateBenchAgent\n"
        "class MemoryAgent(StateBenchAgent):\n"
        "    def retrieve_learnings(self, query, top_k=3):\n"
        "        return [f'learning for {query}'][:top_k]\n"
    )

    agent_class = load_root_agent_class("MemoryAgent", root=tmp_path)
    client = MagicMock(spec=LLMClient)
    client.complete_with_tools.return_value = type(
        "Response",
        (),
        {
            "id": "resp-1",
            "output": [],
            "output_text": "done",
            "usage": None,
        },
    )()

    from unittest.mock import patch

    simulator = MagicMock()
    simulator.respond.return_value = "[TASK_DONE]"
    with patch("state_bench.orchestrator.UserSimulator", return_value=simulator):
        trajectory = run_task(
            task=DummyTask(),
            env_data=DummyEnvData(),
            user_id="user_001",
            client=client,
            simulator_client=MagicMock(),
            domain=DummyDomain(),
            agent_class=agent_class,
        )

    assert trajectory.conversation[1]["content"] == "done"
    _, kwargs = client.complete_with_tools.call_args
    assert any(tool["name"] == "retrieve_learnings" for tool in kwargs["tools"])
    assert "retrieve_learnings" in kwargs["instructions"]


def test_custom_agent_and_client_loaded_from_root_extensions(tmp_path):
    agents_dir = tmp_path / "agents"
    clients_dir = tmp_path / "clients"
    agents_dir.mkdir()
    clients_dir.mkdir()
    (clients_dir / "custom_client.py").write_text(
        "from state_bench.client import BaseLLMClient\n"
        "class CustomClient(BaseLLMClient):\n"
        "    @classmethod\n"
        "    def from_env(cls):\n"
        "        client = cls()\n"
        "        client.constructed_from_env = True\n"
        "        return client\n"
        "    def generate(self, **kwargs):\n"
        "        return 'custom client response'\n"
    )
    (agents_dir / "custom_agent.py").write_text(
        "from state_bench.agents.base import BaseAgent, AgentTurnResponse\n"
        "class CustomAgent(BaseAgent):\n"
        "    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):\n"
        "        super().__init__(runtime_context=runtime_context)\n"
        "        self.client = client\n"
        "    def generate_next_turn(self, *, system_prompt, conversation, tools):\n"
        "        assert self.client.constructed_from_env is True\n"
        "        return AgentTurnResponse(text=self.client.generate())\n"
    )

    agent_class = load_root_agent_class("CustomAgent", root=tmp_path)
    client_class = load_root_client_class("CustomClient", root=tmp_path)
    client = client_class.from_env()

    assert isinstance(client, BaseLLMClient)

    from unittest.mock import patch

    simulator = MagicMock()
    simulator.respond.return_value = "[TASK_DONE]"
    with patch("state_bench.orchestrator.UserSimulator", return_value=simulator):
        trajectory = run_task(
            task=DummyTask(),
            env_data=DummyEnvData(),
            user_id="user_001",
            client=client,
            simulator_client=MagicMock(),
            domain=DummyDomain(),
            agent_class=agent_class,
        )

    assert trajectory.conversation[1]["content"] == "custom client response"


def test_agent_pricing_uses_agent_model_name_for_checked_in_pricing():
    args = type(
        "Args",
        (),
        {
            "agent_model_name": "gpt-5.1",
            "agent_model_reasoning_level": None,
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


def test_agent_model_metadata_requires_model_name():
    args = type("Args", (), {"agent_model_name": "", "agent_model_reasoning_level": None})()

    with pytest.raises(ValueError, match="--agent-model-name"):
        _build_agent_model_metadata(args)


def test_agent_model_metadata_records_optional_reasoning_level():
    args = type("Args", (), {"agent_model_name": "gpt-5.1", "agent_model_reasoning_level": " high "})()

    assert _build_agent_model_metadata(args) == {"model_name": "gpt-5.1", "reasoning_level": "high"}


def test_agent_pricing_args_require_model_input_and_output_together():
    args = type(
        "Args",
        (),
        {
            "agent_model_name": "test-model",
            "agent_model_reasoning_level": None,
            "agent_input_cost_per_1m": 1.0,
            "agent_output_cost_per_1m": None,
            "agent_cached_input_cost_per_1m": None,
        },
    )()

    with pytest.raises(ValueError, match="--agent-output-cost-per-1m"):
        _build_batch_agent_pricing(args)


def test_agent_client_args_allow_built_in_path():
    args = type(
        "Args",
        (),
        {
            "agent_class": None,
            "agent_client_class": None,
        },
    )()

    _validate_agent_client_args(args, [])


def test_agent_client_args_allow_custom_pair():
    args = type(
        "Args",
        (),
        {
            "agent_class": "MyAgent",
            "agent_client_class": "MyClient",
        },
    )()

    _validate_agent_client_args(args, [])


def test_agent_client_args_allow_state_bench_subclass_with_built_in_client():
    args = type(
        "Args",
        (),
        {
            "agent_class": "MyStateBenchAgent",
            "agent_client_class": None,
        },
    )()

    _validate_agent_client_args(args, [])


def test_agent_client_args_reject_client_without_agent():
    args = type(
        "Args",
        (),
        {
            "agent_class": None,
            "agent_client_class": "MyClient",
        },
    )()

    with pytest.raises(ValueError, match="requires --agent-class"):
        _validate_agent_client_args(args, [])


@pytest.mark.parametrize("flag", ["--agent-provider", "--agent-api-key-var"])
def test_agent_client_args_reject_built_in_client_flags_with_custom_client(flag):
    args = type(
        "Args",
        (),
        {
            "agent_class": "MyAgent",
            "agent_client_class": "MyClient",
        },
    )()

    with pytest.raises(ValueError, match="only valid with the built-in client"):
        _validate_agent_client_args(args, [flag])


def test_base_agent_add_token_usage_records_tokens_and_costs():
    agent = HarnessToolAgent(runtime_context=_runtime_context_with_pricing())

    agent.add_token_usage(input_tokens=1000, output_tokens=200, cached_input_tokens=400)

    usage = agent.token_usage
    assert usage.input_tokens == 1000
    assert usage.cached_input_tokens == 400
    assert usage.output_tokens == 200
    assert usage.total_tokens == 1200
    assert usage.input_cost_usd == pytest.approx(600 * 1.25 / 1_000_000)
    assert usage.cached_input_cost_usd == pytest.approx(400 * 0.13 / 1_000_000)
    assert usage.output_cost_usd == pytest.approx(200 * 10.0 / 1_000_000)
    assert usage.agent_turn_cost_usd == pytest.approx(usage.total_cost_usd)


def test_base_agent_add_token_usage_skips_when_input_or_output_missing():
    agent = HarnessToolAgent(runtime_context=_runtime_context_with_pricing())

    agent.add_token_usage(input_tokens=100, output_tokens=None)
    agent.add_token_usage(input_tokens=None, output_tokens=100)

    assert agent.token_usage.total_tokens == 0
    assert agent.token_usage.total_cost_usd == 0


def test_base_agent_add_token_usage_records_tokens_without_pricing():
    agent = HarnessToolAgent(runtime_context=AgentRuntimeContext(task_id="t", user_id="u", domain="d", now="n"))

    agent.add_token_usage(input_tokens=100, output_tokens=25)

    assert agent.token_usage.input_tokens == 100
    assert agent.token_usage.output_tokens == 25
    assert agent.token_usage.total_cost_usd == 0


def test_base_agent_add_token_usage_charges_cached_tokens_at_input_rate_without_cached_price():
    agent = HarnessToolAgent(
        runtime_context=AgentRuntimeContext(
            task_id="t",
            user_id="u",
            domain="d",
            now="n",
            agent_pricing=AgentPricing(
                model_name="m",
                input_cost_per_1m_tokens=2.0,
                output_cost_per_1m_tokens=8.0,
                cached_input_cost_per_1m_tokens=None,
            ),
        )
    )

    agent.add_token_usage(input_tokens=1000, output_tokens=100, cached_input_tokens=500)

    assert agent.token_usage.input_cost_usd == pytest.approx(500 * 2.0 / 1_000_000)
    assert agent.token_usage.cached_input_cost_usd == pytest.approx(500 * 2.0 / 1_000_000)
