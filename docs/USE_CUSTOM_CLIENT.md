# Use a Custom Client + Agent

Use this reference when your chosen track evaluates models from a different provider or needs a custom tool-calling agent.

Start from a track guide first:

- Main Track: [Run Benchmark](RUN_BENCHMARK.md)
- Agent Learning Track: [Agent Learning Track](AGENT_LEARNING_TRACK.md)

Then come here only to build the custom harness. After that, return to your track guide for run, metrics, and submission steps.

STATE-Bench does not ship third-party provider adapters. Provider integration is user-owned.

## What You Build

Custom provider runs use two extension points together:

- **`BaseLLMClient`** ([`state_bench/client.py`](../state_bench/client.py)) wraps your provider client and loads provider-specific environment variables.
- **`BaseAgent`** ([`state_bench/agents/base.py`](../state_bench/agents/base.py)) calls that client and returns provider-neutral tool requests for the benchmark harness to execute.

Place implementations under repo-root extension folders:

```text
clients/
  my_client.py
agents/
  my_agent.py
```

Class names must be unique under those folders. The harness loads them by class name with `--agent-client-class` and `--agent-class`.

## How The Harness Calls Your Agent

A few guarantees up front — these shape everything below.

- **Per-task lifecycle (guarantee).** STATE-Bench constructs a fresh agent instance for every task and discards it when the task ends. Any state you put on `self` is automatically scoped to a single task — no reset, no teardown, no cross-task leakage. Build your agent as if it only ever handles one task; the harness handles the rest.
- **One method to implement: `generate_next_turn()`.** STATE-Bench calls it every time the agent needs to respond. You return assistant text plus any tool requests; STATE-Bench executes the tools, appends the results to the working conversation, and calls you again.
- **STATE-Bench executes the domain tools, not your agent.** Return tool requests in the provider-neutral shape defined below and the harness runs them.
- **The saved trajectory is the canonical transcript** used for scoring, judging, and saving. During a tool loop, the `conversation` argument may also include a temporary `role: "tool"` follow-up item so your agent can produce the next step after tool execution.

This guide shows the recommended stateless replay path. If your provider or framework requires server-side state, see [Advanced Custom Client Patterns](_CUSTOM_CLIENT_ADVANCED.md) after you understand the basic contract here.

## Core Concepts (Read Before The Code)

These four shapes appear in every example below. Skim them once, then the code reads as plain wiring.

Minimal checklist:

1. Create `clients/<your_client>.py` with a `BaseLLMClient` subclass and `from_env()`.
2. Create `agents/<your_agent>.py` with a `BaseAgent` subclass and `generate_next_turn()`.
3. Convert STATE-Bench tool schemas and tool-call responses to your provider's format.
4. Call `self.add_token_usage(...)` after each provider call if token counts are available.
5. Return to your track guide and run with `--agent-class` and `--agent-client-class`.

### Canonical Conversation

The saved trajectory conversation is a list of message dicts. Completed tool calls are embedded on the assistant message that requested them — tool results are **not** separate saved messages.

A full three-turn transcript:

```python
[
    {"role": "user", "content": "I'd like to cancel booking ABC123."},
    {
        "role": "assistant",
        "content": "Let me look that up.",
        "tool_calls": [
            {
                "name": "get_booking",
                "arguments": {"booking_id": "ABC123"},
                "result": {"booking_id": "ABC123", "status": "confirmed", "refundable": True},
            }
        ],
    },
    {"role": "user", "content": "Yes, please go ahead and cancel."},
    {
        "role": "assistant",
        "content": "Cancelled. You'll see the refund within 5 business days.",
        "tool_calls": [
            {
                "name": "cancel_booking",
                "arguments": {"booking_id": "ABC123"},
                "result": {"booking_id": "ABC123", "status": "cancelled"},
            }
        ],
    },
]
```

Notes:

