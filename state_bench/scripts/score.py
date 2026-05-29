"""Score existing trajectories with the current metric judges.

Reads trajectory JSONs, runs the official completion and UX judges,
and updates the same trajectory files in place by default. Does not re-run agents.

Usage:
    uv run python -m state_bench.scripts.score --domain travel --num-runs 5 --results-dir outputs/travel
    uv run python -m state_bench.scripts.score --domain travel --num-runs 5 --results-dir outputs/travel --reasoning-effort high
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

from state_bench.client import build_locked_judge_client
from state_bench.domain import get_domain_config
from state_bench.paths import domain_tasks_dir
from state_bench.protocol import load_default_protocol
from state_bench.schemas import StateDiff, TaskDefinition
from state_bench.scoring import (
    TaskRequirementsJudge,
    UXQualityJudge,
    combine_task_completion,
    evaluate_state_requirements,
)


def _enrich_task_requirement_details(task: TaskDefinition, details: list[dict]) -> list[dict]:
    requirements_by_id = {str(req.get("id")): req for req in task.task_requirements or [] if req.get("id") is not None}
    enriched: list[dict] = []
    for detail in details:
        if not isinstance(detail, dict):
            enriched.append(detail)
            continue
        req = requirements_by_id.get(str(detail.get("id")))
        if req is None:
            enriched.append(detail)
            continue
        merged = {
            "id": detail.get("id"),
            "kind": req.get("kind"),
            "requirement": req.get("requirement"),
            "evidence": req.get("evidence"),
        }
        for key, value in detail.items():
            if key != "id":
                merged[key] = value
        enriched.append(merged)
    return enriched


def score_one(
    traj_path: Path,
    tasks_dir: Path,
    task_requirements_judge: TaskRequirementsJudge | None,
    ux_judge: UXQualityJudge | None,
    output_path: Path,
    protocol=None,
    domain_name: str | None = None,
) -> dict:
    """Score a single trajectory using the official metric judges."""
    traj = json.loads(traj_path.read_text())
    tid = traj["task_id"]

    # Load the task definition
    task_file = tasks_dir / f"{tid}.json"
    if not task_file.exists():
        return {"task_id": tid, "status": "ERR", "error": "task file not found"}
    task = TaskDefinition.load(task_file)

    # Reconstruct state_diff from trajectory
    sd_raw = traj.get("state_diff")
    if sd_raw is None:
        state_diff = StateDiff(created={}, modified={}, deleted={})
    elif isinstance(sd_raw, dict) and {"created", "modified", "deleted"}.issubset(sd_raw):
        state_diff = StateDiff(
            created=sd_raw.get("created", {}),
            modified=sd_raw.get("modified", {}),
            deleted=sd_raw.get("deleted", {}),
        )
    else:
        return {"task_id": tid, "status": "ERR", "error": "malformed state_diff in trajectory"}

    # Reconstruct tool_calls from conversation
    tool_calls = []
    for msg in traj.get("conversation", []):
        if msg.get("tool_calls"):
            tool_calls.extend(msg["tool_calls"])

    if task_requirements_judge is not None:
        state_result = evaluate_state_requirements(task, state_diff)
        task_result = task_requirements_judge.evaluate(task, traj["conversation"], tool_calls, state_diff)

        traj["state_requirements_gt"] = task.state_requirements
        traj["state_requirements_met"] = state_result.score if state_result else None
        traj["state_requirements_reasoning"] = state_result.reasoning if state_result else None
        traj["state_requirements_details"] = state_result.details if state_result else None
        traj.pop("task_requirements_gt", None)
        traj["task_requirements_met"] = task_result.score if task_result else None
        traj["task_requirements_details"] = (
            _enrich_task_requirement_details(task, task_result.details) if task_result else None
        )
        traj.pop("task_requirements_reasoning", None)
        traj["task_completion_pass"] = combine_task_completion(state_result, task_result)

    if ux_judge is not None:
        ux_result = ux_judge.evaluate(task, traj["conversation"], tool_calls)
        if ux_result is None:
            return {"task_id": tid, "status": "ERR", "error": "ux judge returned None"}
        for key in [
            "ux_consent",
            "ux_ease",
            "ux_discovery",
            "ux_information_quality",
            "ux_disambiguation",
        ]:
            traj.pop(key, None)
        traj["ux_user_control"] = ux_result.user_control
        traj["ux_friction"] = ux_result.friction
        traj["ux_situational_awareness"] = ux_result.situational_awareness
        traj["ux_communication_quality"] = ux_result.communication_quality
        traj["ux_intent_alignment"] = ux_result.intent_alignment
        traj["ux_score"] = round(ux_result.ux_score, 2)
        traj["ux_reasoning"] = ux_result.reasoning

    if protocol is not None:
        traj.update(protocol.judge_metadata(domain_name or ""))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(traj, indent=2, ensure_ascii=False) + "\n")

    out = {"task_id": tid, "status": "OK"}
    if ux_judge is not None:
        out["ux_score"] = traj.get("ux_score")
    return out


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Score existing trajectories with the official metric judges")
    parser.add_argument("--domain", type=str, required=True)
    parser.add_argument("--num-runs", type=int, default=5)
    parser.add_argument(
        "--num-runs-idx-start",
        type=int,
        default=1,
        help="Starting run index to score (default: 1)",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        required=True,
        help="Results dir containing run1/, run2/, ... Trajectories are scored in place.",
    )
    parser.add_argument("--reasoning-effort", type=str, default=None, choices=["low", "medium", "high"])
    parser.add_argument("--workers", type=int, default=25)
    args = parser.parse_args()
    if args.num_runs < 1:
        parser.error("--num-runs must be >= 1")
    if args.num_runs_idx_start < 1:
        parser.error("--num-runs-idx-start must be >= 1")
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    domain = get_domain_config(args.domain)
    protocol = load_default_protocol()
    protocol_errors = protocol.validate_prompt_hashes()
    if protocol_errors:
        parser.error("Protocol prompt validation failed:\n" + "\n".join(protocol_errors))
    if args.domain not in protocol.domains:
        parser.error(f"Domain {args.domain!r} is not part of protocol {protocol.protocol_id}")
    if args.num_runs != protocol.num_runs:
        print(
            f"WARNING: Protocol {protocol.protocol_id} expects --num-runs {protocol.num_runs}; "
            f"scoring with {args.num_runs} run(s) for local analysis. Results are NOT protocol-compliant.",
            file=sys.stderr,
        )
    tasks_dir = domain_tasks_dir(args.domain)
    results_dir = Path(args.results_dir)

    judge_client = build_locked_judge_client()

    # Default reasoning effort for shared judge traffic
    reasoning_effort = args.reasoning_effort or protocol.judge_reasoning_effort

    task_requirements_judge = TaskRequirementsJudge(
        client=judge_client,
        prompts_dir=domain.prompts_dir,
        system_prompt=domain.judge_system_prompt,
        reasoning_effort=reasoning_effort,
    )
    ux_judge = UXQualityJudge(
        client=judge_client,
        prompts_dir=domain.prompts_dir,
        system_prompt=domain.judge_system_prompt,
        reasoning_effort=reasoning_effort,
    )

    total_start = time.time()
    run_indices = list(range(args.num_runs_idx_start, args.num_runs_idx_start + args.num_runs))
    for run_idx in run_indices:
        run_dir = results_dir / f"run{run_idx}"
        if not run_dir.exists():
            print(f"WARNING: {run_dir} not found, skipping")
            continue

        traj_files = sorted(run_dir.glob("*.json"))
        print(f"\nRun {run_idx}: scoring {len(traj_files)} trajectories...")

        results = []
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    score_one,
                    tf,
                    tasks_dir,
                    task_requirements_judge,
                    ux_judge,
                    run_dir / tf.name,
                    protocol,
                    domain.name,
                ): tf
                for tf in traj_files
            }
            for future in as_completed(futures):
                r = future.result()
                results.append(r)
                score_str = ""
                if "ux_score" in r:
                    score_str += f" (ux={r['ux_score']})"
                print(f"  [{len(results)}/{len(futures)}] {r['task_id']}: {r['status']}{score_str}")

        errors = sum(1 for r in results if r["status"] == "ERR")
        task_completion_scored = sum(
            1 for r in results if r.get("status") == "OK" and task_requirements_judge is not None
        )
        ux_scored = [r for r in results if "ux_score" in r]
        summary = [f"err={errors}"]
        if task_completion_scored:
            summary.append(f"task_completion_scored={task_completion_scored}")
        if ux_scored:
            mean_ux = sum(r["ux_score"] for r in ux_scored) / len(ux_scored)
            summary.append(f"ux_scored={len(ux_scored)}")
            summary.append(f"mean_ux={mean_ux:.2f}")
        print(f"  Run {run_idx}: " + ", ".join(summary))

    elapsed = time.time() - total_start
    print(f"\nDone in {elapsed:.0f}s. Updated results in: {results_dir}/")
    print(
        f"Run: uv run python -m state_bench.scripts.compute_metrics --results-dir {results_dir} "
        f"--num-runs {args.num_runs} --num-runs-idx-start {args.num_runs_idx_start} "
        f"--save-filepath {results_dir / 'metrics.json'}"
    )


if __name__ == "__main__":
    main()
