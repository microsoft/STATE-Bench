# Use a Custom Client

This guide is for evaluating a non-OpenAI LLM provider, custom tool-calling adapter, or fully custom agent loop. For OpenAI or Azure OpenAI GPT models, use `StateBenchAgent` and, if needed, subclass it to add `retrieve_learnings()` as described in [RUN_BENCHMARK.md](RUN_BENCHMARK.md). Custom provider support is user-owned: STATE-Bench does not ship third-party adapters.

You can run this benchmark in two modes:

- **Test Agentic Memory:** Use the train trajectories in Step 1 to generate procedural learnings before evaluating on the test set.
- **General Agent Benchmark:** Evaluate your model or agent directly on the test set by skipping Step 1.

Custom runs use two extension points together:

- `BaseLLMClient`: your provider-specific client wrapper.
- `BaseAgent`: your agent loop that calls that client and returns provider-neutral tool requests.

## Install

STATE-Bench supports Python 3.12+. Install the [uv](https://docs.astral.sh/uv/) package manager if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install the package dependencies:

```bash
uv sync
```

Copy `.env.example` to `.env` and fill only the sections you need as described below.

## Set Environment Variables

### Locked Evaluation Client

The current evaluation protocol is defined [HERE](state_bench/configs/eval_protocols/gpt51.json). It fixes the tasks, splits, user simulator prompt, judge prompts, and required simulator and judge model so results are comparable across submissions. The current protocol requires GPT-5.1 for the user simulator and judge. The agent model is user-configurable.

NOTE: all prompts are hashed. If you change any prompt file, the hash will change and the evaluation will throw an error. This ensures that all runs use the same prompts.

```bash
STATE_BENCH_EVAL_ENDPOINT="https://your-gpt51-resource.openai.azure.com"
STATE_BENCH_EVAL_DEPLOYMENTS="<your gpt 5.1 deployment name>"
# Optional. If omitted, Azure token auth is tried.
# STATE_BENCH_EVAL_API_KEY="<your gpt 5.1 resource api key>"
```

Deployment names can vary by resource. If `STATE_BENCH_EVAL_API_KEY` is omitted, the client tries Azure token auth through local CLI credentials and `DefaultAzureCredential`.

### Custom Agent Client

Set any provider-specific environment variables your `BaseLLMClient.from_env()` implementation needs. STATE-Bench does not interpret these variables; your custom client does.

Example:

```bash
MY_PROVIDER_API_KEY="<your provider api key>"
MY_PROVIDER_MODEL="<your model name>"
```

## File Layout

Create root extension folders in your repo checkout:

```text
agents/
  my_agent.py
clients/
  my_client.py
```

Class names must be unique under their folder trees. STATE-Bench loads `--agent-class` from repo-root `agents/` and `--agent-client-class` from repo-root `clients/`.

## Custom Client

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

## Custom Agent

Subclass `BaseAgent` and implement `generate_next_turn()`. STATE-Bench calls this method every time the agent needs to respond.

`generate_next_turn()` receives:

- `system_prompt`: the locked benchmark system prompt for the selected domain.
- `conversation`: the conversation so far, including prior tool results.
- `tools`: the allowed tool schemas for the selected domain, plus any memory retrieval tool your agent exposes.

`generate_next_turn()` must return an `AgentTurnResponse` with:

- `text`: the assistant text for this turn.
- `tool_calls`: tool requests for STATE-Bench to execute. Use `AgentToolCallRequest(name=..., arguments=...)` for each requested tool call.

The provider may return tool calls in its own response format. Convert those provider-native tool calls into `AgentToolCallRequest` objects before returning from `generate_next_turn()`.

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
        # See the "Tool Schemas" section below for details. If your provider expects a different format,
        # convert the provided `tools` into your provider's expected format here before sending them in the API call.

        # Provider-specific conversion goes here.
        # Keep the original tool names and argument keys unchanged so the
        # harness can execute any tool calls returned by the provider.
        return tools

    def generate_next_turn(self, *, system_prompt, conversation, tools):
        provider_tools = self.convert_tools_for_provider(tools)
        response = self.client.generate(
            system_prompt=system_prompt,
            conversation=conversation,
            tools=provider_tools,
        )

        # Optional: report provider token usage so STATE-Bench can compute
        # average cost per task. See "Reporting Avg. Cost Per Task" below.
        usage = getattr(response, "usage", None)
        self.add_token_usage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cached_input_tokens=getattr(usage, "cached_input_tokens", None),
        )

        tool_calls = []
        for call in getattr(response, "tool_calls", []):
            # Convert the provider's tool-call object into the STATE-Bench request shape.
            tool_calls.append(AgentToolCallRequest(name=call.name, arguments=call.arguments))

        return AgentTurnResponse(text=response.text, tool_calls=tool_calls)
