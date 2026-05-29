"""Tests for canonical scoring helpers in state_bench.scoring."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from state_bench.schemas import (
    BinaryScore,
    StateDiff,
    TaskDefinition,
    TaskRequirementsScore,
    UserSimulatorConfig,
    UXQualityResult,
)
from state_bench.scoring import (
    TaskRequirementsJudge,
    UXQualityJudge,
    build_ux_prompt,
    combine_task_completion,
    evaluate_state_requirements,
    evaluate_task_requirements_empty,
)


def _make_task() -> TaskDefinition:
    """Create a minimal TaskDefinition for testing."""
    return TaskDefinition(
        task_id="test-task",
        task_summary="Task: Test task. Challenge: Test challenge. Outcome: Agent should do X.",
        user_id="user_001",
        now="2026-06-15T10:00:00",
        opening_message="Hello",
        user_simulator=UserSimulatorConfig(
            personality="cooperative",
            user_sim_context="User is trying to complete the task without knowing the hidden answer.",
            known_info=["user_id: user_001"],
            unknown_info=["fee amount"],
            task_rules=["End with [TASK_DONE]"],
        ),
    )


def _make_state_task(requirements: list[dict]) -> TaskDefinition:
    task = _make_task()
    task.state_requirements = requirements
    return task


class TestDeterministicStateRequirements:
    """Tests for structured state requirement matching."""

    def test_treats_missing_state_requirements_as_empty_requirements(self):
        task = _make_task()
        task.state_requirements = None

        result = evaluate_state_requirements(task, StateDiff())

        assert result == BinaryScore(
            score=1,
            reasoning="Task defines no required state changes and the saved state_diff is empty.",
        )

    def test_passes_for_explicit_no_write_task_with_empty_diff(self):
        task = _make_state_task([])

        result = evaluate_state_requirements(task, StateDiff())

        assert result == BinaryScore(
            score=1,
            reasoning="Task defines no required state changes and the saved state_diff is empty.",
        )

    def test_fails_for_explicit_no_write_task_with_non_empty_diff(self):
        task = _make_state_task([])

        result = evaluate_state_requirements(
            task,
            StateDiff(modified={"bookings": {"BK-1": {"status": {"old": "confirmed", "new": "cancelled"}}}}),
        )

        assert result == BinaryScore(
            score=0,
            reasoning="Task defines no required state changes but the saved state_diff is not empty.",
        )

    def test_passes_for_matching_modified_field(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-1", "field": "status", "expected_value": "cancelled"}]
        )
        diff = StateDiff(modified={"bookings": {"BK-1": {"status": {"old": "confirmed", "new": "cancelled"}}}})

        result = evaluate_state_requirements(task, diff)

        assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")

    def test_fails_when_unexpected_modified_field_is_present(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-1", "field": "status", "expected_value": "cancelled"}]
        )
        diff = StateDiff(
            modified={
                "bookings": {
                    "BK-1": {
                        "status": {"old": "confirmed", "new": "cancelled"},
                        "refund_amount": {"old": None, "new": 100},
                    }
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "unexpected_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "refund_amount", "value": 100}
            ]
        }

    def test_fails_when_unexpected_booking_configuration_change_is_present(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-1", "field": "flight_id", "expected_value": "UA200"}]
        )
        diff = StateDiff(
            modified={
                "bookings": {
                    "BK-1": {
                        "flight_id": {"old": "UA100", "new": "UA200"},
                        "cabin_class": {"old": "economy", "new": "business"},
                        "meal_preference": {"old": "standard", "new": "vegan"},
                    }
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "unexpected_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "cabin_class", "value": "business"},
                {"entity_type": "bookings", "record_key": "BK-1", "field": "meal_preference", "value": "vegan"},
            ]
        }

    def test_fails_for_under_specified_created_record(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-NEW", "field": "payment_method", "expected_value": "points"}]
        )
        diff = StateDiff(created={"bookings": {"BK-NEW": {"payment_method": "points", "status": "confirmed"}}})

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "unexpected_assertions": [
                {"entity_type": "bookings", "record_key": "BK-NEW", "field": "status", "value": "confirmed"}
            ]
        }

    def test_passes_for_fully_specified_created_record(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "bookings",
                    "record_key": "BK-NEW",
                    "field": "payment_method",
                    "expected_value": "points",
                },
                {"entity_type": "bookings", "record_key": "BK-NEW", "field": "status", "expected_value": "confirmed"},
            ]
        )
        diff = StateDiff(created={"bookings": {"BK-NEW": {"payment_method": "points", "status": "confirmed"}}})

        result = evaluate_state_requirements(task, diff)

        assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")

    def test_passes_for_created_record_matched_by_match_fields(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "bookings",
                    "match_fields": {"user_id": "user_005", "flight_id": "B6202"},
                    "expected_fields": {
                        "status": "confirmed",
                        "cabin_class": "economy",
                        "meal_preference": "vegan",
                    },
                }
            ]
        )
        diff = StateDiff(
            created={
                "bookings": {
                    "BK-2042": {
                        "user_id": "user_005",
                        "flight_id": "B6202",
                        "status": "confirmed",
                        "cabin_class": "economy",
                        "meal_preference": "vegan",
                    }
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")

    def test_match_fields_created_record_can_use_match_only_assertion(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "cart_items",
                    "match_fields": {
                        "customer_id": "shop_002",
                        "product_id": "SP-1001",
                        "gift_wrap": False,
                        "quantity": 1,
                    },
                    "expected_fields": {},
                }
            ]
        )
        diff = StateDiff(
            created={
                "cart_items": {
                    "CI-0001": {
                        "customer_id": "shop_002",
                        "product_id": "SP-1001",
                        "quantity": 1,
                        "gift_wrap": False,
                        "variant_id": None,
                    }
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")

    def test_match_fields_created_record_ignores_unspecified_extra_fields(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "cart_items",
                    "match_fields": {"customer_id": "shop_002", "product_id": "SP-1001"},
                    "expected_fields": {"quantity": 1, "gift_wrap": False},
                }
            ]
        )
        diff = StateDiff(
            created={
                "cart_items": {
                    "CI-0001": {
                        "customer_id": "shop_002",
                        "product_id": "SP-1001",
                        "quantity": 1,
                        "gift_wrap": False,
                        "variant_id": None,
                    }
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")

    def test_fails_when_created_record_match_fields_find_no_record(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "bookings",
                    "match_fields": {"user_id": "user_005", "flight_id": "B6202"},
                    "expected_fields": {"status": "confirmed"},
                }
            ]
        )
        diff = StateDiff(
            created={"bookings": {"BK-2042": {"user_id": "user_005", "flight_id": "UA200", "status": "confirmed"}}}
        )

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "unresolved_match_requirements": [
                {
                    "requirement": {
                        "entity_type": "bookings",
                        "match_fields": {"user_id": "user_005", "flight_id": "B6202"},
                        "expected_fields": {"status": "confirmed"},
                    },
                    "error": "match_fields resolved to zero or multiple records",
                    "match_count": 0,
                    "matched_record_keys": [],
                }
            ]
        }

    def test_fails_when_created_record_match_fields_are_ambiguous(self):
        task = _make_state_task(
            [
                {
                    "entity_type": "bookings",
                    "match_fields": {"user_id": "user_005"},
                    "expected_fields": {"status": "confirmed"},
                }
            ]
        )
        diff = StateDiff(
            created={
                "bookings": {
                    "BK-2042": {"user_id": "user_005", "flight_id": "B6202", "status": "confirmed"},
                    "BK-2043": {"user_id": "user_005", "flight_id": "UA200", "status": "confirmed"},
                }
            }
        )

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "unresolved_match_requirements": [
                {
                    "requirement": {
                        "entity_type": "bookings",
                        "match_fields": {"user_id": "user_005"},
                        "expected_fields": {"status": "confirmed"},
                    },
                    "error": "match_fields resolved to zero or multiple records",
                    "match_count": 2,
                    "matched_record_keys": ["BK-2042", "BK-2043"],
                }
            ]
        }

    def test_fails_when_record_missing(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-404", "field": "status", "expected_value": "cancelled"}]
        )

        result = evaluate_state_requirements(task, StateDiff())

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "missing_assertions": [
                {"entity_type": "bookings", "record_key": "BK-404", "field": "status", "value": "cancelled"}
            ]
        }

    def test_fails_when_field_missing(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-1", "field": "refund_amount", "expected_value": 100}]
        )
        diff = StateDiff(modified={"bookings": {"BK-1": {"status": {"old": "confirmed", "new": "cancelled"}}}})

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "missing_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "refund_amount", "value": 100}
            ],
            "unexpected_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "status", "value": "cancelled"}
            ],
        }

    def test_fails_when_value_mismatched(self):
        task = _make_state_task(
            [{"entity_type": "bookings", "record_key": "BK-1", "field": "change_fee", "expected_value": 150}]
        )
        diff = StateDiff(modified={"bookings": {"BK-1": {"change_fee": {"old": None, "new": 75}}}})

        result = evaluate_state_requirements(task, diff)

        assert result is not None
        assert result.score == 0
        assert result.details == {
            "missing_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "change_fee", "value": 150}
            ],
            "unexpected_assertions": [
                {"entity_type": "bookings", "record_key": "BK-1", "field": "change_fee", "value": 75}
            ],
        }


def _make_prompts_dir_with_task_requirements() -> Path:
    """Create a temp dir with task requirement templates."""
    d = tempfile.mkdtemp()
    base = Path(d)
    (base / "judge_task_requirements.md").write_text(
        "Task summary: $task_summary\nRequirements: $task_requirements\nInstructions: judge exactly\nConversation: $conversation"
    )
    return base


class TestTaskRequirementsJudge:
    def test_empty_requirements_auto_pass(self):
        task = _make_task()
        task.task_requirements = []

        result = evaluate_task_requirements_empty(task)

        assert result is not None
        assert result.score == 1
        assert result.details == []
        assert "no task_requirements" in result.reasoning

    def test_judge_derives_binary_score_from_details(self):
        client = MagicMock()
        client.complete_json.return_value = {
            "details": [{"id": "r1", "passed": True, "reasoning": "Agent did it."}],
        }
        prompts_dir = _make_prompts_dir_with_task_requirements()
        judge = TaskRequirementsJudge(client, prompts_dir, "Judge")
        task = _make_task()
        task.task_requirements = [{"id": "r1", "kind": "must", "requirement": "Do it", "evidence": "conversation"}]

        result = judge.evaluate(task, [{"role": "assistant", "content": "done"}], [], StateDiff())

        assert result is not None
        assert result.score == 1
        assert result.details == [{"id": "r1", "passed": True, "reasoning": "Agent did it."}]
        assert result.reasoning == "All task_requirements satisfied."

    def test_judge_fails_when_any_detail_fails(self):
        client = MagicMock()
        client.complete_json.return_value = {
            "details": [
                {"id": "r1", "passed": True, "reasoning": "Agent did it."},
                {"id": "r2", "passed": False, "reasoning": "Agent skipped it."},
            ],
        }
        prompts_dir = _make_prompts_dir_with_task_requirements()
        judge = TaskRequirementsJudge(client, prompts_dir, "Judge")
        task = _make_task()
        task.task_requirements = [
            {"id": "r1", "kind": "must", "requirement": "Do first", "evidence": "conversation"},
            {"id": "r2", "kind": "must", "requirement": "Do second", "evidence": "conversation"},
        ]

        result = judge.evaluate(task, [{"role": "assistant", "content": "done"}], [], StateDiff())

        assert result is not None
        assert result.score == 0
        assert result.details == [
            {"id": "r1", "passed": True, "reasoning": "Agent did it."},
            {"id": "r2", "passed": False, "reasoning": "Agent skipped it."},
        ]
        assert "r2: Agent skipped it." in result.reasoning

    def test_judge_fails_when_detail_is_missing(self):
        client = MagicMock()
        client.complete_json.return_value = {
            "details": [{"id": "r1", "passed": True, "reasoning": "Agent did it."}],
        }
        prompts_dir = _make_prompts_dir_with_task_requirements()
        judge = TaskRequirementsJudge(client, prompts_dir, "Judge")
        task = _make_task()
        task.task_requirements = [
            {"id": "r1", "kind": "must", "requirement": "Do first", "evidence": "conversation"},
            {"id": "r2", "kind": "must", "requirement": "Do second", "evidence": "conversation"},
        ]

        result = judge.evaluate(task, [{"role": "assistant", "content": "done"}], [], StateDiff())

        assert result is not None
        assert result.score == 0
        assert result.details == [{"id": "r1", "passed": True, "reasoning": "Agent did it."}]
        # Structural failure (missing judgment) should be reported in reasoning
        assert "missing judgments" in result.reasoning
        assert "r2" in result.reasoning

    def test_judge_uses_auto_pass_without_llm_call_for_empty_requirements(self):
        client = MagicMock()
        prompts_dir = _make_prompts_dir_with_task_requirements()
        judge = TaskRequirementsJudge(client, prompts_dir, "Judge")
        task = _make_task()
        task.task_requirements = []

        result = judge.evaluate(task, [], [], StateDiff())

        assert result is not None
        assert result.score == 1
        client.complete_json.assert_not_called()


class TestCombineTaskCompletion:
    def test_returns_none_when_task_requirements_score_is_missing(self):
        assert combine_task_completion(BinaryScore(score=1, reasoning="ok"), None) is None

    def test_requires_both_surfaces_when_both_exist(self):
        result = combine_task_completion(
            BinaryScore(score=0, reasoning="bad state"),
            TaskRequirementsScore(score=1, details=[]),
        )
        assert result == 0


def _make_prompts_dir_with_ux() -> Path:
    d = tempfile.mkdtemp()
    base = Path(d)
    (base / "judge_ux_quality_user.md").write_text("$task_summary\nConversation: $conversation")
    (base / "judge_ux_quality.md").write_text("You are a UX judge.")
    return base


class TestUXQualityJudge:
    def test_build_ux_prompt_includes_task_context_and_conversation(self):
        prompts_dir = _make_prompts_dir_with_ux()
        task = _make_task()
        task.task_summary = "Task: desc\nChallenge: chall"
        prompt = build_ux_prompt(
            task=task,
            conversation=[{"role": "user", "content": "hello"}],
            tool_calls=[],
            prompts_dir=prompts_dir,
        )
        assert "Task: desc" in prompt
        assert "Challenge: chall" in prompt
        assert "hello" in prompt

    def test_evaluate_returns_ux_result(self):
        client = MagicMock()
        client.complete_json.return_value = {
            "user_control": 4,
            "friction": 5,
            "situational_awareness": 3,
            "communication_quality": 4,
            "intent_alignment": 5,
            "ux_score": 4.0,
            "reasoning": "solid",
        }
        prompts_dir = _make_prompts_dir_with_ux()
        judge = UXQualityJudge(client, prompts_dir, "Judge")

        task = _make_task()
        task.task_summary = "Task: desc\nChallenge: chall"
        result = judge.evaluate(
            task=task,
            conversation=[{"role": "assistant", "content": "done"}],
            tool_calls=[],
        )

        assert result == UXQualityResult(
            user_control=4,
            friction=5,
            situational_awareness=3,
            communication_quality=4,
            intent_alignment=5,
            reasoning="solid",
            score=4.0,
        )
        assert result.ux_score == 4.0
        _, kwargs = client.complete_json.call_args
        assert kwargs["system_prompt"] == "You are a UX judge."

    def test_evaluate_returns_none_on_exception(self):
        client = MagicMock()
        client.complete_json.side_effect = RuntimeError("boom")
        prompts_dir = _make_prompts_dir_with_ux()
        judge = UXQualityJudge(client, prompts_dir, "Judge")

        result = judge.evaluate(task=_make_task(), conversation=[], tool_calls=[])

        assert result is None


def test_state_requirements_can_match_preserved_seeded_state_from_task_env(tmp_path):
    task = _make_state_task(
        [
            {
                "entity_type": "cart_items",
                "match_fields": {"customer_id": "shop_004", "product_id": "SP-1002"},
                "expected_fields": {"quantity": 1, "gift_wrap": False},
            },
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "subtotal", "expected_value": 1078},
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "total", "expected_value": 1078},
        ]
    )
    env_path = tmp_path / "task_env.json"
    env_path.write_text(
        json.dumps(
            {
                "customers": {"shop_004": {"customer_id": "shop_004"}},
                "carts": {
                    "CART-shop_004": {
                        "cart_id": "CART-shop_004",
                        "customer_id": "shop_004",
                        "item_ids": ["CI-A1", "CI-A2"],
                        "subtotal": 1128,
                        "total": 1128,
                    }
                },
                "cart_items": {
                    "CI-A1": {
                        "cart_item_id": "CI-A1",
                        "customer_id": "shop_004",
                        "product_id": "SP-1002",
                        "quantity": 1,
                        "gift_wrap": False,
                    },
                    "CI-A2": {
                        "cart_item_id": "CI-A2",
                        "customer_id": "shop_004",
                        "product_id": "SP-2006",
                        "quantity": 1,
                        "gift_wrap": False,
                    },
                },
            }
        )
    )
    task.task_env_path = str(env_path)
    diff = StateDiff(
        modified={
            "carts": {"CART-shop_004": {"subtotal": {"old": 1128, "new": 1078}, "total": {"old": 1128, "new": 1078}}}
        },
        created={
            "cart_items": {
                "CI-0003": {
                    "cart_item_id": "CI-0003",
                    "customer_id": "shop_004",
                    "product_id": "SP-2005",
                    "quantity": 1,
                    "gift_wrap": False,
                }
            }
        },
        deleted={
            "cart_items": {
                "CI-A2": {
                    "cart_item_id": "CI-A2",
                    "customer_id": "shop_004",
                    "product_id": "SP-2006",
                    "quantity": 1,
                    "gift_wrap": False,
                }
            }
        },
    )

    result = evaluate_state_requirements(task, diff)

    assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")


def test_state_requirements_allow_reviewed_path_dependent_cart_item_ids(tmp_path):
    task = _make_state_task(
        [
            {
                "entity_type": "cart_items",
                "match_fields": {
                    "customer_id": "shop_004",
                    "product_id": "SP-1002",
                    "gift_wrap": False,
                    "quantity": 1,
                },
                "expected_fields": {},
            },
            {
                "entity_type": "cart_items",
                "match_fields": {
                    "customer_id": "shop_004",
                    "product_id": "SP-2003",
                    "gift_wrap": False,
                    "quantity": 1,
                },
                "expected_fields": {},
            },
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "subtotal", "expected_value": 1148},
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "total", "expected_value": 1148},
        ]
    )
    task.task_id = "55-partial_add_failure_reporting"
    env_path = tmp_path / "task_env.json"
    env_path.write_text(
        json.dumps(
            {
                "customers": {"shop_004": {"customer_id": "shop_004"}},
                "carts": {
                    "CART-shop_004": {
                        "cart_id": "CART-shop_004",
                        "customer_id": "shop_004",
                        "item_ids": [],
                        "subtotal": 0,
                        "total": 0,
                    }
                },
                "cart_items": {},
            }
        )
    )
    task.task_env_path = str(env_path)
    diff = StateDiff(
        modified={
            "carts": {
                "CART-shop_004": {
                    "item_ids": {"old": [], "new": ["CI-0003", "CI-0004"]},
                    "subtotal": {"old": 0, "new": 1148},
                    "total": {"old": 0, "new": 1148},
                }
            }
        },
        created={
            "cart_items": {
                "CI-0003": {
                    "cart_item_id": "CI-0003",
                    "customer_id": "shop_004",
                    "product_id": "SP-1002",
                    "quantity": 1,
                    "gift_wrap": False,
                },
                "CI-0004": {
                    "cart_item_id": "CI-0004",
                    "customer_id": "shop_004",
                    "product_id": "SP-2003",
                    "quantity": 1,
                    "gift_wrap": False,
                },
            }
        },
    )

    result = evaluate_state_requirements(task, diff)

    assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")


def test_state_requirements_do_not_ignore_uncovered_cart_item_ids(tmp_path):
    task = _make_state_task(
        [
            {
                "entity_type": "cart_items",
                "match_fields": {
                    "customer_id": "shop_004",
                    "product_id": "SP-1002",
                    "gift_wrap": False,
                    "quantity": 1,
                },
                "expected_fields": {},
            },
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "subtotal", "expected_value": 999},
        ]
    )
    task.task_id = "1-recommend_college_laptop"
    env_path = tmp_path / "task_env.json"
    env_path.write_text(
        json.dumps(
            {
                "customers": {"shop_004": {"customer_id": "shop_004"}},
                "carts": {"CART-shop_004": {"cart_id": "CART-shop_004", "item_ids": [], "subtotal": 0}},
                "cart_items": {},
            }
        )
    )
    task.task_env_path = str(env_path)
    diff = StateDiff(
        modified={
            "carts": {
                "CART-shop_004": {
                    "item_ids": {"old": [], "new": ["CI-0003", "CI-0004"]},
                    "subtotal": {"old": 0, "new": 999},
                }
            }
        },
        created={
            "cart_items": {
                "CI-0003": {
                    "cart_item_id": "CI-0003",
                    "customer_id": "shop_004",
                    "product_id": "SP-1002",
                    "quantity": 1,
                    "gift_wrap": False,
                },
                "CI-0004": {
                    "cart_item_id": "CI-0004",
                    "customer_id": "shop_004",
                    "product_id": "SP-2003",
                    "quantity": 1,
                    "gift_wrap": False,
                },
            }
        },
    )

    result = evaluate_state_requirements(task, diff)

    assert result is not None
    assert result.score == 0
    assert result.details == {
        "unexpected_assertions": [
            {
                "entity_type": "carts",
                "record_key": "CART-shop_004",
                "field": "item_ids",
                "value": ["CI-0003", "CI-0004"],
            }
        ]
    }


def test_state_requirements_can_match_preserved_seeded_final_fields_after_remove_only(tmp_path):
    task = _make_state_task(
        [
            {
                "entity_type": "carts",
                "record_key": "CART-shop_004",
                "field": "applied_promo_codes",
                "expected_value": [],
            },
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "subtotal", "expected_value": 129},
            {"entity_type": "carts", "record_key": "CART-shop_004", "field": "total", "expected_value": 129},
        ]
    )
    env_path = tmp_path / "task_env.json"
    env_path.write_text(
        json.dumps(
            {
                "customers": {"shop_004": {"customer_id": "shop_004"}},
                "carts": {
                    "CART-shop_004": {
                        "cart_id": "CART-shop_004",
                        "customer_id": "shop_004",
                        "item_ids": [],
                        "subtotal": 0,
                        "total": 0,
                        "applied_promo_codes": [],
                    }
                },
                "cart_items": {},
                "promotions": {},
            }
        )
    )
    task.task_env_path = str(env_path)
    diff = StateDiff(
        modified={"carts": {"CART-shop_004": {"subtotal": {"old": 0, "new": 129}, "total": {"old": 0, "new": 129}}}},
        created={
            "cart_items": {
                "CI-0001": {
                    "cart_item_id": "CI-0001",
                    "customer_id": "shop_004",
                    "product_id": "SP-2006",
                    "quantity": 1,
                    "gift_wrap": False,
                }
            }
        },
    )

    result = evaluate_state_requirements(task, diff)

    assert result == BinaryScore(score=1, reasoning="All required state assertions matched the saved state_diff.")


def test_evaluation_result_to_dict_separates_task_and_state_reasoning():
    from state_bench.schemas import (
        BinaryScore,
        TaskRequirementsScore,
        Trajectory,
    )

    result = Trajectory(
        task_id="t1",
        user_id="u1",
        task_summary="x",
        conversation=[],
        state_requirements_score=BinaryScore(score=1, reasoning="STATE TEXT"),
        task_requirements_score=TaskRequirementsScore(score=0, details=[], reasoning="TASK TEXT"),
    )
    out = result.to_dict()
    assert out["state_requirements_reasoning"] == "STATE TEXT"
    assert out["task_requirements_reasoning"] == "TASK TEXT"
    assert "reasoning" not in out


def test_evaluate_task_requirements_empty_carries_explanatory_reasoning():
    from state_bench.schemas import TaskDefinition
    from state_bench.scoring import evaluate_task_requirements_empty

    task = TaskDefinition(
        task_id="t1",
        user_id="u1",
        task_type="x",
        opening_message="",
        user_simulator={},
        task_summary="x",
        task_requirements=[],
    )
    score = evaluate_task_requirements_empty(task)
    assert score is not None
    assert score.score == 1
    assert "no task_requirements" in score.reasoning


def test_summarize_task_requirements_details_distinguishes_failures_from_structural():
    from state_bench.scoring import _summarize_task_requirements_details

    s = _summarize_task_requirements_details(
        details=[{"id": "r1", "passed": True}, {"id": "r2", "passed": True}],
        required_ids={"r1", "r2"},
        passed_ids={"r1", "r2"},
    )
    assert s == "All task_requirements satisfied."

    s = _summarize_task_requirements_details(
        details=[{"id": "r1", "passed": True}, {"id": "r2", "passed": False, "reasoning": "did not match"}],
        required_ids={"r1", "r2"},
        passed_ids={"r1"},
    )
    assert "r2: did not match" in s

    s = _summarize_task_requirements_details(
        details=[{"id": "r1", "passed": True}],
        required_ids={"r1", "r2"},
        passed_ids={"r1"},
    )
    assert "missing judgments" in s
    assert "r2" in s

    s = _summarize_task_requirements_details(details=[], required_ids=set(), passed_ids=set())
    assert "no task_requirements" in s


def test_task_definition_from_dict_rejects_duplicate_task_requirement_ids():
    import pytest

    from state_bench.schemas import TaskDefinition

    payload = {
        "task_id": "t1",
        "user_id": "u1",
        "task_summary": "x",
        "opening_message": "hi",
        "user_simulator": {"user_sim_context": "ctx", "personality": "polite"},
        "task_requirements": [
            {"id": "r1", "kind": "must", "requirement": "first", "evidence": "conversation"},
            {"id": "r1", "kind": "must_not", "requirement": "second", "evidence": "conversation"},
        ],
    }
    with pytest.raises(ValueError, match="duplicate task_requirement id"):
        TaskDefinition.from_dict(payload)


def test_task_definition_from_dict_accepts_unique_task_requirement_ids():
    from state_bench.schemas import TaskDefinition

    payload = {
        "task_id": "t1",
        "user_id": "u1",
        "task_summary": "x",
        "opening_message": "hi",
        "user_simulator": {"user_sim_context": "ctx", "personality": "polite"},
        "task_requirements": [
            {"id": "r1", "kind": "must", "requirement": "first", "evidence": "conversation"},
            {"id": "r2", "kind": "must", "requirement": "second", "evidence": "conversation"},
        ],
    }
    task = TaskDefinition.from_dict(payload)
    assert {r["id"] for r in task.task_requirements} == {"r1", "r2"}


def test_all_checked_in_customer_support_tasks_have_unique_requirement_ids():
    """Smoke test against the real corpus: every checked-in CS task must load
    cleanly under the new uniqueness check. Catches regressions where a future
    edit reintroduces dup IDs."""
    import json
    from pathlib import Path

    from state_bench.schemas import TaskDefinition

    tasks_dir = Path("state_bench/domains/customer_support/tasks")
    for task_file in sorted(tasks_dir.glob("*.json")):
        # Loading raises ValueError if dup ids exist
        TaskDefinition.from_dict(json.loads(task_file.read_text()))
