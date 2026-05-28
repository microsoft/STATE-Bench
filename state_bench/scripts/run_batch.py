"""Run tasks in parallel and write scored trajectories by default.

Usage:
    uv run python -m state_bench.scripts.run_batch --domain travel --num-runs 2
"""

import argparse
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from state_bench.agents.base import AgentPricing, BaseAgent
from state_bench.agents.loader import load_root_agent_class, load_root_client_class
from state_bench.agents.state_bench import StateBenchAgent
from state_bench.client import (
    BaseLLMClient,
    LLMClient,
    PooledLLMClient,
    build_llm_client,
    build_locked_judge_client,
    build_user_sim_client,
)
from state_bench.domain import DomainConfig, get_domain_config
from state_bench.env_loader import load_task_environment
from state_bench.orchestrator import run_task
from state_bench.paths import domain_tasks_dir
from state_bench.protocol import load_default_protocol, load_split_task_ids
from state_bench.schemas import TaskDefinition
from state_bench.scoring import TaskRequirementsJudge, UXQualityJudge
from state_bench.scripts.score import score_one


def _build_run_dirs(base_output: Path, run_indices: list[int]) -> dict[int, Path]:
    return {run_idx: base_output / f"run{run_idx}" for run_idx in run_indices}


def _parse_task_ids(raw_value: str) -> list[str]:
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _resolve_task_files(tasks_dir: Path, task_ids: list[str]) -> list[Path]:
    task_files: list[Path] = []
    missing: list[str] = []
    for task_id in task_ids:
        task_file = tasks_dir / f"{task_id}.json"
        if task_file.exists():
            task_files.append(task_file)
        else:
            missing.append(task_id)

    if missing:
        available = sorted(path.stem for path in tasks_dir.glob("*.json"))
        preview = ", ".join(available[:20])
        if len(available) > 20:
            preview += f", ... ({len(available)} total)"
        raise ValueError(f"task ID(s) not found: {', '.join(missing)}. Available task IDs: {preview or '<none>'}")

    return task_files


def _arg_was_provided(argv: list[str], flag: str) -> bool:
    return flag in argv


def _validate_agent_client_args(args: argparse.Namespace, argv: list[str]) -> None:
    custom_agent_requested = bool(args.agent_class)
    custom_client_requested = bool(args.agent_client_class)
    if custom_client_requested and not custom_agent_requested:
        raise ValueError("--agent-client-class requires --agent-class.")
    if custom_client_requested and (
        _arg_was_provided(argv, "--agent-provider") or _arg_was_provided(argv, "--agent-api-key-var")
    ):
        raise ValueError(
            "--agent-provider and --agent-api-key-var are only valid with the built-in client. "
            "Custom clients should read their own configuration in from_env()."
        )


def _build_agent_model_metadata(args: argparse.Namespace) -> dict[str, str | None]:
    model_name = (args.agent_model_name or "").strip()
    if not model_name:
        raise ValueError("--agent-model-name is required")
    reasoning_level = args.agent_model_reasoning_level
    if isinstance(reasoning_level, str):
        reasoning_level = reasoning_level.strip() or None
    return {"model_name": model_name, "reasoning_level": reasoning_level}


def _build_agent_pricing(args: argparse.Namespace) -> AgentPricing | None:
    model_name = (args.agent_model_name or "").strip()
    pricing_values = [
        args.agent_input_cost_per_1m,
        args.agent_output_cost_per_1m,
        args.agent_cached_input_cost_per_1m,
    ]
    if all(value is None for value in pricing_values):
        return None

    missing = [
        flag
        for flag, value in [
            ("--agent-input-cost-per-1m", args.agent_input_cost_per_1m),
            ("--agent-output-cost-per-1m", args.agent_output_cost_per_1m),
        ]
        if value is None
    ]
    if missing:
        raise ValueError("agent pricing requires " + ", ".join(missing))
    pricing = AgentPricing(
        model_name=model_name,
        input_cost_per_1m_tokens=args.agent_input_cost_per_1m,
        output_cost_per_1m_tokens=args.agent_output_cost_per_1m,
        cached_input_cost_per_1m_tokens=args.agent_cached_input_cost_per_1m,
    )
    pricing.validate()
    return pricing


