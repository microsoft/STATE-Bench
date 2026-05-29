"""Tests for score integration with deterministic state requirements."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from state_bench.scripts.score import score_one


def test_score_writes_state_requirement_fields(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    task_path = tasks_dir / "1-cancel_economy_domestic.json"
    task_path.write_text(
        json.dumps(
            {
                "task_id": "1-cancel_economy_domestic",
                "task_summary": "Task summary",
                "state_requirements": [
                    {
                        "entity_type": "bookings",
                        "record_key": "BK-1000",
                        "field": "status",
                        "expected_value": "cancelled",
                    }
                ],
                "task_requirements": [
                    {"id": "r1", "kind": "must", "requirement": "warn about the connection", "evidence": "conversation"}
                ],
                "user_id": "user_001",
                "opening_message": "hello",
                "user_simulator": {
                    "personality": "cooperative",
                    "user_sim_context": "User simulator context",
                    "known_info": [],
                    "unknown_info": [],
                    "task_rules": [],
                },
            }
        )
    )

    traj_path = tmp_path / "traj.json"
    traj_path.write_text(
        json.dumps(
            {
                "task_id": "1-cancel_economy_domestic",
                "conversation": [{"role": "user", "content": "cancel it"}],
                "state_diff": {
                    "created": {},
                    "modified": {"bookings": {"BK-1000": {"status": {"old": "confirmed", "new": "cancelled"}}}},
                    "deleted": {},
                },
            }
        )
    )

    task_requirements_judge = MagicMock()
    task_requirements_judge.evaluate.return_value = type(
        "TaskReqResult",
        (),
        {
            "score": 1,
            "details": [{"id": "r1", "passed": True}],
        },
    )()

    output_path = tmp_path / "out.json"
    result = score_one(traj_path, tasks_dir, task_requirements_judge, None, output_path)
    saved = json.loads(output_path.read_text())

    assert result["status"] == "OK"
    assert saved["state_requirements_met"] == 1
    assert "matched the saved state_diff" in saved["state_requirements_reasoning"]
    assert saved["task_requirements_met"] == 1
    assert "task_requirements_reasoning" not in saved
    assert saved["state_requirements_gt"] == [
        {
            "entity_type": "bookings",
            "record_key": "BK-1000",
            "field": "status",
            "expected_value": "cancelled",
        }
    ]
    assert "task_requirements_gt" not in saved
    assert saved["task_requirements_details"] == [
        {
            "id": "r1",
            "kind": "must",
            "requirement": "warn about the connection",
            "evidence": "conversation",
            "passed": True,
        }
    ]
    assert saved["task_completion_pass"] == 1


def test_score_can_write_ux_fields_only(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "1-cancel_economy_domestic.json").write_text(
        json.dumps(
            {
                "task_id": "1-cancel_economy_domestic",
                "task_summary": "Task summary",
                "user_id": "user_001",
                "opening_message": "hello",
                "user_simulator": {
                    "personality": "cooperative",
                    "user_sim_context": "User simulator context",
                    "known_info": [],
                    "unknown_info": [],
                    "task_rules": [],
                },
            }
        )
    )

    traj_path = tmp_path / "traj.json"
    traj_path.write_text(
        json.dumps(
            {
                "task_id": "1-cancel_economy_domestic",
                "conversation": [{"role": "user", "content": "cancel it"}],
                "state_diff": {"created": {}, "modified": {}, "deleted": {}},
            }
        )
    )

    ux_judge = MagicMock()
    ux_judge.evaluate.return_value = MagicMock(
        user_control=4,
        friction=3,
        situational_awareness=5,
        communication_quality=4,
        intent_alignment=3,
        ux_score=3.8,
        reasoning="ux ok",
    )

    output_path = tmp_path / "out.json"
    result = score_one(traj_path, tasks_dir, None, ux_judge, output_path)
    saved = json.loads(output_path.read_text())

    assert result["status"] == "OK"
    assert result["ux_score"] == 3.8
    assert saved["ux_user_control"] == 4
    assert saved["ux_friction"] == 3
    assert saved["ux_situational_awareness"] == 5
    assert saved["ux_communication_quality"] == 4
    assert saved["ux_intent_alignment"] == 3
    assert saved["ux_score"] == 3.8
    assert saved["ux_reasoning"] == "ux ok"


def test_score_cli_requires_results_dir():
    """`score.py` must reject invocation without --results-dir."""
    proc = subprocess.run(
        [sys.executable, "-m", "state_bench.scripts.score", "--domain", "travel", "--num-runs", "5"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "--results-dir" in proc.stderr


def test_score_one_overwrites_in_place(tmp_path: Path):
    """When output_path == traj_path, score_one rewrites the same file."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "t1.json").write_text(
        json.dumps(
            {
                "task_id": "t1",
                "task_summary": "s",
                "user_id": "u",
                "opening_message": "hi",
                "user_simulator": {
                    "personality": "cooperative",
                    "user_sim_context": "ctx",
                    "known_info": [],
                    "unknown_info": [],
                    "task_rules": [],
                },
            }
        )
    )

    traj_path = tmp_path / "traj.json"
    traj_path.write_text(
        json.dumps(
            {
                "task_id": "t1",
                "conversation": [{"role": "user", "content": "hi"}],
                "state_diff": {"created": {}, "modified": {}, "deleted": {}},
            }
        )
    )

    ux_judge = MagicMock()
    ux_judge.evaluate.return_value = MagicMock(
        user_control=5,
        friction=5,
        situational_awareness=5,
        communication_quality=5,
        intent_alignment=5,
        ux_score=5.0,
        reasoning="ok",
    )

    result = score_one(traj_path, tasks_dir, None, ux_judge, traj_path)

    assert result["status"] == "OK"
    saved = json.loads(traj_path.read_text())
    assert saved["task_id"] == "t1"
    assert saved["ux_score"] == 5.0
    assert saved["conversation"] == [{"role": "user", "content": "hi"}]
