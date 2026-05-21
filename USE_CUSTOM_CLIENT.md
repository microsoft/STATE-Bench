# Use a Custom Client + Agent

Use this reference when your chosen track evaluates models from a different provider or needs a custom tool-calling agent.

Start from a track guide first:

- Main Track: [Run Benchmark](RUN_BENCHMARK.md)
- Memory Track: [Memory Track](MEMORY_TRACK.md)

Then come here only to build the custom harness. After that, return to your track guide for run, metrics, and submission steps.

STATE-Bench does not ship third-party provider adapters. Provider integration is user-owned.

## What You Build

Custom provider runs use two extension points together:

- **`BaseLLMClient`** ([`state_bench/client.py`](state_bench/client.py)) wraps your provider client and loads provider-specific environment variables.
- **`BaseAgent`** ([`state_bench/agents/base.py`](state_bench/agents/base.py)) calls that client and returns provider-neutral tool requests for the benchmark harness to execute.

Place implementations under repo-root extension folders:

```text
clients/
  my_client.py
agents/
  my_agent.py
```

Class names must be unique under those folders. The harness loads them by class name with `--agent-client-class` and `--agent-class`.

## Provider Environment Variables

STATE-Bench does not interpret third-party provider variables. Your `BaseLLMClient.from_env()` method owns that configuration.

Example `.env` entries:

```bash
MY_PROVIDER_API_KEY="<your provider api key>"
MY_PROVIDER_MODEL="<your model name>"
```

## Custom Client

Subclass `BaseLLMClient` and implement `from_env()`. The base class intentionally does not require a specific request method; your custom agent decides which client methods to call.

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

## Custom Agent

Subclass `BaseAgent` and implement `generate_next_turn()`. STATE-Bench calls this method every time the agent needs to respond.

`generate_next_turn()` receives:

- `system_prompt`: the benchmark system prompt for the selected domain,
- `conversation`: the canonical conversation so far, including prior tool results,
- `tools`: the allowed tool schemas for the selected domain, plus any track-specific tools exposed by your agent.

It must return `AgentTurnResponse` with:

- `text`: assistant text for the current turn,
- `tool_calls`: tool requests for STATE-Bench to execute.

```python
# agents/my_agent.py
from state_bench.agents.base import AgentToolCallRequest, AgentTurnResponse, BaseAgent


class MyAgent(BaseAgent):
    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.client = client

    def convert_tools_for_provider(self, tools):
        # STATE-Bench provides OpenAI function-calling style schemas by default.
        # Convert them here if your provider expects another format.
        # Keep tool names and argument keys unchanged.
        return tools

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        response = self.client.generate(
            system_prompt=system_prompt,
            conversation=conversation,
            tools=self.convert_tools_for_provider(tools),
        )

        usage = getattr(response, "usage", None)
        self.add_token_usage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cached_input_tokens=getattr(usage, "cached_input_tokens", None),
        )

        tool_calls = [
            AgentToolCallRequest(name=call.name, arguments=call.arguments)
            for call in getattr(response, "tool_calls", [])
        ]
        return AgentTurnResponse(text=response.text, tool_calls=tool_calls)
```

## Tool Call Contract

STATE-Bench, not your custom agent, executes benchmark tools.

When your provider requests a tool call, convert it to this shape:

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

The harness validates that `name` is an allowed tool, executes it with `arguments`, appends the result to the conversation, and calls `generate_next_turn()` again until no more tool calls are returned.

## Tool Schemas

The `tools` argument contains domain tool schemas in OpenAI function-calling style. If your provider expects a different tool format, convert the schemas before sending them to the provider.

Do not rename tool names or argument keys. The harness uses those names to execute returned tool calls.

Domain schemas live in:

- [state_bench/domains/travel/tools.py](state_bench/domains/travel/tools.py)
- [state_bench/domains/customer_support/tools.py](state_bench/domains/customer_support/tools.py)
- [state_bench/domains/shopping_assistant/tools.py](state_bench/domains/shopping_assistant/tools.py)

Inspect these files when writing a provider conversion, but do not edit them for official runs.

## Conversation Shape

`conversation` uses STATE-Bench's canonical transcript shape. Completed tool calls are embedded on the assistant message that requested them:

```python
{
    "role": "assistant",
    "content": "Checking that now.",
    "tool_calls": [
        {"name": "tool_name", "arguments": {"key": "value"}, "result": {"ok": True}}
    ],
}
```

If your provider expects separate tool-result messages, convert this canonical shape inside your agent before calling the provider.

## Token Usage And Cost

Cost reporting is strongly encouraged. Custom agents should call `self.add_token_usage(...)` after each provider LLM call returns:

```python
self.add_token_usage(
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cached_input_tokens=cached_input_tokens,
)
```

`input_tokens` and `output_tokens` are required for usage and cost to be recorded. `cached_input_tokens` is optional.

Your track guide explains the pricing flags to pass at run time. Full details: [Reporting Avg. Cost Per Task](docs/eval/cost-reporting.md).

## Return To Your Track

After your custom client and agent classes are in place:

- Main Track users return to [Run Benchmark](RUN_BENCHMARK.md) and run with `--agent-class` plus `--agent-client-class`.
- Memory Track users return to [Memory Track](MEMORY_TRACK.md) and run with `--agent-class`, `--agent-client-class`, and `--retrieve-learnings-top-k 3`.
