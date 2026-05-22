# run_batch

`run_batch.py` runs the protocol test tasks and scores each trajectory inline with the locked judge. Do not edit the locked base prompt, judge prompts, benchmark domain tools, or protocol file for official runs.

## Which flags are required for my path?

The exact required flags depend on your agent path and whether you are running the Memory Track.

| Path | `--agent-class` | `--agent-client-class` | `--retrieve-learnings-top-k` |
| --- | --- | --- | --- |
| Main Track, OOTB (StateBenchAgent on Azure AI Foundry/OpenAI) | omitted | omitted | n/a |
| Main Track, custom client + agent | required (your `BaseAgent` subclass) | required (your `BaseLLMClient` subclass) | n/a |
| Memory Track, OOTB | required (your `StateBenchAgent` subclass) | omitted | `3` (official) |
| Memory Track, custom | required (your `BaseAgent` subclass) | required (your `BaseLLMClient` subclass) | `3` (official) |

> Passing `--agent-client-class` without `--agent-class` is rejected. Passing `--agent-class` without `--agent-client-class` uses the built-in Azure AI Foundry/OpenAI client and requires a `StateBenchAgent` subclass.

## Invocation

```bash
uv run python -m state_bench.scripts.run_batch \
  --domain <domain> \
  --agent-model-name <model-name> \
  --num-runs 5 \
  --num-workers <parallel workers> \
  --output-dir outputs/<domain>/test_trajectories
```

If your agent model uses a reportable reasoning level, add `--agent-model-reasoning-level <reasoning-level>`.

Add `--agent-class`, `--agent-client-class`, and `--retrieve-learnings-top-k` per the matrix above. For cost reporting, also add the pricing flags from [docs/eval/cost-reporting.md](cost-reporting.md).

## Arguments

- `--domain` — Benchmark domain to run: `travel`, `customer_support`, or `shopping_assistant`.
- `--agent-class` — Agent class name under repo-root `agents/`. See matrix above.
- `--agent-client-class` — `BaseLLMClient` subclass name under repo-root `clients/`. See matrix above.
- `--agent-model-name` — **Required.** Model name reported in trajectories and the submitted `metrics.json` (e.g., `gpt-5.1`, `claude-sonnet-4.5`).
- `--agent-model-reasoning-level` — Reasoning level reported in trajectories and `metrics.json` when the agent model uses one (e.g., `medium`). Used to group results on the leaderboard.
- `--num-runs` — Number of runs per task. Set to `5` for official submissions.
- `--retrieve-learnings-top-k` — Benchmark-fixed maximum number of learnings returned by `retrieve_learnings()`. Set to `3` for official submissions. Memory Track only.
- `--num-workers` — Number of benchmark tasks to run in parallel. Tune for your provider rate limits.
- `--output-dir` — Directory where scored trajectories are written.

## Tuning `--num-workers`

A good starting point is the number of parallel API calls your agent model can handle without hitting rate limits or timeouts.

- **OpenAI API**: often around `10`.
- **Azure AI Foundry / Azure OpenAI**: depends on your resource limits and number of deployments. Try `2 × <number of deployments>` and adjust.
- **Custom providers**: start conservative and raise until you see throttling.

## Output layout

Scored trajectories are written to:

```
outputs/<domain>/test_trajectories/run1/<task_id>.json
outputs/<domain>/test_trajectories/run2/<task_id>.json
...
outputs/<domain>/test_trajectories/run5/<task_id>.json
```

Proceed to [docs/eval/compute-metrics.md](compute-metrics.md).
