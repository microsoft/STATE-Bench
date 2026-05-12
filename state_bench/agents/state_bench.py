"""StateBenchAgent — default agent with no memory.

Ships with the benchmark as the baseline. Calls the LLM with tools
directly, implementing the standard Responses API tool-calling loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from state_bench.agents.base import Agent, AgentRuntimeContext
from state_bench.client import LLMClient, PooledLLMClient

RETRIEVE_LEARNINGS_TOOL_NAME = "retrieve_learnings"

RETRIEVE_LEARNINGS_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "name": RETRIEVE_LEARNINGS_TOOL_NAME,
    "description": "Retrieve procedural learnings relevant to the current task and conversation.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "A concise search query describing the current user request, task context, and relevant constraints.",
            },
            "top_k": {
                "type": "integer",
                "description": "Benchmark-fixed maximum number of learnings to retrieve. Use 3.",
                "minimum": 1,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

RETRIEVAL_SYSTEM_INSTRUCTION = """# Procedural Learning Retrieval
You have access to `retrieve_learnings(query, top_k)` for procedural learnings from past user interactions. These learnings capture patterns that helped on prior tasks, such as tool-use order, policy checks, consent steps, and common failure modes. Before your first substantive answer for a task, call `retrieve_learnings` with a concise query based on the user's request, domain, task context, and relevant conversation facts. Use the benchmark-fixed `top_k` value provided in the run configuration. You can call the tool again if later turns require further procedural guidance. Apply retrieved learnings as guidance for how to proceed, but only when they are relevant and consistent with domain tools, tool results, and policies."""