- If your provider expects separate `tool` / `function` result messages, convert this canonical shape inside your agent before calling the provider. See [Custom Agent](#custom-agent) for an example, and your provider's docs for the exact target shape (OpenAI Chat Completions uses `role: "tool"`, Anthropic Messages uses `tool_result` content blocks, etc.).
- The `tool_calls` field is omitted (or `None`) on assistant turns with no tool use.
- On the first `generate_next_turn()` call for an agent turn, the last item is the new user message. If your response requests tools, STATE-Bench executes them and calls `generate_next_turn()` again with a temporary `role: "tool"` item appended after the assistant tool-call message. That temporary item is for your provider replay only; it is not saved as a separate trajectory message.

### Tool Schema (`tools` argument)

`tools` is a list of dicts in OpenAI function-calling style. Each entry looks like:

```python
{
    "type": "function",
    "name": "get_booking",
    "description": "Look up a booking by its ID.",
    "parameters": {
        "type": "object",
        "properties": {
            "booking_id": {"type": "string", "description": "The booking ID."},
        },
        "required": ["booking_id"],
        "additionalProperties": False,
    },
}
```

Full canonical examples live in the domain modules:

- [state_bench/domains/travel/tools.py](../state_bench/domains/travel/tools.py)
- [state_bench/domains/customer_support/tools.py](../state_bench/domains/customer_support/tools.py)
- [state_bench/domains/shopping_assistant/tools.py](../state_bench/domains/shopping_assistant/tools.py)

If your provider expects a different schema format, convert these dicts inside your agent before sending them to the provider. **Do not rename tool names or argument keys** — the harness uses those names to dispatch the tool calls you return.

### Tool Call Request (what your agent returns)

When your provider's response asks to call a tool, translate it into either of:

```python
AgentToolCallRequest(name="tool_name", arguments={"key": "value"})
# or the equivalent dict
{"name": "tool_name", "arguments": {"key": "value"}}
```

`AgentToolCallRequest` is a small dataclass exported from `state_bench.agents.base` with two fields: `name: str` and `arguments: dict[str, Any]`.

### Agent Constructor Arguments

The harness constructs your agent with this positional signature:

```python
MyAgent(client, system_prompt, tools, tool_handlers, runtime_context=...)
```

What each argument is for:

- `client` — your `BaseLLMClient` instance, already constructed via `from_env()`. Store on `self.client` and use it however your provider needs.
- `system_prompt` — the benchmark system prompt for the selected domain. Pass to your provider.
- `tools` — the tool schema list described above. Convert and pass to your provider.
- `tool_handlers` — a dict mapping tool name → Python callable for the domain tools. Custom `generate_next_turn()` agents should ignore this argument: STATE-Bench already holds the same handlers and executes the tools you request itself. The argument is part of the constructor signature only so the built-in agent (which self-executes tools) and custom agents can share one calling convention. If your agent needs to expose **additional** tools (e.g., a memory-retrieval tool the model can call), do not stuff them into `tool_handlers` — override `memory_tool_schemas()` and `memory_tool_handlers()` on `BaseAgent` and the harness will merge them in.
- `runtime_context` — an `AgentRuntimeContext` carrying task metadata (`task_id`, `user_id`, `domain`, `now`, optional `agent_pricing`, etc.). Forward to `super().__init__(runtime_context=runtime_context)`. Store on `self` only if you need task metadata inside your agent.

## Provider Environment Variables

STATE-Bench does not interpret third-party provider variables. Your `BaseLLMClient.from_env()` method owns that configuration.

Example `.env` entries:

```bash
MY_PROVIDER_API_KEY="<your provider api key>"
MY_PROVIDER_MODEL="<your model name>"
```

## Custom Client

Subclass `BaseLLMClient` and implement `from_env()`. The base class intentionally does not require a specific request method — your agent decides what to call, with whatever signature suits your provider. The `generate()` method shown below is one reasonable shape for stateless replay.

`model_name` is useful provider metadata. Submitted model metadata and cost reporting come from the required `--agent-model-name` flag and optional pricing flags in your run command.

```python
# clients/my_client.py
import os
from typing import Any

from state_bench.client import BaseLLMClient


class MyLLMClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ["MY_PROVIDER_API_KEY"],
            model=os.environ.get("MY_PROVIDER_MODEL", "my-model"),
        )

    @property
    def model_name(self) -> str:
        return self.model

    def generate(
        self,
        *,
        system_prompt: str,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        # Call your provider here. Convert STATE-Bench tool schemas to your
        # provider's format if needed, and return an object your agent understands.
        raise NotImplementedError
```

### How The Client Reaches Your Agent

You do not wire the client to the agent yourself. At run time, the harness:

1. Loads your client class by name (`--agent-client-class MyLLMClient`) and constructs it via `MyLLMClient.from_env()`.
2. Loads your agent class by name (`--agent-class MyAgent`) and constructs it with the signature shown in [Agent Constructor Arguments](#agent-constructor-arguments).
3. Calls `agent.generate_next_turn(...)` each turn.

## Custom Agent

Subclass `BaseAgent` and implement `generate_next_turn()`. STATE-Bench calls it every time the agent needs to respond.

```python
from typing import Any

from state_bench.agents.base import AgentTurnResponse, BaseAgent


class MyAgent(BaseAgent):
    def generate_next_turn(
        self,
        *,
        system_prompt: str,
        conversation: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AgentTurnResponse:
        ...
```

Arguments mirror the ones described in [Core Concepts](#core-concepts-read-before-the-code):

- `system_prompt` — same benchmark system prompt your `__init__` received. Forwarded each turn so stateless agents don't need to stash it.
- `conversation` — transcript so far. On tool-loop follow-up calls, this includes a temporary `role: "tool"` item containing the tool results from the previous request.
- `tools` — domain tool schemas (plus learning-track tools, when applicable — see [Agent Learning Track](AGENT_LEARNING_TRACK.md)).

Return `AgentTurnResponse`:

```python
AgentTurnResponse(
    text="assistant text for this turn",
    tool_calls=[AgentToolCallRequest(name="tool_name", arguments={"key": "value"})],
)
```

A plain dict with the same keys is also accepted.

The harness validates that each `name` is an allowed tool, executes it with `arguments`, appends the result to the working conversation, and calls `generate_next_turn()` again until no more tool calls are returned. See [Token Usage And Cost](#token-usage-and-cost) below for the `add_token_usage` call used in every example.

Convert STATE-Bench's working conversation → provider shape every turn. No state on `self`.

```python
# agents/my_stateless_agent.py
from state_bench.agents.base import AgentToolCallRequest, AgentTurnResponse, BaseAgent


class MyStatelessAgent(BaseAgent):
    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools  # convert to provider format here if needed
        # tool_handlers is unused — STATE-Bench executes tools, not this agent.

    def _to_provider_messages(self, conversation):
        # Illustrative only. Real conversion is provider-specific — see your
        # provider's docs (OpenAI Chat Completions uses role="tool";
        # Anthropic Messages uses tool_result content blocks; etc.).
        messages = []
        for msg in conversation:
            if msg.get("role") == "tool":
                for call in msg.get("content") or []:
                    messages.append({"role": "tool", "name": call["name"], "content": call["result"]})
                continue
            messages.append({"role": msg["role"], "content": msg.get("content", "")})
            for call in msg.get("tool_calls") or []:
                messages.append({"role": "tool", "name": call["name"], "content": call["result"]})
        return messages

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        response = self.client.generate(
            system_prompt=system_prompt,
            conversation=self._to_provider_messages(conversation),
            tools=tools,
        )
        self.add_token_usage(
            input_tokens=getattr(response.usage, "input_tokens", None),
            output_tokens=getattr(response.usage, "output_tokens", None),
            cached_input_tokens=getattr(response.usage, "cached_input_tokens", None),
        )
        return AgentTurnResponse(
            text=response.text,
            tool_calls=[
                AgentToolCallRequest(name=c.name, arguments=c.arguments)
                for c in getattr(response, "tool_calls", [])
            ],
        )
```

For server-side stateful providers or framework-native history, use the same contract but keep provider state on `self`. See [Advanced Custom Client Patterns](_CUSTOM_CLIENT_ADVANCED.md).

## Token Usage And Cost

Cost reporting is strongly encouraged. Custom agents should call `self.add_token_usage(...)` after each provider LLM call returns:

```python
self.add_token_usage(
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cached_input_tokens=cached_input_tokens,
)
```

`input_tokens` and `output_tokens` are required for usage and cost to be recorded — pass `None` if your provider didn't report them, and the call is skipped silently. `cached_input_tokens` is optional and treated as 0 when missing.

Your track guide explains the pricing flags to pass at run time. Full details: [Reporting Avg. Cost Per Task](eval/cost-reporting.md).

## Return To Your Track

After your custom client and agent classes are in place:

- Main Track users return to [Run Benchmark](RUN_BENCHMARK.md) and run with `--agent-class` plus `--agent-client-class`.
- Agent Learning Track users return to [Agent Learning Track](AGENT_LEARNING_TRACK.md) and run with `--agent-class`, `--agent-client-class`, and `--retrieve-learnings-top-k 3`.
