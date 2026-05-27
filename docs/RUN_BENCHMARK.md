# Run Benchmark: Main Track

Use the **Main Track** to evaluate an agent or model on STATE-Bench's provided enterprise benchmark tasks. This is the default benchmark path.

If you want to benchmark agentic memory, skills, or prompt optimization, use the [Agent Learning Track](AGENT_LEARNING_TRACK.md) instead.

## 1. Install

STATE-Bench supports Python 3.12+ and uses [uv](https://docs.astral.sh/uv/). From a fresh checkout, sync dependencies and create your local environment file:

```bash
uv sync
cp .env.example .env
```

STATE-Bench makes LLM calls in three places:

- the locked user simulator,
- the locked judge,
- the agent under test.

The simulator and judge are fixed by the benchmark protocol. Your agent model is configurable.

## 2. Configure Clients

### Locked simulator and judge

Every official run requires the protocol-locked GPT-5.1 evaluation client. Configure it first:

- [Locked Evaluation Client](setup/eval-client.md)

### Agent under test

If you are evaluating an Azure AI Foundry model or OpenAI model with standard tool calling, use the built-in `StateBenchAgent` client:

- [Built-in StateBenchAgent Client](agents/builtin.md) (no code change needed; only configure env variables)

If you are evaluating models from a different provider or want to write a custom tool-calling agent, follow the instructions to extend the base classes:

- [Custom Client + Agent](USE_CUSTOM_CLIENT.md)

After you build the custom harness, come back to this guide and pass `--agent-class` and `--agent-client-class` in the run command below.

## 3. Run Tasks

Run one domain at a time:

```bash
uv run python -m state_bench.scripts.run_batch \
  --domain <domain> \
  --agent-model-name <model-name> \
  --num-runs 5 \
  --num-workers <parallel-workers> \
  --output-dir outputs/<domain>/
```

If your agent model uses a reportable reasoning level, add:

```bash
  --agent-model-reasoning-level <reasoning-level>
```

For a custom client + agent, add:

```bash
  --agent-class <YourAgent> \
  --agent-client-class <YourClient>
```

Use these values:

| Argument | Value |
| --- | --- |
| `--domain` | `travel`, `customer_support`, or `shopping_assistant` |
| `--agent-model-name` | The model name to report in trajectories and metrics, such as `gpt-5.1` or `claude-sonnet-4.5` |
| `--agent-model-reasoning-level` | Optional reasoning level, such as `low`, `medium`, or `high`; omit if not applicable |
| `--num-runs` | `5` for official submissions |
| `--num-workers` | Parallel task workers; tune for your provider rate limits |
| `--output-dir` | `outputs/<domain>/` for the standard layout |

`run_batch` writes scored trajectories under:

```text
outputs/<domain>/run1/<task_id>.json
outputs/<domain>/run2/<task_id>.json
...
outputs/<domain>/run5/<task_id>.json
```

For the full CLI reference and worker guidance, see [run_batch](eval/run-batch.md).

## 4. Report Cost Per Task

Cost reporting is optional but strongly encouraged. Add pricing flags to `run_batch` so STATE-Bench can compute average cost per task:

```bash
  --agent-input-cost-per-1m <input-price> \
  --agent-output-cost-per-1m <output-price> \
  --agent-cached-input-cost-per-1m <cached-input-price>
```

The cached-input flag is optional. Details: [Reporting Avg. Cost Per Task](eval/cost-reporting.md).

## 5. Compute Metrics

After a domain finishes, produce its standardized metrics file:

```bash
uv run python -m state_bench.scripts.compute_metrics \
  --domain <domain> \
  --results-dir outputs/<domain>/ \
  --num-runs 5 \
  --output-dir outputs/<domain>/
```

Metrics default to the protocol test split and fail if any expected test task is missing or unscored. Details: [Compute Metrics](eval/compute-metrics.md).

Repeat the run and metrics steps for `travel`, `customer_support`, and `shopping_assistant` for a complete submission.

## 6. Submit

Package the scored trajectories and metrics for each completed domain, then open a submission issue. Details: [Submit Results](submit.md).

## Official Run Settings

For protocol-compliant submissions:

- use the locked GPT-5.1 simulator and judge client,
- do not edit simulator prompts, judge prompts, domain tools, task files, environment files, or protocol files,
- run `--num-runs 5`,
- compute metrics with the same number of runs,
- include `metrics.json` and scored trajectories for each submitted domain.
