# Built-in StateBenchAgent Client

`StateBenchAgent` is the provided standard tool-calling agent loop for Azure AI Foundry models and OpenAI models. It uses the OpenAI v1 client to call the Responses API with the benchmark's domain tools and the locked prompt protocol. If your model supports this tool-calling path, no agent code is required.

## Configure the client

Pick one of the two provider options below and set the variables in your `.env`.

### Azure AI Foundry / Azure OpenAI

```bash
STATE_BENCH_AGENT_ENDPOINT="https://your-agent-resource.openai.azure.com"
STATE_BENCH_AGENT_DEPLOYMENTS="<your agent deployment name>"
# Optional. If omitted, Azure token auth is tried.
STATE_BENCH_AGENT_API_KEY="<your agent resource api key>"
```

For multiple Azure deployments, use a comma-separated list:

```bash
STATE_BENCH_AGENT_DEPLOYMENTS="deployment-a, deployment-b"
```

The harness round-robins across deployments with sticky routing for Responses API `previous_response_id` chains.

### OpenAI API

```bash
STATE_BENCH_AGENT_PROVIDER="openai"
STATE_BENCH_AGENT_MODEL="<your OpenAI model>"
STATE_BENCH_AGENT_API_KEY="<your OpenAI API key>"
```

`OPENAI_API_KEY` is also accepted as a fallback. If both are set, `STATE_BENCH_AGENT_API_KEY` is used for the agent client.

For the OpenAI API, parallelism comes from concurrent API calls to that model, controlled by `--num-workers` at run time.

## What `StateBenchAgent` does

Source: [`state_bench/agents/state_bench.py`](../../state_bench/agents/state_bench.py).

Per turn it calls the Responses API with the domain tool schemas, executes any tool calls locally against the task environment, feeds `function_call_output` items back with `previous_response_id`, and repeats until the model returns a final text answer. Token usage and cost are recorded automatically from provider-reported metadata.

If you want to add a memory retrieval hook on top of this loop, see [docs/memory/builtin-hook.md](../memory/builtin-hook.md).

## Next step

Return to your track guide and continue with the run steps:

- Main Track: [Run Benchmark](../../RUN_BENCHMARK.md)
- Agent Learning Track: [Agent Learning Track](../../AGENT_LEARNING_TRACK.md)
