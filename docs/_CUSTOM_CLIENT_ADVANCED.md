# Advanced Custom Client Patterns

Use this reference after you understand [Use a Custom Client + Agent](USE_CUSTOM_CLIENT.md). The main guide shows the recommended stateless replay path. This page covers agents that keep provider or framework state on `self`.

STATE-Bench constructs a fresh agent instance for every task. Any state you keep on `self` is scoped to that task and is discarded afterward.

## Tool-Loop Reminder

On the first `generate_next_turn()` call for an agent turn, the last `conversation` item is the new user message. If your response requests tools, STATE-Bench executes them and calls `generate_next_turn()` again with a temporary `role: "tool"` item appended after the assistant tool-call message.

That means stateful agents must handle both cases:

```python
last = conversation[-1]
if last.get("role") == "tool":
    # Follow-up after STATE-Bench executed requested tools.
    tool_results = last.get("content", [])
else:
    # New user turn.
    user_message = last.get("content", "")
```

The saved trajectory remains the canonical transcript for scoring. The temporary `role: "tool"` item is only part of the working conversation passed back to your agent during tool execution.

## Server-Side Stateful Provider

Use this when your provider offers a stateful conversation primitive, such as a response ID, thread ID, or session ID. Cache the provider handle on `self`, send the latest user turn on the first call, then send tool results on follow-up calls.

```python
# agents/my_stateful_agent.py
from state_bench.agents.base import AgentToolCallRequest, AgentTurnResponse, BaseAgent


class MyStatefulAgent(BaseAgent):
    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self._previous_response_id: str | None = None

    def _latest_input(self, conversation):
        last = conversation[-1]
        if last.get("role") == "tool":
            return {"tool_results": last.get("content", [])}
        return {"user_message": last.get("content", "")}

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        response = self.client.generate(
            system_prompt=system_prompt,
            input=self._latest_input(conversation),
            tools=tools,
            previous_response_id=self._previous_response_id,
        )
        self._previous_response_id = response.id

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

Your provider may require tool results in a different shape. Convert `last["content"]`, which is a list of `{name, arguments, result}` records, to the provider's expected tool-result format before sending it.

## Framework-Native History

Use this when an agent framework owns its own message history, such as LangChain, AutoGen, Semantic Kernel, or another framework runtime. Append user turns and tool results as they arrive; the framework owns replay.

```python
# agents/my_framework_agent.py
from state_bench.agents.base import AgentToolCallRequest, AgentTurnResponse, BaseAgent


class MyFrameworkAgent(BaseAgent):
    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.framework_agent = client.build_framework_agent(system_prompt=system_prompt, tools=tools)
        self._native_history: list = []  # framework's native message type

    def _append_latest_to_history(self, conversation):
        last = conversation[-1]
        if last.get("role") == "tool":
            for call in last.get("content") or []:
                self._native_history.append({"role": "tool", "name": call["name"], "content": call["result"]})
            return
        self._native_history.append({"role": "user", "content": last.get("content", "")})

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        self._append_latest_to_history(conversation)

        result = self.framework_agent.run(messages=self._native_history)
        self._native_history = result.messages  # framework's updated native history

        self.add_token_usage(
            input_tokens=getattr(result.usage, "input_tokens", None),
            output_tokens=getattr(result.usage, "output_tokens", None),
            cached_input_tokens=getattr(result.usage, "cached_input_tokens", None),
        )
        return AgentTurnResponse(
            text=result.text,
            tool_calls=[
                AgentToolCallRequest(name=c.name, arguments=c.arguments)
                for c in getattr(result, "tool_calls", [])
            ],
        )
```

Because instances are per-task, `self._native_history` starts empty for every task. No manual reset is needed.

## Next Step

Return to [Use a Custom Client + Agent](USE_CUSTOM_CLIENT.md), then continue with your track guide.