```

## Tool Schemas

The `tools` argument contains the tools for the selected domain. STATE-Bench does not allow adding new tools except a `retrieve_learnings` tool (details below). If your provider expects a different tool format, convert these provided schemas inside your client or agent before sending them to the provider.

The checked-in domain tool schemas are defined in:

- [state_bench/domains/travel/tools.py](state_bench/domains/travel/tools.py)
- [state_bench/domains/customer_support/tools.py](state_bench/domains/customer_support/tools.py)
- [state_bench/domains/shopping_assistant/tools.py](state_bench/domains/shopping_assistant/tools.py)

Each domain's `config.py` passes its `TOOL_SCHEMAS` into the harness. Inspect these schemas when writing your provider-format conversion, but do not edit them for official benchmark runs.

When the provider asks to call a tool, return that request to STATE-Bench as an `AgentToolCallRequest`:

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

This is needed because the harness, not the custom agent, executes tools. The harness reads `name`, finds the matching allowed domain tool or declared memory tool, runs it with `arguments`, appends the tool result to the conversation, and calls `generate_next_turn()` again until the agent returns no tool calls.

Across turns, `conversation` uses STATE-Bench's canonical transcript shape. Completed tool calls are embedded on the assistant message that requested them:

```python
{
    "role": "assistant",
    "content": "Checking that now.",
    "tool_calls": [{"name": "tool_name", "arguments": {"key": "value"}, "result": {"ok": True}}],
}
```

If your provider expects separate tool-result messages, convert each embedded `result` into that provider's required shape before calling the provider. For example, OpenAI Chat Completions adapters typically need to synthesize paired assistant tool-call messages and `role="tool"` result messages from these records.

## Step 1: Build Procedural Learnings From Train Trajectories

NOTE: Skip this step for a general agent benchmark with no memory.

If your method uses procedural learnings, build your learning artifact from the provided train trajectories before running the test split. They are stored under:

```bash
datasets/train_task_trajectories/<domain>/<task_id>.json
```

The artifact format is up to you. It can be JSON, a vector index, a database, or any local file your custom agent can read during inference. Artifact creation is user-owned; STATE-Bench only calls the inference-time tool handlers your agent exposes.

### Expose Memory Retrieval Tool For Evaluation Runs

If you are testing agentic memory, expose a read-only retrieval tool by overriding `memory_tool_schemas()` and `memory_tool_handlers()`.

```python
from pathlib import Path


