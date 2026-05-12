# Run Benchmark

This guide is for external users running the locked STATE-Bench benchmark. The active protocol is defined in `state_bench/configs/eval_protocols/state_bench_v0.4.4_gpt51.json`; it fixes the tasks, splits, user simulator prompt, judge prompts, API version, and required simulator, judge, and agent model so results are comparable across submissions. The current protocol requires GPT-5.1 for the user simulator, judge, and `StateBenchAgent` test trajectories.

The workflow is to extract procedural learnings from the provided train trajectories, then run a `StateBenchAgent` subclass on the test split with a `retrieve_learnings(query, top_k)` tool. Finally, score the test trajectories with the locked judge and submit the scored outputs and metrics.

NOTE: Use the checked-in tasks, splits, and provided train trajectories as fixed benchmark inputs for official runs.

## Locked Evaluation Client

Set the locked GPT-5.1 evaluation client used by both the user simulator and judge in your `.env` file:

```bash
STATE_BENCH_EVAL_ENDPOINT="https://your-gpt51-resource.openai.azure.com"
STATE_BENCH_EVAL_DEPLOYMENTS="<your gpt 5.1 deployment name>"
# Optional. If omitted, Azure token auth is tried.
# STATE_BENCH_EVAL_API_KEY="<your gpt 5.1 resource api key>"
```

The user simulator and judge deployments must point to GPT-5.1 for the current protocol. Deployment names can vary by resource. If `STATE_BENCH_EVAL_API_KEY` is omitted, the client tries Azure token auth through local CLI credentials and `DefaultAzureCredential`.

## Install

```bash
uv sync
```

Copy `.env.example` to `.env` and fill only the sections you need.

## StateBenchAgent Client

`StateBenchAgent` is the official STATE-Bench agent loop. It uses your configured GPT-5.1 agent client, the benchmark domain tools, and the locked prompt protocol to generate test trajectories. Set one of these client configurations before running the test split.

For official runs, the configured agent deployment or model must be GPT-5.1. STATE-Bench owns cost accounting for the locked model and reads prices from `state_bench/configs/pricing.yaml`; no model or pricing fields are needed from submitters.

For Azure OpenAI:

```bash
STATE_BENCH_AGENT_ENDPOINT="https://your-agent-resource.openai.azure.com"
STATE_BENCH_AGENT_DEPLOYMENTS="<your gpt 5.1 agent deployment name>"
# Optional. If omitted, Azure token auth is tried.
STATE_BENCH_AGENT_API_KEY="<your gpt 5.1 agent resource api key>"
STATE_BENCH_AGENT_API_VERSION="2025-03-01-preview"
```

For OpenAI API:

```bash
STATE_BENCH_AGENT_PROVIDER="openai"
STATE_BENCH_AGENT_MODEL="gpt-5.1"
OPENAI_API_KEY="<your OpenAI API key>"
```

For multiple Azure OpenAI deployments, use a comma-separated list:

```bash
STATE_BENCH_AGENT_DEPLOYMENTS="gpt51-deployment-a, gpt51-deployment-b"
```

For OpenAI API, use `gpt-5.1`. Parallelism comes from concurrent API calls to that model, controlled by `--num-workers`.

`--num-workers <parallel workers>` controls how many benchmark tasks run in parallel. For Azure OpenAI, a good starting point is 2x the number of configured deployments. For OpenAI API, set it according to your account/project rate limits. Start high (e.g. 10) and decrease if you see throttling.

Cost per task is computed from provider-reported token usage using the locked GPT-5.1 pricing in `state_bench/configs/pricing.yaml`.

## Step 1: [Training] Build Procedural Learnings

Use the provided train trajectories as the input to your learning pipeline. They are stored under:

```bash
datasets/train_task_trajectories/<domain>/<task_id>.json
```

Create a repo-root `agents/` directory and add a `StateBenchAgent` subclass. Your subclass needs two custom methods: `build_learnings()` for training-time extraction and `retrieve_learnings()` for test-time retrieval.

`build_learnings(trajectories_dir, output_path)` runs before the benchmark test split. It should read the provided train trajectories for one domain, extract whatever procedural knowledge your method uses, and write that artifact to `output_path`. The artifact format is up to you. It can be JSON, a vector index, a database, or any local file that `retrieve_learnings()` will use to retrieve relevant learnings later.

