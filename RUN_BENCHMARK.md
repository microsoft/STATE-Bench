# Run Benchmark

This guide is for evaluating OpenAI / Azure OpenAI GPT models using the OpenAI SDK. For non-OpenAI models or other LLM providers, follow [USE_CUSTOM_CLIENT.md](USE_CUSTOM_CLIENT.md) instead.

You can run this benchmark in two modes:

- **Test Agentic Memory:** Use the train trajectories in Step 1 to generate procedural learnings before evaluating on the test set.
- **General Agent Benchmark:** Evaluate your model or agent directly on the test set by skipping Step 1.

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

The current evaluation protocol is defined [HERE](state_bench/configs/eval_protocols/state_bench_v0.4.4_gpt51.json). It fixes the tasks, splits, user simulator prompt, judge prompts, and required simulator and judge model so results are comparable across submissions. The current protocol requires GPT-5.1 model for the user simulator and judge. The agent model is user-configurable.

NOTE: all the prompts are hashed. If you change any prompt file, the hash will change and the evaluation will throw an error. This ensures that all runs use the same prompts.

```bash
STATE_BENCH_EVAL_ENDPOINT="https://your-gpt51-resource.openai.azure.com"
STATE_BENCH_EVAL_DEPLOYMENTS="<your gpt 5.1 deployment name>"
# Optional. If omitted, Azure token auth is tried.
# STATE_BENCH_EVAL_API_KEY="<your gpt 5.1 resource api key>"
```

Deployment names can vary by resource. If `STATE_BENCH_EVAL_API_KEY` is omitted, the client tries Azure token auth through local CLI credentials and `DefaultAzureCredential`.

### StateBenchAgent Client

`StateBenchAgent` is the provided agent loop. It uses the built-in OpenAI/Azure OpenAI v1 client to call the Responses API with benchmark domain tools and the locked prompt protocol.

For Azure OpenAI:

```bash
STATE_BENCH_AGENT_ENDPOINT="https://your-agent-resource.openai.azure.com"
STATE_BENCH_AGENT_DEPLOYMENTS="<your agent deployment name>"
# Optional. If omitted, Azure token auth is tried.
STATE_BENCH_AGENT_API_KEY="<your agent resource api key>"
```

For OpenAI API:

```bash
STATE_BENCH_AGENT_PROVIDER="openai"
STATE_BENCH_AGENT_MODEL="<your OpenAI model>"
OPENAI_API_KEY="<your OpenAI API key>"
```

For multiple Azure OpenAI deployments, use a comma-separated list:

```bash
STATE_BENCH_AGENT_DEPLOYMENTS="deployment-a, deployment-b"
```

For OpenAI API, parallelism comes from concurrent API calls to that model, controlled by `--num-workers`.

## Step 1: Build Procedural Learnings From Train Trajectories

Use the provided task trajectories (100 per domain) as the input to your learning or memory pipeline. They are stored under:

```bash
datasets/train_task_trajectories/<domain>/<task_id>.json
```

Procedural learning generation is fully user-owned; STATE-Bench only requires the inference-time retrieval method to consume these learnings.

Expose your learnings by subclassing `StateBenchAgent` and implementing `retrieve_learnings(query, top_k=3) -> list[str]`. Put this custom agent file under the repo-root `agents/` folder.

STATE-Bench automatically discovers this agent and adds `retrieve_learnings` to the list of available tools during inference.

A minimal example is below. Replace the loading and retrieval logic with your method.

```python
# agents/my_memory_agent.py
import json
from pathlib import Path

from state_bench.agents.state_bench import StateBenchAgent


class MyMemoryAgent(StateBenchAgent):
    # It need not be a JSON file; this is just an example.
    # Use whatever storage and retrieval method you like,
    # as long as `retrieve_learnings` returns a list of strings.
    learnings_path = Path("<path_to_learnings.json>")

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        learnings = json.loads(self.learnings_path.read_text())
        # Replace this with your retrieval/ranking logic.
        return learnings[:top_k]
```


## Step 2: Evaluate on Test Tasks

```bash
uv run python -m state_bench.scripts.run_batch \
  --domain <domain> \
  --agent-class <MyMemoryAgent> \
  --agent-model-name <model-name> \
  --agent-model-reasoning-level <reasoning-level> \
  --num-runs 5 \
  --retrieve-learnings-top-k 3 \
  --num-workers <parallel workers> \
  --output-dir outputs/<domain>/test_trajectories
```

Arguments:

- `--domain`: Benchmark domain to run: `travel`, `customer_support`, or `shopping_assistant`.
- `--agent-class`: [Optional] Name of the custom agent built in Step 1 `StateBenchAgent` subclass under repo-root `agents/`. If not provided, the default `StateBenchAgent` with no `retrieve_learnings` tool is used.
- `--agent-model-name`: Required model name reported in trajectories and the submitted `metrics.json`. E.g. `gpt-5.1`.
- `--agent-model-reasoning-level`: Reasoning level reported in trajectories and `metrics.json` when the agent model uses one. E.g. `medium`. This is important for grouping results in the leaderboard.
- `--num-runs`: Number of runs per task. Set to `5` for official submissions.
- `--retrieve-learnings-top-k`: Benchmark-fixed maximum number of learnings returned by `retrieve_learnings()`. Set to `3` for official submissions.
- `--num-workers`: Number of benchmark tasks to run in parallel. Tune this for your provider rate limits. See suggestion below.
- `--output-dir`: Directory where scored trajectories are written.

A good starting point for `--num-workers` is the number of parallel API calls your agent model can handle without hitting rate limits or timeouts. For OpenAI API, this is often around 10. For Azure OpenAI, it depends on your resource limits and number of deployments (we suggest starting with 2x the number of deployments)


### Reporting Avg. Cost Per Task

One metric in the benchmark is the average cost to run a task. We strongly encourage benchmark users to provide pricing in the `run_batch.py` command.

Use these pricing flags:

```bash
--agent-input-cost-per-1m <input-price> \
--agent-output-cost-per-1m <output-price>
```

If your provider reports cached input tokens and has a separate cached-input rate, also pass:

```bash
--agent-cached-input-cost-per-1m <cached-input-price>
```

## Step 3: Compute Metrics

```bash
uv run python -m state_bench.scripts.compute_metrics \
  --domain <domain> \
  --results-dir outputs/<domain>/test_trajectories \
  --num-runs 5 \
  --save-filepath outputs/<domain>/metrics.json
```

Metrics default to the protocol test split and fail if any expected test task is missing or unscored. For local partial analysis only, add `--ignore-missing-runs`.

Repeat Steps 1-3 for every protocol domain.

## Submit Results

Create `outputs.zip` containing the scored trajectories and metrics for each completed domain:

- `outputs/<domain>/test_trajectories/`
- `outputs/<domain>/metrics.json`, which includes the evaluation protocol ID and standardized public metrics

Submit results by opening a GitHub issue in this repository. Attach `outputs.zip` to the issue if it is within GitHub's upload limit; otherwise, include a download link to the archive. Include brief details of your method, plus links to any relevant paper, GitHub repository, or project page. After verification, accepted results will be uploaded to the official leaderboard.