class MyAgent(BaseAgent):
    learnings_path = Path("outputs/learnings.json")

    def memory_tool_schemas(self):
        return [
            {
                "type": "function",
                "name": "retrieve_learnings",
                "description": "Retrieve procedural learnings relevant to the current task.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]

    def memory_tool_handlers(self):
        return {"retrieve_learnings": self.retrieve_learnings}

    def retrieve_learnings(self, query: str) -> list[str]:
        # Load/query your artifact and return relevant learnings.
        raise NotImplementedError
```

Memory tools should not mutate benchmark state. Domain tools are still owned and executed by STATE-Bench.

## Step 2: Evaluate on Test Tasks

`run_batch.py` runs the protocol test tasks and scores each trajectory inline with the locked judge. Do not edit the locked base prompt, judge prompts, benchmark domain tools, or protocol file for official runs.

For custom provider runs, `run_batch.py` requires both `--agent-class` and `--agent-client-class`. Passing only `--agent-client-class` is rejected. Passing only `--agent-class` uses the built-in OpenAI/Azure OpenAI client path and is only for `StateBenchAgent` subclasses.

```bash
uv run python -m state_bench.scripts.run_batch \
  --domain <domain> \
  --agent-class MyAgent \
  --agent-client-class MyLLMClient \
  --agent-model-name <model-name> \
  --agent-model-reasoning-level <reasoning-level> \
  --num-runs 5 \
  --num-workers <parallel workers> \
  --output-dir outputs/<domain>/test_trajectories
```

Arguments:

- `--domain`: Benchmark domain to run: `travel`, `customer_support`, or `shopping_assistant`.
- `--agent-class`: Required custom `BaseAgent` subclass name under repo-root `agents/`.
- `--agent-client-class`: Required custom `BaseLLMClient` subclass name under repo-root `clients/`.
- `--agent-model-name`: Required model name reported in trajectories and the submitted `metrics.json`. E.g. `claude-sonnet-4.5`.
- `--agent-model-reasoning-level`: Reasoning level reported in trajectories and `metrics.json` when the agent model uses one. E.g. `medium`. This is important for grouping results in the leaderboard.
- `--num-runs`: Number of runs per task. Set to `5` for official submissions.
- `--num-workers`: Number of benchmark tasks to run in parallel. Tune this for your provider rate limits.
- `--output-dir`: Directory where scored trajectories are written.

The output is scored trajectories from `outputs/<domain>/test_trajectories/run1/<task_id>.json` through `outputs/<domain>/test_trajectories/run5/<task_id>.json`.

A good starting point for `--num-workers` is the number of parallel API calls your provider can handle without hitting rate limits or timeouts.

### Reporting Avg. Cost Per Task

One metric in the benchmark is the average cost to run a task. We strongly encourage benchmark users to provide pricing in the `run_batch.py` command.

Custom clients should use provider-reported token counts. STATE-Bench does not estimate third-party model tokens. After each provider LLM call returns, call `self.add_token_usage(...)` from your custom agent with the usage metadata from that response. In most implementations, this goes inside `generate_next_turn()` immediately after `self.client.generate(...)` returns:

```python
self.add_token_usage(
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cached_input_tokens=cached_input_tokens,
)
```

`input_tokens` and `output_tokens` are required for recording usage and cost. `cached_input_tokens` is optional. If token counts are missing, STATE-Bench skips usage and cost recording for that call.

Use these pricing flags:

```bash
--agent-input-cost-per-1m <input-price> \
--agent-output-cost-per-1m <output-price>
```

If your provider reports cached input tokens and has a separate cached-input rate, also pass:

```bash
--agent-cached-input-cost-per-1m <cached-input-price>
```

If cached tokens are reported without a cached rate, they are charged at the normal input rate.

## Step 3: Compute Metrics

```bash
uv run python -m state_bench.scripts.compute_metrics \
  --domain <domain> \
  --results-dir outputs/<domain>/test_trajectories \
  --num-runs 5 \
  --save-filepath outputs/<domain>/metrics.json
```

Arguments:

- `--domain`: Benchmark domain to score: `travel`, `customer_support`, or `shopping_assistant`.
- `--results-dir`: Directory containing the scored trajectories from Step 2.
- `--num-runs`: Number of runs to include. Set to `5` for official submissions. This should match the `--num-runs` used in Step 2.
- `--save-filepath`: Path where the standardized public metrics JSON file is written.

Metrics default to the protocol test split and fail if any expected test task is missing or unscored. For local partial analysis only, add `--ignore-missing-runs`.

Repeat Steps 1-3 for every protocol domain.

## Submit Results

Create `outputs.zip` containing the scored trajectories and metrics for each completed domain:

- `outputs/<domain>/test_trajectories/`
- `outputs/<domain>/metrics.json`, which includes the evaluation protocol ID and standardized public metrics

Submit results by opening a GitHub issue in this repository. Attach `outputs.zip` to the issue if it is within GitHub's upload limit; otherwise, include a download link to the archive. Include brief details of your method, plus links to any relevant paper, GitHub repository, or project page. After verification, accepted results will be uploaded to the official leaderboard.