class StateBenchAgent(Agent):
    """Default agent with no memory. Calls the LLM with tools directly.

    This is the baseline agent used when no custom agent is provided.
    It implements the standard Responses API tool-calling loop: send the
    conversation, execute any tool calls, feed results back, repeat until
    the model produces a final text response.
    """

    def __init__(
        self,
        client: LLMClient | PooledLLMClient,
        system_prompt: str,
        tools: list[dict[str, Any]],
        tool_handlers: dict[str, Callable],
        runtime_context: AgentRuntimeContext | None = None,
        retrieve_learnings_top_k: int = 3,
    ):
        super().__init__(runtime_context=runtime_context)
        if not isinstance(client, (LLMClient, PooledLLMClient)):
            raise TypeError("StateBenchAgent requires state_bench.client.LLMClient or PooledLLMClient")
        if (
            not isinstance(retrieve_learnings_top_k, int)
            or isinstance(retrieve_learnings_top_k, bool)
            or retrieve_learnings_top_k < 1
        ):
            raise ValueError("retrieve_learnings_top_k must be an integer >= 1")
        self.client = client
        self.retrieve_learnings_top_k = retrieve_learnings_top_k
        self.retrieval_enabled = self._has_retrieve_learnings()
        self.system_prompt = (
            self._with_retrieval_instruction(system_prompt) if self.retrieval_enabled else system_prompt
        )
        self.tools = self._with_retrieval_tool(tools) if self.retrieval_enabled else tools
        self.tool_handlers = self._with_retrieval_handler(tool_handlers) if self.retrieval_enabled else tool_handlers

    @staticmethod
    def build_learnings(train_trajectories_dir: str | Path, output_path: str | Path | None = None) -> list[str]:
        """Optional user hook for building learnings after train trajectories."""
        raise NotImplementedError("Override build_learnings() in a StateBenchAgent subclass to build learnings")

    def _has_retrieve_learnings(self) -> bool:
        return callable(getattr(self, "retrieve_learnings", None))

    def _with_retrieval_instruction(self, system_prompt: str) -> str:
        return system_prompt.rstrip() + "\n\n" + RETRIEVAL_SYSTEM_INSTRUCTION

    def _with_retrieval_tool(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if any(tool.get("name") == RETRIEVE_LEARNINGS_TOOL_NAME for tool in tools):
            raise ValueError(f"Domain tool name conflicts with {RETRIEVE_LEARNINGS_TOOL_NAME!r}")
        return [*tools, RETRIEVE_LEARNINGS_TOOL_SCHEMA]

    def _with_retrieval_handler(self, tool_handlers: dict[str, Callable]) -> dict[str, Callable]:
        if RETRIEVE_LEARNINGS_TOOL_NAME in tool_handlers:
            raise ValueError(f"Domain tool handler conflicts with {RETRIEVE_LEARNINGS_TOOL_NAME!r}")
        return {**tool_handlers, RETRIEVE_LEARNINGS_TOOL_NAME: self._handle_retrieve_learnings_tool}

    def _handle_retrieve_learnings_tool(self, args: dict[str, Any]) -> dict[str, list[str]]:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("retrieve_learnings requires a non-empty string query")
        requested_top_k = args.get("top_k", self.retrieve_learnings_top_k)
        if not isinstance(requested_top_k, int) or isinstance(requested_top_k, bool) or requested_top_k < 1:
            raise ValueError("retrieve_learnings top_k must be an integer >= 1")
        top_k = self.retrieve_learnings_top_k
        retrieve = getattr(self, "retrieve_learnings", None)
        if not callable(retrieve):
            raise RuntimeError("retrieve_learnings is not configured")
        learnings = retrieve(query, top_k=top_k)
        if not isinstance(learnings, list) or any(not isinstance(item, str) for item in learnings):
            raise TypeError("retrieve_learnings() must return list[str]")
        return {"learnings": learnings}

    def act(self, conversation: list[Any]) -> tuple[str, list[dict[str, Any]], list[Any]]:
        """Run one turn: LLM call + tool execution loop.

        Uses a pinned deployment for pooled clients so previous_response_id
        chaining stays on one deployment. Single LLMClient instances are used
        directly.
        """
        all_tool_calls: list[dict[str, Any]] = []
        raw_items: list[Any] = []
        prepared_conversation = self.prepare_conversation(conversation)

        pinned = self.client
        pinned_context = self.client.pinned() if isinstance(self.client, PooledLLMClient) else None
        if pinned_context is not None:
            pinned = pinned_context.__enter__()
        try:
            response = pinned.complete_with_tools(
                instructions=self.system_prompt,
                input=prepared_conversation,
                tools=self.tools,
            )
            if response.usage:
                self.total_output_tokens += response.usage.output_tokens
                self.add_response_usage(response.usage, category="agent_turn")

            # Process tool calls in a loop
            while True:
                tool_calls = [item for item in response.output if item.type == "function_call"]
                if not tool_calls:
                    break

                raw_items.extend(response.output)

                tool_results: list[dict[str, Any]] = []
                for tc in tool_calls:
                    args = json.loads(tc.arguments)
                    handler = self.tool_handlers.get(tc.name)

                    if handler is None:
                        output = json.dumps({"error": f"Unknown tool: {tc.name}"})
                    else:
                        result = handler(args)
                        all_tool_calls.append(
                            {
                                "name": tc.name,
                                "arguments": args,
                                "result": result,
                            }
                        )
                        output = json.dumps(result, ensure_ascii=False)

                    tool_result_item = {
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": output,
                    }
                    tool_results.append(tool_result_item)
                    raw_items.append(tool_result_item)

                # Follow-up call with tool results — same deployment via pinned client
                response = pinned.complete_with_tools(
                    instructions=self.system_prompt,
                    input=tool_results,
                    tools=self.tools,
                    previous_response_id=response.id,
                )
                if response.usage:
                    self.total_output_tokens += response.usage.output_tokens
                    self.add_response_usage(response.usage, category="agent_turn")
        finally:
            if pinned_context is not None:
                pinned_context.__exit__(None, None, None)

        # Add final response output
        raw_items.extend(response.output)

        return response.output_text or "", all_tool_calls, raw_items
