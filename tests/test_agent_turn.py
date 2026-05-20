"""Tests for StateBenchAgent tool-calling loop.

Verifies that StateBenchAgent.act() correctly chains tool calls via
the LLM client's complete_with_tools method, and that previous_response_id
is properly used within tool loops.
"""

from unittest.mock import MagicMock

import pytest

from state_bench.agents.base import AgentPricing, AgentRuntimeContext
from state_bench.agents.state_bench import RETRIEVE_LEARNINGS_TOOL_NAME, StateBenchAgent
from state_bench.client import LLMClient, PooledLLMClient


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


def _runtime_context_without_pricing() -> AgentRuntimeContext:
    return AgentRuntimeContext(
        task_id="task-1",
        user_id="user_001",
        domain="travel",
        now="2026-06-15T10:00:00",
    )


def _make_response(response_id: str, output_items: list, output_text: str = "") -> MagicMock:
    """Create a mock Responses API response object."""
    response = MagicMock()
    response.id = response_id
    response.output = output_items
    response.output_text = output_text
    response.status = "completed"
    response.incomplete_details = None
    response.usage = None
    return response


def _make_usage(*, input_tokens: int, cached_tokens: int, output_tokens: int, reasoning_tokens: int = 0) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.total_tokens = input_tokens + output_tokens
    usage.input_tokens_details = MagicMock(cached_tokens=cached_tokens)
    usage.output_tokens_details = MagicMock(reasoning_tokens=reasoning_tokens)
    return usage


def _make_function_call(call_id: str, name: str, arguments: str) -> MagicMock:
    """Create a mock function_call output item."""
    item = MagicMock()
    item.type = "function_call"
    item.call_id = call_id
    item.name = name
    item.arguments = arguments
    return item


def _make_text_item(text: str) -> MagicMock:
    """Create a mock text output item."""
    item = MagicMock()
    item.type = "message"
    item.text = text
    return item


def _make_agent(mock_complete_with_tools: MagicMock, tool_handlers: dict | None = None) -> StateBenchAgent:
    """Create a StateBenchAgent with a mocked client.

    Sets up the pinned() context manager to return a mock LLMClient
    whose complete_with_tools is the provided mock.
    """
    pinned_client = MagicMock()
    pinned_client.complete_with_tools = mock_complete_with_tools

    pinned_ctx = MagicMock()
    pinned_ctx.__enter__ = MagicMock(return_value=pinned_client)
    pinned_ctx.__exit__ = MagicMock(return_value=False)

    client = MagicMock(spec=PooledLLMClient)
    client.pinned.return_value = pinned_ctx
    return StateBenchAgent(
        client=client,
        system_prompt="You are a travel agent.",
        tools=[{"type": "function", "name": "get_booking"}],
        tool_handlers=tool_handlers or {},
        runtime_context=_runtime_context_with_pricing(),
    )


