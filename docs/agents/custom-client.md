# Custom Client + Agent

Use this path to evaluate models from a different provider or write a custom tool-calling agent. STATE-Bench does not ship third-party adapters — provider integration is user-owned.

Custom runs use two extension points together:

- **`BaseLLMClient`** ([`state_bench/client.py`](../../state_bench/client.py)) — your provider-specific client wrapper.
- **`BaseAgent`** ([`state_bench/agents/base.py`](../../state_bench/agents/base.py)) — your agent loop that calls that client and returns provider-neutral tool requests for the harness to execute.

## File layout

Place your implementations under repo-root extension folders:

```text
agents/
  my_agent.py
clients/
  my_client.py
```

Class names must be unique under their folder trees. The harness loads `--agent-class` from `agents/` and `--agent-client-class` from `clients/`.

## Provider environment variables

STATE-Bench does not interpret provider env vars; your `BaseLLMClient.from_env()` does. Add whatever your provider needs to `.env`:

```bash
MY_PROVIDER_API_KEY="<your provider api key>"
MY_PROVIDER_MODEL="<your model name>"
```

## Custom client

Subclass `BaseLLMClient` and implement `from_env()`. The base class does not require a specific method shape; your custom agent decides which client methods to call.

```python
# clients/my_client.py
import os

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
    def model_name(self):
        return self.model

    def generate(self, *, system_prompt, conversation, tools):
        # Call your provider here. Convert STATE-Bench tool schemas to your
        # provider's format if needed, and return an object your agent understands.
        raise NotImplementedError
```

## Custom agent

Subclass `BaseAgent` and implement `generate_next_turn()`. STATE-Bench calls this method every time the agent needs to respond.

`generate_next_turn()` receives:

- `system_prompt` — the locked benchmark system prompt for the selected domain.
- `conversation` — the conversation so far, including prior tool results.
- `tools` — the allowed tool schemas for the selected domain, plus any memory retrieval tool your agent exposes.

It must return an `AgentTurnResponse` with:

- `text` — the assistant text for this turn.
- `tool_calls` — tool requests for STATE-Bench to execute. Use `AgentToolCallRequest(name=..., arguments=...)` for each.

```python
# agents/my_agent.py
from state_bench.agents.base import AgentToolCallRequest, AgentTurnResponse, BaseAgent


class MyAgent(BaseAgent):
    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self.tool_handlers = tool_handlers

    def convert_tools_for_provider(self, tools):
        # STATE-Bench provides OpenAI function-calling style schemas by default.
        # See the "Tool Schemas" section below. If your provider expects a different
        # format, convert the provided `tools` here before sending them in the API call.
        # Keep tool names and argument keys unchanged so the harness can execute returned calls.
        return tools

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        provider_tools = self.convert_tools_for_provider(tools)
        response = self.client.generate(
            system_prompt=system_prompt,
            conversation=conversation,
            tools=provider_tools,
        )

        # Optional: report provider token usage so STATE-Bench can compute
        # average cost per task. See docs/eval/cost-reporting.md.
        usage = getattr(response, "usage", None)
        self.add_token_usage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cached_input_tokens=getattr(usage, "cached_input_tokens", None),
        )

        tool_calls = []
        for call in getattr(response, "tool_calls", []):
            tool_calls.append(AgentToolCallRequest(name=call.name, arguments=call.arguments))

        return AgentTurnResponse(text=response.text, tool_calls=tool_calls)
```

## Tool schemas

The `tools` argument contains the tools for the selected domain. STATE-Bench does not allow adding new tools except a `retrieve_learnings` tool (see [docs/memory/custom-hook.md](../memory/custom-hook.md)). If your provider expects a different tool format, convert the schemas inside your client or agent before sending them to the provider.

The checked-in domain tool schemas live in:

- [state_bench/domains/travel/tools.py](../../state_bench/domains/travel/tools.py)
- [state_bench/domains/customer_support/tools.py](../../state_bench/domains/customer_support/tools.py)
- [state_bench/domains/shopping_assistant/tools.py](../../state_bench/domains/shopping_assistant/tools.py)

Each domain's `config.py` passes its `TOOL_SCHEMAS` into the harness. Inspect these when writing your conversion, but do not edit them for official runs.

When the provider asks to call a tool, return it as an `AgentToolCallRequest`:

```python
AgentToolCallRequest(
    name="tool_name",
    arguments={"key": "value"},
)
```

The equivalent dictionary shape is also accepted:

```python
{"name": "tool_name", "arguments": {"key": "value"}}
```

The harness — not your agent — executes tools. It reads `name`, finds the matching allowed domain or memory tool, runs it with `arguments`, appends the result to the conversation, and calls `generate_next_turn()` again until the agent returns no tool calls.

## Conversation transcript shape

Across turns, `conversation` uses STATE-Bench's canonical transcript shape. Completed tool calls are embedded on the assistant message that requested them:

```python
{
    "role": "assistant",
    "content": "Checking that now.",
    "tool_calls": [{"name": "tool_name", "arguments": {"key": "value"}, "result": {"ok": True}}],
}
```

If your provider expects separate tool-result messages (e.g., OpenAI Chat Completions with paired assistant tool-call messages and `role="tool"` results), convert each embedded `result` into that shape inside your agent before calling the provider.

## Next step

Return to your track guide and continue with the run steps:

- Main Track: [Run Benchmark](../../RUN_BENCHMARK.md)
- Agent Learning Track: [Agent Learning Track](../../AGENT_LEARNING_TRACK.md)
