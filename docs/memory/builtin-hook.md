# Memory Hook — Built-in `StateBenchAgent`

Use this hook when you are running the [Agent Learning Track](../AGENT_LEARNING_TRACK.md) with the built-in standard tool-calling `StateBenchAgent`.

Expose your learnings by subclassing `StateBenchAgent` and implementing `retrieve_learnings(query, top_k=3) -> list[str]`. Place the file under the repo-root `agents/` folder so the harness can discover it by class name.

```python
# agents/my_memory_agent.py
import json
from pathlib import Path

from state_bench.agents.state_bench import StateBenchAgent


class MyMemoryAgent(StateBenchAgent):
    # The artifact can be JSON, a vector index, a database, or anything your
    # implementation can read at inference time. This is just an example.
    learnings_path = Path("<path_to_learnings.json>")

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        learnings = json.loads(self.learnings_path.read_text())
        # Replace this with your retrieval/ranking logic.
        return learnings[:top_k]
```

When a subclass defines `retrieve_learnings`, `StateBenchAgent` automatically:

- appends a procedural-retrieval instruction to the system prompt,
- adds `retrieve_learnings` to the tool schema the model sees,
- routes the model's `retrieve_learnings` calls to your implementation,
- forces `top_k` to the benchmark-fixed value (`--retrieve-learnings-top-k`, default `3`) regardless of what the model requests, and
- validates the return type as `list[str]`.

## Building the artifact

Train trajectories are available under:

```
datasets/train_task_trajectories/<domain>/<task_id>.json
```

Generation of the learnings artifact is **fully user-owned**. STATE-Bench only requires that the inference-time `retrieve_learnings` method return `list[str]`. Optionally, you may implement a static `build_learnings(train_trajectories_dir, output_path)` on your subclass for offline extraction; the benchmark does not prescribe the artifact format.

## Next step

Return to [Agent Learning Track](../AGENT_LEARNING_TRACK.md) and continue with the run steps using `--agent-class MyMemoryAgent --retrieve-learnings-top-k 3`.