class RetrievalAgent(StateBenchAgent):
    def __init__(self, *args, learnings: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.queries: list[tuple[str, int]] = []
        self._learnings = learnings or [
            "Check policy before write tools.",
            "Confirm before irreversible actions.",
            "Explain fees before acting.",
            "Avoid unrelated write tools.",
        ]

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        self.queries.append((query, top_k))
        return self._learnings[:top_k]


class BadRetrievalAgent(StateBenchAgent):
    def retrieve_learnings(self, query: str, top_k: int = 3):
        return {"learning": query}


def _make_retrieval_agent(mock_complete_with_tools: MagicMock, *, cls=RetrievalAgent) -> StateBenchAgent:
    pinned_client = MagicMock()
    pinned_client.complete_with_tools = mock_complete_with_tools

    pinned_ctx = MagicMock()
    pinned_ctx.__enter__ = MagicMock(return_value=pinned_client)
    pinned_ctx.__exit__ = MagicMock(return_value=False)

    client = MagicMock(spec=PooledLLMClient)
    client.pinned.return_value = pinned_ctx
    return cls(
        client=client,
        system_prompt="You are a travel agent.",
        tools=[{"type": "function", "name": "get_booking"}],
        tool_handlers={"get_booking": lambda args: {"booking_id": args["booking_id"]}},
        runtime_context=_runtime_context_with_pricing(),
    )


class TestStateBenchAgentInstructions:
    """Test that StateBenchAgent passes system prompt via instructions parameter."""

    def test_first_turn_uses_instructions_param(self):
        """First turn should pass system prompt via instructions."""
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_001", [text_item], "Hello!")
        mock = MagicMock(side_effect=[response])
        agent = _make_agent(mock)

        agent.act([{"role": "user", "content": "Hi"}])

        kwargs = mock.call_args_list[0].kwargs
        assert kwargs["instructions"] == "You are a travel agent."
        for item in kwargs["input"]:
            if isinstance(item, dict):
                assert item.get("role") != "system"

    def test_single_llm_client_does_not_need_pinned_context(self):
        """Single benchmark LLMClient instances call complete_with_tools() directly."""
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_001", [text_item], "Hello!")
        client = MagicMock(spec=LLMClient)
        client.complete_with_tools = MagicMock(return_value=response)
        agent = StateBenchAgent(
            client=client,
            system_prompt="You are a travel agent.",
            tools=[],
            tool_handlers={},
            runtime_context=_runtime_context_with_pricing(),
        )

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Hi"}])

        assert text == "Hello!"
        assert tool_calls == []
        assert raw_items == [text_item]
        client.complete_with_tools.assert_called_once()

    def test_rejects_arbitrary_compatible_client(self):
        """StateBenchAgent only supports benchmark-created client types."""
        client = MagicMock()
        client.complete_with_tools = MagicMock()

        with pytest.raises(TypeError, match="LLMClient or PooledLLMClient"):
            StateBenchAgent(
                client=client,
                system_prompt="You are a travel agent.",
                tools=[],
                tool_handlers={},
                runtime_context=_runtime_context_with_pricing(),
            )

    def test_first_turn_no_previous_response_id(self):
        """First API call should not include previous_response_id."""
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_001", [text_item], "Hello!")
        mock = MagicMock(side_effect=[response])
        agent = _make_agent(mock)

        agent.act([{"role": "user", "content": "Hi"}])

        kwargs = mock.call_args_list[0].kwargs
        assert kwargs.get("previous_response_id") is None

    def test_retrieval_subclass_gets_tool_and_prompt_instruction(self):
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_001", [text_item], "Hello!")
        mock = MagicMock(side_effect=[response])
        agent = _make_retrieval_agent(mock)

        agent.act([{"role": "user", "content": "Hi"}])

        kwargs = mock.call_args_list[0].kwargs
        tool_names = [tool["name"] for tool in kwargs["tools"]]
        assert RETRIEVE_LEARNINGS_TOOL_NAME in tool_names
        assert "Before your first substantive answer" in kwargs["instructions"]

    def test_base_agent_does_not_get_retrieval_tool(self):
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_001", [text_item], "Hello!")
        mock = MagicMock(side_effect=[response])
        agent = _make_agent(mock)

        agent.act([{"role": "user", "content": "Hi"}])

        kwargs = mock.call_args_list[0].kwargs
        tool_names = [tool["name"] for tool in kwargs["tools"]]
        assert RETRIEVE_LEARNINGS_TOOL_NAME not in tool_names
        assert "Procedural Learning Retrieval" not in kwargs["instructions"]


class TestStateBenchAgentToolLoopChaining:
    """Test that tool loop iterations chain via previous_response_id."""

    def test_single_tool_call_chains(self):
        """Tool loop follow-up should chain via previous_response_id."""
        tool_call = _make_function_call("call_1", "get_booking", '{"booking_id": "BK-1000"}')
        text_item = _make_text_item("Your booking is confirmed.")

        response_1 = _make_response("resp_001", [tool_call])
        response_2 = _make_response("resp_002", [text_item], "Your booking is confirmed.")

        mock = MagicMock(side_effect=[response_1, response_2])
        tool_handlers = {
            "get_booking": lambda args: {"booking_id": "BK-1000", "status": "confirmed"},
        }
        agent = _make_agent(mock, tool_handlers)

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Show my booking"}])

        assert text == "Your booking is confirmed."
        assert len(tool_calls) == 1

        second_kwargs = mock.call_args_list[1].kwargs
        assert second_kwargs["previous_response_id"] == "resp_001"
        input_items = second_kwargs["input"]
        assert len(input_items) == 1
        assert input_items[0]["type"] == "function_call_output"
        assert input_items[0]["call_id"] == "call_1"

    def test_multi_step_tool_loop(self):
        """Multiple tool loop iterations each chain to the previous response."""
        tool_call_1 = _make_function_call("call_1", "get_user_reservations", '{"user_id": "user_001"}')
        tool_call_2 = _make_function_call("call_2", "get_booking", '{"booking_id": "BK-1000"}')
        text_item = _make_text_item("Here are your booking details.")

        response_1 = _make_response("resp_001", [tool_call_1])
        response_2 = _make_response("resp_002", [tool_call_2])
        response_3 = _make_response("resp_003", [text_item], "Here are your booking details.")

        mock = MagicMock(side_effect=[response_1, response_2, response_3])
        tool_handlers = {
            "get_user_reservations": lambda args: {"booking_ids": ["BK-1000"]},
            "get_booking": lambda args: {"booking_id": "BK-1000", "status": "confirmed"},
        }

        pinned_client = MagicMock()
        pinned_client.complete_with_tools = mock
        pinned_ctx = MagicMock()
        pinned_ctx.__enter__ = MagicMock(return_value=pinned_client)
        pinned_ctx.__exit__ = MagicMock(return_value=False)
        client = MagicMock(spec=PooledLLMClient)
        client.pinned.return_value = pinned_ctx

        agent = StateBenchAgent(
            client=client,
            system_prompt="You are a travel agent.",
            tools=[
                {"type": "function", "name": "get_user_reservations"},
                {"type": "function", "name": "get_booking"},
            ],
            tool_handlers=tool_handlers,
            runtime_context=_runtime_context_with_pricing(),
        )

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Show my bookings"}])

        assert text == "Here are your booking details."
        assert len(tool_calls) == 2

        assert mock.call_args_list[1].kwargs["previous_response_id"] == "resp_001"
        assert mock.call_args_list[2].kwargs["previous_response_id"] == "resp_002"

    def test_parallel_tool_calls(self):
        """Multiple tool calls in one response produce one chained follow-up."""
        tool_call_a = _make_function_call("call_a", "get_booking", '{"booking_id": "BK-1000"}')
        tool_call_b = _make_function_call("call_b", "get_booking", '{"booking_id": "BK-1001"}')
        text_item = _make_text_item("Both bookings found.")

        response_1 = _make_response("resp_001", [tool_call_a, tool_call_b])
        response_2 = _make_response("resp_002", [text_item], "Both bookings found.")

        mock = MagicMock(side_effect=[response_1, response_2])
        tool_handlers = {
            "get_booking": lambda args: {"booking_id": args["booking_id"], "status": "confirmed"},
        }
        agent = _make_agent(mock, tool_handlers)

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Show both bookings"}])

        assert text == "Both bookings found."
        assert len(tool_calls) == 2

        second_kwargs = mock.call_args_list[1].kwargs
        assert second_kwargs["previous_response_id"] == "resp_001"
        assert len(second_kwargs["input"]) == 2
        call_ids = {item["call_id"] for item in second_kwargs["input"]}
        assert call_ids == {"call_a", "call_b"}

    def test_retrieve_learnings_tool_routes_query_and_records_result(self):
        retrieval_call = _make_function_call(
            "call_mem", RETRIEVE_LEARNINGS_TOOL_NAME, '{"query":"refund policy confirmation"}'
        )
        text_item = _make_text_item("I found the relevant learning.")
        response_1 = _make_response("resp_001", [retrieval_call])
        response_2 = _make_response("resp_002", [text_item], "I found the relevant learning.")
        mock = MagicMock(side_effect=[response_1, response_2])
        agent = _make_retrieval_agent(mock)

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Help with my refund"}])

        assert text == "I found the relevant learning."
        assert agent.queries == [("refund policy confirmation", 3)]
        assert tool_calls == [
            {
                "name": RETRIEVE_LEARNINGS_TOOL_NAME,
                "arguments": {"query": "refund policy confirmation"},
                "result": {
                    "learnings": [
                        "Check policy before write tools.",
                        "Confirm before irreversible actions.",
                        "Explain fees before acting.",
                    ]
                },
            }
        ]
        assert raw_items[1]["output"] == (
            '{"learnings": ["Check policy before write tools.", '
            '"Confirm before irreversible actions.", "Explain fees before acting."]}'
        )

    def test_retrieve_learnings_tool_uses_benchmark_fixed_top_k(self):
        retrieval_call = _make_function_call("call_mem", RETRIEVE_LEARNINGS_TOOL_NAME, '{"query":"refund","top_k":2}')
        text_item = _make_text_item("I found the relevant learning.")
        response_1 = _make_response("resp_001", [retrieval_call])
        response_2 = _make_response("resp_002", [text_item], "I found the relevant learning.")
        mock = MagicMock(side_effect=[response_1, response_2])
        agent = _make_retrieval_agent(mock)

        _text, tool_calls, _raw_items = agent.act([{"role": "user", "content": "Help with my refund"}])

        assert agent.queries == [("refund", 3)]
        assert tool_calls[0]["result"] == {
            "learnings": [
                "Check policy before write tools.",
                "Confirm before irreversible actions.",
                "Explain fees before acting.",
            ]
        }

    def test_retrieve_learnings_top_k_can_be_set_by_benchmark(self):
        retrieval_call = _make_function_call("call_mem", RETRIEVE_LEARNINGS_TOOL_NAME, '{"query":"refund","top_k":3}')
        text_item = _make_text_item("I found the relevant learning.")
        response_1 = _make_response("resp_001", [retrieval_call])
        response_2 = _make_response("resp_002", [text_item], "I found the relevant learning.")
        mock = MagicMock(side_effect=[response_1, response_2])
        agent = _make_retrieval_agent(mock)
        agent.retrieve_learnings_top_k = 2

        _text, tool_calls, _raw_items = agent.act([{"role": "user", "content": "Help with my refund"}])

        assert agent.queries == [("refund", 2)]
        assert tool_calls[0]["result"] == {
            "learnings": ["Check policy before write tools.", "Confirm before irreversible actions."]
        }

    def test_retrieve_learnings_rejects_invalid_top_k(self):
        retrieval_call = _make_function_call("call_mem", RETRIEVE_LEARNINGS_TOOL_NAME, '{"query":"refund","top_k":0}')
        response_1 = _make_response("resp_001", [retrieval_call])
        mock = MagicMock(side_effect=[response_1])
        agent = _make_retrieval_agent(mock)

        with pytest.raises(ValueError, match="top_k"):
            agent.act([{"role": "user", "content": "Help with my refund"}])

    def test_retrieve_learnings_requires_list_of_strings(self):
        retrieval_call = _make_function_call("call_mem", RETRIEVE_LEARNINGS_TOOL_NAME, '{"query":"refund"}')
        response_1 = _make_response("resp_001", [retrieval_call])
        mock = MagicMock(side_effect=[response_1])
        agent = _make_retrieval_agent(mock, cls=BadRetrievalAgent)

        with pytest.raises(TypeError, match=r"list\[str\]"):
            agent.act([{"role": "user", "content": "Help with my refund"}])


class TestStateBenchAgentReturnValue:
    """Test that act() returns text, tool_calls, and raw_items."""

    def test_returns_text(self):
        """Return value should include the agent's text response."""
        text_item = _make_text_item("Hello!")
        response = _make_response("resp_abc", [text_item], "Hello!")
        mock = MagicMock(side_effect=[response])
        agent = _make_agent(mock)

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Hi"}])

        assert text == "Hello!"
        assert tool_calls == []

    def test_returns_tool_calls_after_loop(self):
        """After tool loop, should return all tool calls made."""
        tool_call = _make_function_call("call_1", "get_booking", '{"booking_id": "BK-1"}')
        text_item = _make_text_item("Done.")

        response_1 = _make_response("resp_first", [tool_call])
        response_2 = _make_response("resp_final", [text_item], "Done.")

        mock = MagicMock(side_effect=[response_1, response_2])
        agent = _make_agent(mock, {"get_booking": lambda a: {"ok": True}})

        text, tool_calls, raw_items = agent.act([{"role": "user", "content": "Do it"}])

        assert text == "Done."
        assert len(tool_calls) == 1
        assert tool_calls[0]["name"] == "get_booking"


class TestStateBenchAgentUsageTracking:
    def test_accumulates_input_cached_and_output_tokens(self):
        tool_call = _make_function_call("call_1", "get_booking", '{"booking_id": "BK-1"}')
        text_item = _make_text_item("Done.")

        response_1 = _make_response("resp_first", [tool_call])
        response_1.usage = _make_usage(input_tokens=1000, cached_tokens=800, output_tokens=120, reasoning_tokens=40)
        response_2 = _make_response("resp_final", [text_item], "Done.")
        response_2.usage = _make_usage(input_tokens=200, cached_tokens=150, output_tokens=60, reasoning_tokens=10)

        mock = MagicMock(side_effect=[response_1, response_2])
        agent = _make_agent(mock, {"get_booking": lambda a: {"ok": True}})

        agent.act([{"role": "user", "content": "Do it"}])

        assert agent.token_usage.input_tokens == 1200
        assert agent.token_usage.cached_input_tokens == 950
        assert agent.token_usage.output_tokens == 180
        assert agent.token_usage.reasoning_output_tokens == 50
        assert agent.token_usage.total_tokens == 1380
        assert round(agent.token_usage.agent_turn_cost_usd, 6) == round(
            ((250 * 1.25) + (950 * 0.13) + (180 * 10.0)) / 1_000_000, 6
        )
        assert agent.token_usage.memory_ingestion_cost_usd == 0.0
        assert round(agent.token_usage.total_cost_usd, 6) == round(
            ((250 * 1.25) + (950 * 0.13) + (180 * 10.0)) / 1_000_000, 6
        )

    def test_accumulates_tokens_without_pricing_metadata(self):
        text_item = _make_text_item("Done.")
        response = _make_response("resp_first", [text_item], "Done.")
        response.usage = _make_usage(input_tokens=1000, cached_tokens=800, output_tokens=120, reasoning_tokens=40)

        client = MagicMock(spec=LLMClient)
        client.complete_with_tools = MagicMock(return_value=response)
        agent = StateBenchAgent(
            client=client,
            system_prompt="You are a travel agent.",
            tools=[],
            tool_handlers={},
            runtime_context=_runtime_context_without_pricing(),
        )

        agent.act([{"role": "user", "content": "Do it"}])

        assert agent.token_usage.input_tokens == 1000
        assert agent.token_usage.cached_input_tokens == 800
        assert agent.token_usage.output_tokens == 120
        assert agent.token_usage.reasoning_output_tokens == 40
        assert agent.token_usage.total_tokens == 1120
        assert agent.token_usage.total_cost_usd == 0.0


class TestAgentReasoningEffort:
    """Bug-fix regression: --agent-model-reasoning-level must reach complete_with_tools."""

    def test_reasoning_effort_forwarded_to_complete_with_tools(self):
        response = _make_response("r-1", [_make_text_item("done")], output_text="done")
        mock = MagicMock(return_value=response)
        pinned_client = MagicMock()
        pinned_client.complete_with_tools = mock
        pinned_ctx = MagicMock()
        pinned_ctx.__enter__ = MagicMock(return_value=pinned_client)
        pinned_ctx.__exit__ = MagicMock(return_value=False)
        client = MagicMock(spec=PooledLLMClient)
        client.pinned.return_value = pinned_ctx

        agent = StateBenchAgent(
            client=client,
            system_prompt="You are a travel agent.",
            tools=[{"type": "function", "name": "get_booking"}],
            tool_handlers={},
            runtime_context=_runtime_context_with_pricing(),
            agent_reasoning_effort="high",
        )
        agent.act([{"role": "user", "content": "hi"}])

        _, kwargs = mock.call_args
        assert kwargs.get("reasoning_effort") == "high"

    def test_reasoning_effort_default_none_forwarded(self):
        response = _make_response("r-2", [_make_text_item("done")], output_text="done")
        mock = MagicMock(return_value=response)
        agent = _make_agent(mock)
        agent.act([{"role": "user", "content": "hi"}])
        _, kwargs = mock.call_args
        assert kwargs.get("reasoning_effort") is None

    def test_invalid_reasoning_effort_rejected(self):
        client = MagicMock(spec=PooledLLMClient)
        with pytest.raises(ValueError, match="agent_reasoning_effort"):
            StateBenchAgent(
                client=client,
                system_prompt="x",
                tools=[],
                tool_handlers={},
                runtime_context=_runtime_context_with_pricing(),
                agent_reasoning_effort="extreme",
            )
