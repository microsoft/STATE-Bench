# Memory Hook — Custom `BaseAgent`

Use this hook when you are running the [Memory Track](../../MEMORY_TRACK.md) with a custom client + agent from [Use a Custom Client + Agent](../../USE_CUSTOM_CLIENT.md).

A custom `BaseAgent` does not benefit from `StateBenchAgent`'s automatic injection. Instead, expose a read-only retrieval tool by overriding `memory_tool_schemas()` and `memory_tool_handlers()`.

```python
from pathlib import Path

from state_bench.agents.base import BaseAgent


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

The harness will:

- merge your memory tool schemas into the `tools` argument passed to `generate_next_turn()`,
- execute `retrieve_learnings` calls returned by your agent using your handler,
- validate the return type as `list[str]` and reject other return types,
- force `top_k` to the run-configured `--retrieve-learnings-top-k`.

**Memory tools must not mutate benchmark state.** Domain tools are still owned and executed by STATE-Bench.

## Building the artifact

Train trajectories are available under:

```
datasets/train_task_trajectories/<domain>/<task_id>.json
```

The artifact format is up to you — JSON, a vector index, a database, or any local file your custom agent can read at inference time. STATE-Bench only calls the inference-time tool handlers your agent exposes.

## Next step

Return to [Memory Track](../../MEMORY_TRACK.md) and continue with the run steps using `--agent-class MyAgent --agent-client-class MyLLMClient --retrieve-learnings-top-k 3`.