`retrieve_learnings(query, top_k)` runs during the locked test trajectories. STATE-Bench exposes this method to the agent as the fixed model-callable tool `retrieve_learnings(query, top_k)`. For a given `query`, it should load or query the artifact produced by `build_learnings()`, retrieve the top `top_k` relevant learnings, and return them as `list[str]`.

A minimal example is below. Replace both the extraction logic and retrieval/ranking logic with your own implementation.

```python
# agents/my_memory_agent.py
import json
from pathlib import Path

from state_bench.agents.state_bench import StateBenchAgent


class MyMemoryAgent(StateBenchAgent):
    learnings_path = Path("outputs/learnings.json")

    @staticmethod
    def build_learnings(trajectories_dir: str | Path, output_path: str | Path | None = None) -> list[str]:
        if output_path is None:
            output_path = MyMemoryAgent.learnings_path
        else:
            output_path = Path(output_path)
            MyMemoryAgent.learnings_path = output_path

        trajectories = [path.read_text() for path in sorted(Path(trajectories_dir).glob("*.json"))]

        # PUT YOUR CUSTOM LEARNING EXTRACTION LOGIC HERE.
        learnings = [
            "Summarize one reusable procedure learned from a training trajectory."
        ]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(learnings, indent=2) + "\n")
        return learnings

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        learnings = json.loads(self.learnings_path.read_text())
        # PUT YOUR CUSTOM RETRIEVAL/RANKING LOGIC HERE.
        return learnings[:top_k]
```

Call your extractor on the provided train trajectories:

```python
from agents.my_memory_agent import MyMemoryAgent

MyMemoryAgent.build_learnings("datasets/train_task_trajectories/travel", "outputs/travel/learnings.json")
```


## Step 2: [Evaluation] Run Test Trajectories

Run the test split with `--agent-class`. STATE-Bench loads the class from repo-root `agents/`, adds the fixed `retrieve_learnings(query, top_k)` tool, and instructs the agent to call it before substantive task answers. It also scores each trajectory inline with the locked judge. Do not edit the locked base prompt, judge prompts, or benchmark domain tools.

Use one of these domain names for `--domain`: `travel`, `customer_support`, `shopping_assistant`.

```bash
# Fixed by the benchmark: --num-runs 5 and --retrieve-learnings-top-k 3.
uv run python -m state_bench.scripts.run_batch \
  --domain <domain> \
  --split test \
  --agent-class MyMemoryAgent \
  --num-runs 5 \
  --retrieve-learnings-top-k 3 \
  --num-workers <parallel workers> \
  --output-dir outputs/<domain>/test_trajectories
```

The output is scored trajectories from `outputs/<domain>/test_trajectories/run1/<task_id>.json` through `outputs/<domain>/test_trajectories/run5/<task_id>.json`.

Agent cost metadata is written with the protocol model and the checked-in pricing file; no model or price flags are needed for official runs.

## Step 3: Compute Metrics

```bash
uv run python -m state_bench.scripts.compute_metrics \
  --domain <domain> \
  --results-dir outputs/<domain>/test_trajectories \
  --num-runs 5 \
  --save-filepath outputs/<domain>/metrics.json
```

Metrics default to the protocol `test` split and fail if any expected test task is missing or unscored. For local partial analysis only, add `--ignore-missing-runs`; use `--split all` only when you intentionally want every JSON in the run directories included.

Repeat Steps 1-3 for every protocol domain.

## Step 4: Submit Results

Create `outputs.zip` containing the scored trajectories and metrics for each completed domain:

- `outputs/<domain>/test_trajectories/`
- `outputs/<domain>/metrics.json`, which includes the evaluation protocol ID and standardized public metrics

Submit results by opening a GitHub issue in this repository. Attach `outputs.zip` to the issue if it is within GitHub's upload limit; otherwise, include a download link to the archive. Include brief details of your method, plus links to any relevant paper, GitHub repository, or project page. After verification, accepted results will be uploaded to the official leaderboard. Official comparisons are grouped by the protocol ID stamped into the trajectory and metrics metadata.
