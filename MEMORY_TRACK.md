# Memory Track

The STATE-Bench memory track measures whether an agent can learn reusable procedures from past enterprise interactions and apply them reliably to new, similar-but-not-identical workflows. It is a specialized evaluation built on top of the same task loop, domain tools, simulator, and judges used by the main benchmark — but with a locked train/test split and a benchmark-managed `retrieve_learnings` hook so submissions can be compared fairly.

If you only want to evaluate an agent end-to-end on STATE-Bench's enterprise tasks, you do not need this track. See the main [README](README.md) and [RUN_BENCHMARK.md](RUN_BENCHMARK.md).

## What the track measures

The official memory score asks one question: *do procedural learnings extracted from past trajectories improve task completion, reliability, UX, and cost on held-out test tasks?* It reports the same four metrics as the main benchmark (Task Completion Rate, `pass^5` Reliability, UX Score, Cost Per Task), but on the locked 50-task-per-domain test set, with five runs per task under the canonical evaluation protocol (`state_bench_v0.4.4_gpt51`).

## Train/test split

Each domain ships a locked split of 100 train tasks and 50 test tasks, defined in `state_bench/domains/<domain>/splits/train_test.json`:

| Domain | Train Trajectories | Test Tasks |
| --- | ---: | ---: |
| Travel | 100 | 50 |
| Customer Support | 100 | 50 |
| Shopping Assistant | 100 | 50 |

Public train trajectories are checked in under `datasets/train_task_trajectories/<domain>/*.json` and are the only inputs allowed for offline learning extraction. Test task definitions live under `state_bench/domains/<domain>/tasks/`; test trajectories are generated at evaluation time, not shipped.

## How memory plugs in

STATE-Bench owns the benchmark plumbing — the fixed test tasks, domain tools, user simulator, judge prompts, scoring protocol, model pricing, and the default `StateBenchAgent` loop. You bring the memory logic and expose it through a single method on a `StateBenchAgent` subclass:

```python
# agents/my_memory_agent.py
from state_bench.agents.state_bench import StateBenchAgent

class MyMemoryAgent(StateBenchAgent):
    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        ...
```

When a subclass defines `retrieve_learnings`, `StateBenchAgent` automatically:

- appends a procedural-retrieval instruction to the system prompt,
- adds `retrieve_learnings` to the tool schema the model sees,
- routes the model's `retrieve_learnings` calls to your implementation,
- forces `top_k` to the benchmark-fixed value (`--retrieve-learnings-top-k`, default `3`) regardless of what the model requests, and
- validates the return type as `list[str]`.

You may additionally implement a static `build_learnings(train_trajectories_dir, output_path)` for offline learning extraction; the benchmark does not prescribe the artifact format.

## Running the memory track

The full step-by-step workflow — credential setup, building learnings from train trajectories, running locked test trajectories with `run_batch.py`, scoring, computing metrics, and submitting results — lives in [RUN_BENCHMARK.md](RUN_BENCHMARK.md). Use `--agent-class <YourSubclass>` to wire your subclass into the locked GPT-5.1 protocol.

## Ground rules

- Memory extraction may only use the public train trajectories under `datasets/train_task_trajectories/`. Do not use the test task definitions, test environments, or any out-of-distribution oracle.
- The benchmark protocol (`state_bench/configs/eval_protocols/state_bench_v0.4.4_gpt51.json`) locks the split, `num_runs=5`, official model `gpt-5.1`, simulator and judge prompt hashes, and judge reasoning effort. Submissions outside this protocol are not protocol-compliant.
- `retrieve_learnings` must return `list[str]`. The harness rejects other return types.
- Embedding cost accounting is not currently included in the official public metrics.
