"""Orchestrator — runs a multi-turn agent-user conversation with tool execution.

The orchestrator:
1. Creates a deep copy of the environment for the run
2. Runs the agent-user-tool loop (agent.act() per turn)
3. Computes efficiency metrics (deterministic)
4. Returns a Trajectory without completion or UX scores; use the scoring scripts separately

Domain-agnostic: all domain-specific behavior is provided via DomainConfig.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from state_bench.agents.base import Agent, AgentPricing, AgentRuntimeContext, AgentToolCallRequest, AgentTurnResponse
from state_bench.client import LLMClient, PooledLLMClient
from state_bench.domain import DomainConfig
from state_bench.schemas import (
    StateDiff,
    TaskDefinition,
    Trajectory,
)
from state_bench.scoring import compute_efficiency
from state_bench.simulator import UserSimulator

logger = logging.getLogger(__name__)


def _normalize_agent_turn_response(response: AgentTurnResponse | dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(response, AgentTurnResponse):
        text = response.text
        raw_tool_calls = response.tool_calls
    elif isinstance(response, dict):
        text = str(response.get("text", "") or "")
        raw_tool_calls = response.get("tool_calls", []) or []
    else:
        raise TypeError("generate_next_turn() must return AgentTurnResponse or dict")

    tool_calls: list[dict[str, Any]] = []
    for raw in raw_tool_calls:
        if isinstance(raw, AgentToolCallRequest):
            name = raw.name
            arguments = raw.arguments
        elif isinstance(raw, dict):
            name = raw.get("name")
            arguments = raw.get("arguments", {})
        else:
            raise TypeError("tool_calls must contain AgentToolCallRequest or dict items")
        if not isinstance(name, str) or not name:
            raise ValueError("tool call request missing non-empty name")
        if not isinstance(arguments, dict):
            raise ValueError(f"tool call {name!r} arguments must be a dict")
        tool_calls.append({"name": name, "arguments": arguments})
    return text, tool_calls


def _run_harness_executed_agent_turn(
    *,
    agent: Agent,
    system_prompt: str,
    conversation_full: list[dict[str, Any]],
    domain_tools: list[dict[str, Any]],
    domain_tool_handlers: dict[str, Any],
    max_tool_rounds: int = 8,
) -> tuple[str, list[dict[str, Any]]]:
    """Run one assistant turn while the benchmark executes allowed tools."""
    memory_tools = agent.memory_tool_schemas()
    memory_handlers = agent.memory_tool_handlers()
    tools = [*domain_tools, *memory_tools]
    handlers = {**domain_tool_handlers, **memory_handlers}
    allowed_names = set(handlers)

    turn_tool_calls: list[dict[str, Any]] = []
    working_conversation = agent.prepare_conversation(list(conversation_full))
    final_text = ""

    for _ in range(max_tool_rounds):
        response = agent.generate_next_turn(
            system_prompt=system_prompt,
            conversation=working_conversation,
            tools=tools,
        )
        text, requested_tool_calls = _normalize_agent_turn_response(response)
        final_text = text
        if not requested_tool_calls:
            return final_text, turn_tool_calls

        executed_tool_calls: list[dict[str, Any]] = []
        for request in requested_tool_calls:
            name = request["name"]
            arguments = request["arguments"]
            if name not in allowed_names:
                raise ValueError(f"Agent requested disallowed tool: {name}")
            result = handlers[name](arguments)
            record = {"name": name, "arguments": arguments, "result": result}
            executed_tool_calls.append(record)
            turn_tool_calls.append(record)

        working_conversation.append(
            {
                "role": "assistant",
                "content": text,
                "tool_calls": executed_tool_calls,
            }
        )
        working_conversation.append(
            {
                "role": "tool",
                "content": executed_tool_calls,
            }
        )

    raise RuntimeError(f"Agent exceeded max tool rounds ({max_tool_rounds})")


def run_task(
    task: TaskDefinition,
    env_data: Any,
    user_id: str,
    client: LLMClient | PooledLLMClient | None,
    domain: DomainConfig,
    agent: Agent | None = None,
    env: Any | None = None,
    trajectory_metadata: dict[str, Any] | None = None,
    simulator_client: LLMClient | PooledLLMClient | None = None,
    agent_pricing: AgentPricing | None = None,
    agent_class: type[Agent] | None = None,
    retrieve_learnings_top_k: int = 3,
) -> Trajectory:
    """Run a single task and return the trajectory.

    Generates the conversation and computes efficiency metrics.
    Does NOT run completion or UX judges; use state_bench.scripts.score for scoring.

    Args:
        task: The task definition.
        env_data: The environment data (will be deep-copied). Type varies by domain.
        user_id: The user to run the task for.
        client: Optional LLM client for StateBenchAgent and non-protocol simulator runs.
        domain: Domain configuration providing all domain-specific behavior.
        agent: Agent to evaluate. If None, uses StateBenchAgent (no memory).
        env: Optional prebuilt environment instance. When provided, the same env must
            also back the agent's tool handlers.

    Returns:
        A Trajectory with conversation, tool calls, state diff, and efficiency metrics.
    """
    t0 = time.monotonic()

    now = task.now
    if env is None:
        # Deep copy environment for this run
        env_copy = env_data.deep_copy()
        env = domain.environment_class(env_copy, now=now)
    # Build agent (default: StateBenchAgent with no memory)
    agent_system_prompt = domain.agent_system_prompt.format(now=now, user_id=user_id)
    if agent is None:
        from state_bench.agents.state_bench import StateBenchAgent

        if client is None:
            raise ValueError("StateBenchAgent requires a benchmark LLM client")
        resolved_agent_class = agent_class or StateBenchAgent
        runtime_context = AgentRuntimeContext(
            task_id=task.task_id,
            user_id=user_id,
            domain=domain.name,
            now=now,
            task_summary=task.task_summary,
            state_requirements=task.state_requirements,
            task_requirements=task.task_requirements,
            agent_pricing=agent_pricing,
        )
        agent = resolved_agent_class(
            client,
            agent_system_prompt,
            domain.tool_schemas,
            env.tool_handlers,
            runtime_context=runtime_context,
            retrieve_learnings_top_k=retrieve_learnings_top_k,
        )

    # Build simulator
    sim_prompt = domain.build_simulator_prompt(task, env_data, user_id)
    resolved_simulator_client = simulator_client or client
    if resolved_simulator_client is None:
        raise ValueError("User simulator requires simulator_client or benchmark LLM client")
    simulator = UserSimulator(resolved_simulator_client, sim_prompt)

    # Snapshot before the run
    db_before = env.get_full_snapshot()

    # Build conversation
    # `conversation` holds Responses API input items: message dicts + raw output items (function_call,
    # function_call_output). This is the stateless input-array chaining pattern — the full conversation
    # is passed on each turn. We do NOT use previous_response_id across turns because the PooledLLMClient
    # may route different turns to different endpoints that don't share server-side state.
    opening = task.opening_message
    conversation: list[Any] = [{"role": "user", "content": opening}]
    conversation_full: list[dict[str, Any]] = [{"role": "user", "content": opening}]
    all_tool_calls: list[dict[str, Any]] = []
    user_response: str = ""

    logger.info("Task: %s | User: %s | Now: %s", task.task_id, user_id, now)
    logger.info("User: %s", opening[:100])

    for turn in range(domain.max_agent_turns):
        # Build input for this turn — full conversation for stateless chaining
        if turn > 0:
            conversation.append({"role": "user", "content": user_response})

        # Agent turn
        if agent.uses_harness_tool_execution():
            agent_text, tool_calls = _run_harness_executed_agent_turn(
                agent=agent,
                system_prompt=agent_system_prompt,
                conversation_full=conversation_full,
                domain_tools=domain.tool_schemas,
                domain_tool_handlers=env.tool_handlers,
            )
            raw_items = [{"role": "assistant", "content": agent_text}]
        else:
            agent_text, tool_calls, raw_items = agent.act(conversation)

        all_tool_calls.extend(tool_calls)
        conversation.extend(raw_items)  # Append raw output items for legacy stateless chaining
        conversation_full.append(
            {
                "role": "assistant",
                "content": agent_text,
                "tool_calls": tool_calls if tool_calls else None,
            }
        )

        tc_names = [tc["name"] for tc in tool_calls]
        logger.info(
            "Turn %s: %s | %s", turn + 1, tc_names if tc_names else "no tools", agent_text[:80] if agent_text else ""
        )

        if turn < domain.max_agent_turns - 1:
            # User simulator responds
            user_response = simulator.respond(conversation_full)
            conversation_full.append({"role": "user", "content": user_response})
            logger.info("User: %s", user_response[:80])

            if domain.check_termination and domain.check_termination(user_response):
                break

    # Snapshot after
    db_after = env.get_full_snapshot()

    # --- Compute metrics (no judge — use score.py) ---
    state_diff = StateDiff.compute(db_before, db_after)
    efficiency = compute_efficiency(conversation_full, all_tool_calls)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info("TRAJECTORY (%ss):", elapsed)
    if efficiency:
        logger.info("Turns: %s", efficiency.turns)
        logger.info("Tool Calls: %s", efficiency.tool_calls)
        logger.info("Tool Errors: %s", efficiency.tool_errors)
        logger.info("Redundant Calls: %s", efficiency.redundant_calls)
    if state_diff:
        logger.info("State Diff: %s", "empty" if state_diff.is_empty() else "changes detected")

    trajectory = Trajectory(
        task_id=task.task_id,
        user_id=user_id,
        task_summary=task.task_summary,
        conversation=conversation_full,
        state_diff=state_diff,
        efficiency=efficiency,
        token_usage=agent.token_usage,
        metadata=trajectory_metadata or {},
    )
    agent.ingest_trajectory(trajectory)
    return trajectory
