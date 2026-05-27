# Memory Hook — Custom `BaseAgent`

Use this hook when you are running the [Agent Learning Track](../AGENT_LEARNING_TRACK.md) with a custom client + agent from [Use a Custom Client + Agent](../USE_CUSTOM_CLIENT.md).

A custom `BaseAgent` does not benefit from `StateBenchAgent`'s automatic injection. Instead, expose a read-only retrieval tool by overriding `memory_tool_schemas()` and `memory_tool_handlers()`.

```python
from pathlib import Path

from state_bench.agents.base import BaseAgent


class MyAgent(BaseAgent):
    learnings_path = Path("outputs/learnings.json")

    def __init__(self, client, system_prompt, tools, tool_handlers, runtime_context=None, retrieve_learnings_top_k=3, **kwargs):
        super().__init__(runtime_context=runtime_context)
        self.client = client
        self.retrieve_learnings_top_k = retrieve_learnings_top_k

    def memory_tool_schemas(self):
        return [
            {
                "type": "function",
                "name": "retrieve_learnings",
                "description": "Retrieve procedural learnings relevant to the current task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "minimum": 1},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]

    def memory_tool_handlers(self):
        return {"retrieve_learnings": self.handle_retrieve_learnings}

    def handle_retrieve_learnings(self, args):
        query = args["query"]
        top_k = min(int(args.get("top_k", self.retrieve_learnings_top_k)), self.retrieve_learnings_top_k)
        learnings = self.retrieve_learnings(query, top_k=top_k)
        if not isinstance(learnings, list) or not all(isinstance(item, str) for item in learnings):
            raise TypeError("retrieve_learnings must return list[str]")
        return learnings

    def retrieve_learnings(self, query: str, top_k: int = 3) -> list[str]:
        # Load/query your artifact and return relevant learnings.
        raise NotImplementedError
```

The harness will:

- merge your memory tool schemas into the `tools` argument passed to `generate_next_turn()`,
- execute `retrieve_learnings` calls returned by your agent using your handler,
- append the retrieval result to the canonical conversation as a tool result.

For custom `BaseAgent` implementations, your handler owns validation and `top_k` enforcement. Keep the schema and handler above unless you have a provider-specific reason to adapt it.

**Memory tools must not mutate benchmark state.** Domain tools are still owned and executed by STATE-Bench.

## Building the artifact

Train trajectories are available under:

```
datasets/train_task_trajectories/<domain>/<task_id>.json
```

The artifact format is up to you — JSON, a vector index, a database, or any local file your custom agent can read at inference time. STATE-Bench only calls the inference-time tool handlers your agent exposes.

## Next step

Return to [Agent Learning Track](../AGENT_LEARNING_TRACK.md) and continue with the run steps using `--agent-class MyAgent --agent-client-class MyLLMClient --retrieve-learnings-top-k 3`.