def _run_single(
    task_file: Path,
    client: BaseLLMClient | None,
    simulator_client: LLMClient | PooledLLMClient | None,
    output_dir: Path,
    domain: DomainConfig,
    max_attempts: int,
    protocol=None,
    agent_pricing: AgentPricing | None = None,
    agent_model: dict[str, str | None] | None = None,
    agent_class: type[BaseAgent] | None = None,
    retrieve_learnings_top_k: int = 3,
    task_requirements_judge: TaskRequirementsJudge | None = None,
    ux_judge: UXQualityJudge | None = None,
    agent_reasoning_effort: str | None = None,
) -> dict:
    task = TaskDefinition.load(task_file)
    user_id = task.user_id
    if not user_id:
        return {"task_id": task.task_id, "status": "ERR", "error": "no user_id"}

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            env_data, _env_path = load_task_environment(domain, task)

            metadata = {}
            if protocol is not None:
                metadata.update(protocol.simulator_metadata(domain.name))
                metadata["agent_name"] = (agent_class or StateBenchAgent).__name__
                if agent_model is not None:
                    metadata["agent_model"] = agent_model
                if agent_pricing is not None:
                    metadata["agent_pricing"] = agent_pricing.to_dict()

            traj = run_task(
                task,
                env_data,
                user_id,
                client,
                domain=domain,
                agent=None,
                env=None,
                trajectory_metadata=metadata,
                simulator_client=simulator_client,
                agent_pricing=agent_pricing,
                agent_class=agent_class,
                retrieve_learnings_top_k=retrieve_learnings_top_k,
                agent_reasoning_effort=agent_reasoning_effort,
            )

            out_path = output_dir / f"{task.task_id}.json"
            traj.save(out_path)

            result = {"task_id": task.task_id, "status": "OK"}
            if task_requirements_judge is not None or ux_judge is not None:
                score_result = score_one(
                    out_path,
                    domain_tasks_dir(domain.name),
                    task_requirements_judge,
                    ux_judge,
                    out_path,
                    protocol,
                    domain.name,
                )
                result["scoring_status"] = score_result.get("status")
                if score_result.get("status") == "ERR":
                    result["scoring_error"] = score_result.get("error", "unknown scoring error")
                if "ux_score" in score_result:
                    result["ux_score"] = score_result["ux_score"]

            if traj.token_usage is not None:
                result["token_usage"] = traj.token_usage.to_dict()
                result["cost_usd"] = traj.token_usage.total_cost_usd
            if attempt > 1:
                result["attempts"] = attempt
            return result
        except Exception as e:
            last_error = {
                "task_id": task.task_id,
                "status": "ERR",
                "attempts": attempt,
                "error": str(e)[:200],
                "traceback": "".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:],
            }
            if attempt < max_attempts:
                time.sleep(min(2 * attempt, 5))

    return last_error or {"task_id": task.task_id, "status": "ERR", "error": "unknown error"}


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run benchmark tasks")
    parser.add_argument("--domain", type=str, default="travel", help="Domain name (default: travel)")
    parser.add_argument(
        "--num-workers", "--workers", dest="workers", type=int, default=None, help="Number of parallel task workers"
    )
    parser.add_argument("--tasks", type=str, default=None, help="Comma-separated task IDs")
    parser.add_argument(
        "--split",
        type=str,
        default="all",
        choices=["all", "test"],
        help="Task split to run (default: all)",
    )
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (default: outputs/<domain>)")
    parser.add_argument("--num-runs", type=int, default=1, help="Number of runs (default: 1)")
    parser.add_argument(
        "--num-runs-idx-start",
        type=int,
        default=1,
        help="Starting run index for output directories (default: 1)",
    )
    parser.add_argument(
        "--agent-class",
        type=str,
        default=None,
        help=(
            "Agent class name under repo-root agents/. StateBenchAgent subclasses can use the built-in "
            "client; fully custom providers also require --agent-client-class."
        ),
    )
    parser.add_argument(
        "--agent-client-class",
        type=str,
        default=None,
        help="BaseLLMClient subclass name under repo-root clients/. Required for fully custom provider clients.",
    )
    parser.add_argument(
        "--retrieve-learnings-top-k",
        type=int,
        default=3,
        help="Benchmark-fixed retrieve_learnings top_k value (default: 3)",
    )
    parser.add_argument(
        "--retry-attempts", type=int, default=3, help="Worker retry attempts for transient runtime errors"
    )
    parser.add_argument(
        "--agent-provider",
        type=str,
        default=os.environ.get("STATE_BENCH_AGENT_PROVIDER", "azure_openai"),
        choices=["azure_openai", "openai"],
        help="Provider for the built-in agent client",
    )
    parser.add_argument(
        "--agent-api-key-var",
        type=str,
        default=os.environ.get("STATE_BENCH_AGENT_API_KEY_VAR", "STATE_BENCH_AGENT_API_KEY"),
        help="API key env var for the built-in agent client",
    )
    parser.add_argument(
        "--agent-model-name",
        type=str,
        required=True,
        help="Agent model name reported in trajectories and metrics",
    )
    parser.add_argument(
        "--agent-model-reasoning-level",
        type=str,
        default=None,
        help="Optional agent model reasoning level reported in trajectories and metrics",
    )
    parser.add_argument(
        "--agent-input-cost-per-1m",
        type=float,
        default=None,
        help="Override agent input token cost in USD per 1M tokens",
    )
    parser.add_argument(
        "--agent-output-cost-per-1m",
        type=float,
        default=None,
        help="Override agent output token cost in USD per 1M tokens",
    )
    parser.add_argument(
        "--agent-cached-input-cost-per-1m",
        type=float,
        default=None,
        help="Override cached-input token cost in USD per 1M tokens",
    )
    parser.add_argument(
        "--score",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Score each trajectory inline immediately after generation (default: true). Use --no-score for local unscored runs.",
    )
    parser.add_argument(
        "--score-reasoning-effort",
        type=str,
        default=None,
        choices=["low", "medium", "high"],
        help="Reasoning effort for inline judge scoring (default: protocol judge setting)",
    )
    args = parser.parse_args()
    if args.num_runs < 1:
        parser.error("--num-runs must be >= 1")
    if args.num_runs_idx_start < 1:
        parser.error("--num-runs-idx-start must be >= 1")
    if args.workers is not None and args.workers < 1:
        parser.error("--num-workers must be >= 1")
    if args.retrieve_learnings_top_k < 1:
        parser.error("--retrieve-learnings-top-k must be >= 1")
    if args.tasks and args.split != "all":
        parser.error("--tasks and --split are mutually exclusive")
    try:
        _validate_agent_client_args(args, sys.argv[1:])
    except ValueError as exc:
        parser.error(str(exc))
    domain = get_domain_config(args.domain)
    protocol = load_default_protocol()
    try:
        agent_model = _build_agent_model_metadata(args)
        agent_pricing = _build_agent_pricing(args)
    except ValueError as exc:
        parser.error(str(exc))
    protocol_errors = protocol.validate_prompt_hashes()
    if protocol_errors:
        parser.error("Protocol prompt validation failed:\n" + "\n".join(protocol_errors))
    if args.domain not in protocol.domains:
        parser.error(f"Domain {args.domain!r} is not part of protocol {protocol.protocol_id}")
    tasks_dir = domain_tasks_dir(args.domain)
    base_output = Path(args.output_dir) if args.output_dir else Path(f"outputs/{args.domain}")
    agent_class = load_root_agent_class(args.agent_class) if args.agent_class else None
    if agent_class is not None and args.agent_client_class is None and not issubclass(agent_class, StateBenchAgent):
        parser.error("--agent-class without --agent-client-class must be a StateBenchAgent subclass")

    if args.agent_client_class:
        client_class = load_root_client_class(args.agent_client_class)
        client = client_class.from_env()
        if not isinstance(client, BaseLLMClient):
            raise TypeError(f"{args.agent_client_class}.from_env() must return a BaseLLMClient")
    else:
        client = build_llm_client(
            provider=args.agent_provider,
            api_key_var=args.agent_api_key_var,
        )
    user_sim_client = build_user_sim_client()
    task_requirements_judge = None
    ux_judge = None
    if args.score:
        judge_client = build_locked_judge_client()
        score_reasoning_effort = args.score_reasoning_effort or protocol.judge_reasoning_effort
        task_requirements_judge = TaskRequirementsJudge(
            client=judge_client,
            prompts_dir=domain.prompts_dir,
            system_prompt=domain.judge_system_prompt,
            reasoning_effort=score_reasoning_effort,
        )
        ux_judge = UXQualityJudge(
            client=judge_client,
            prompts_dir=domain.prompts_dir,
            system_prompt=domain.judge_system_prompt,
            reasoning_effort=score_reasoning_effort,
        )
    if args.workers is None:
        args.workers = 1
    if args.tasks:
        task_ids = _parse_task_ids(args.tasks)
        if not task_ids:
            parser.error("--tasks must include at least one task ID")
        try:
            task_files = _resolve_task_files(tasks_dir, task_ids)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        task_ids = load_split_task_ids(args.domain, args.split, protocol.split_version)
        try:
            task_files = _resolve_task_files(tasks_dir, task_ids)
        except ValueError as exc:
            parser.error(str(exc))

    agent_name = (agent_class or StateBenchAgent).__name__
    print(f"Agent: {agent_name}")
    if agent_pricing is not None:
        print(
            f"Agent pricing: {agent_pricing.model_name} "
            f"input=${agent_pricing.input_cost_per_1m_tokens}/1M "
            f"output=${agent_pricing.output_cost_per_1m_tokens}/1M "
            f"source={agent_pricing.source}"
        )
    else:
        print("Agent pricing: not provided (token counts recorded without cost)")
    if args.score:
        print(f"Scoring: inline (reasoning_effort={args.score_reasoning_effort or protocol.judge_reasoning_effort})")
    else:
        print("Scoring: off (--no-score set; use state_bench.scripts.score for local scoring)")

    total_start = time.time()
    run_indices = list(range(args.num_runs_idx_start, args.num_runs_idx_start + args.num_runs))
    run_dirs = _build_run_dirs(base_output, run_indices)
    for run_dir in run_dirs.values():
        run_dir.mkdir(parents=True, exist_ok=True)

    work_items = [(run_idx, tf) for run_idx in run_indices for tf in task_files]

    print(f"\n{'#' * 60}")
    print(
        f"# Runs {run_indices[0]}..{run_indices[-1]} together — {len(task_files)} tasks/run, "
        f"{len(work_items)} total jobs, {args.workers} workers"
    )
    print(f"# Scoring: {'inline' if args.score else 'off'}")
    print(f"{'#' * 60}")

    start = time.time()
    results = []
    run_results: dict[int, list[dict]] = {run_idx: [] for run_idx in run_indices}
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                _run_single,
                tf,
                client,
                user_sim_client,
                run_dirs[run_idx],
                domain,
                args.retry_attempts,
                protocol,
                agent_pricing,
                agent_model,
                agent_class,
                args.retrieve_learnings_top_k,
                task_requirements_judge,
                ux_judge,
                (agent_model or {}).get("reasoning_level"),
            ): (run_idx, tf)
            for run_idx, tf in work_items
        }
        for future in as_completed(futures):
            run_idx, _tf = futures[future]
            r = future.result()
            r["run_idx"] = run_idx
            results.append(r)
            run_results[run_idx].append(r)
            suffix = ""
            if "cost_usd" in r:
                suffix += f" | cost=${r['cost_usd']:.4f}"
            if r.get("scoring_status"):
                suffix += f" | score={r['scoring_status']}"
            if "ux_score" in r:
                suffix += f" | ux={r['ux_score']}"
            if r.get("scoring_error"):
                suffix += f" | scoring_error={r['scoring_error']}"
            print(f"  [{len(results)}/{len(futures)}] run{run_idx} {r['task_id']}: {r['status']}{suffix}")

    elapsed = time.time() - start
    for run_idx in run_indices:
        run_items = run_results[run_idx]
        ok = sum(1 for r in run_items if r["status"] == "OK")
        errors = sum(1 for r in run_items if r["status"] == "ERR")
        print(f"\n  Run {run_idx} done — {ok} ok, {errors} err")
        costed = [r["cost_usd"] for r in run_items if "cost_usd" in r]
        if costed:
            print(f"    Mean cost: ${sum(costed) / len(costed):.4f}")
        scored_inline = [r for r in run_items if r.get("scoring_status") == "OK"]
        score_errors = [r for r in run_items if r.get("scoring_status") == "ERR"]
        if scored_inline:
            ux_scored = [r["ux_score"] for r in scored_inline if "ux_score" in r]
            if ux_scored:
                print(f"    Inline scored: {len(scored_inline)}; mean UX: {sum(ux_scored) / len(ux_scored):.2f}")
            else:
                print(f"    Inline scored: {len(scored_inline)}")
        if score_errors:
            print(f"    Inline scoring errors: {len(score_errors)}")
        if errors:
            for r in run_items:
                if r["status"] == "ERR":
                    print(f"    ERROR {r['task_id']}: {r.get('error', '?')} (attempts={r.get('attempts', '?')})")
                    if r.get("traceback"):
                        print(r["traceback"])

    total_elapsed = time.time() - total_start
    print(f"\nAll runs complete in {total_elapsed:.0f}s (worker wall time {elapsed:.0f}s)")
    print(f"Trajectories in: {base_output}/run*/")
    if args.score:
        print(
            f"Metrics with: uv run python -m state_bench.scripts.compute_metrics --domain {args.domain} "
            f"--results-dir {base_output} "
            f"--num-runs {args.num_runs} --num-runs-idx-start {args.num_runs_idx_start} "
            f"--save-filepath {base_output / 'metrics.json'}"
        )
    else:
        print(
            f"Score with: uv run python -m state_bench.scripts.score --domain {args.domain} "
            f"--results-dir {base_output} "
            f"--num-runs {args.num_runs} --num-runs-idx-start {args.num_runs_idx_start}"
        )


if __name__ == "__main__":
    main()
