# Customer Support Date Fix Notes

This document tracks proposed customer support fixture date fixes. It is a planning note only; no fixture changes have been applied from this document yet.

## Critical T38-Like Issues

These are the highest-priority fixes because the order chronology is impossible in a way an agent or user could directly notice.

| Task | Why critical |
| --- | --- |
| `38-exchange_outside_window` | `delivery_date` is before `order_date`. |
| `127-hard_warranty_recent_expiry_discounted_repair` | `delivery_date` and warranty start are in 2025, but `order_date` is in 2026. |
| `128-hard_warranty_recurring_low_value_replace` | `delivery_date` is before `order_date`. |
| `130-hard_warranty_maxed_but_paid_repair` | `delivery_date` is before `order_date`. |
| `137-hard_edge_all_windows_plus_false_defect` | `delivery_date` is before `order_date`. |

## Tasks Needing Date Fix Review

These tasks have hard chronology issues such as delivery before order, promised delivery before order, or stale promised delivery dates copied from an unrelated fixture. Each task needs a targeted review before editing because some old delivery dates are intentional for warranty or seasonal-return scenarios.

| Task | Primary issue |
| --- | --- |
| `17-cancel_price_match` | `delivery_promised_date` is before `order_date`. |
| `38-exchange_outside_window` | `delivery_date` is before `order_date`. |
| `52-challenge_fragile_goodwill_separate` | `delivery_promised_date` is before `order_date`. |
| `53-challenge_remorse_as_defective` | `delivery_promised_date` is before `order_date`. |
| `54-challenge_high_value_investigation` | `delivery_promised_date` is before `order_date`. |
| `55-challenge_price_match_refund` | `delivery_promised_date` is before `order_date`. |
| `56-challenge_signature_denial` | `delivery_promised_date` is before `order_date`. |
| `57-challenge_false_damage_claim` | `delivery_promised_date` is before `order_date`. |
| `59-challenge_damaged_plus_wrong` | `delivery_promised_date` is before `order_date`. |
| `60-challenge_low_value_lost_immediate` | `delivery_promised_date` is before `order_date`. |
| `62-challenge_exchange_oos_pivot` | `delivery_promised_date` is before `order_date`. |
| `63-challenge_bulk_clawback` | `delivery_promised_date` is before `order_date`. |
| `65-challenge_defective_plus_clawback` | `delivery_promised_date` is before `order_date`. |
| `67-challenge_seasonal_plus_bulk_clawback` | Stale `delivery_promised_date` predates the November order. |
| `68-challenge_seasonal_plus_shipping_clawback` | Stale `delivery_promised_date` predates the November order. |
| `77-challenge_seasonal_gold_restocking` | Stale `delivery_promised_date` predates the December order. |
| `79-challenge_user_error_as_defective` | `delivery_promised_date` is before `order_date`. |
| `84-challenge_seasonal_return_shipping` | Stale `delivery_promised_date` predates the November order. |
| `85-challenge_seasonal_repeat_clothing` | Stale `delivery_promised_date` predates the November order. |
| `86-challenge_seasonal_bulk_shipping_triple` | Stale `delivery_promised_date` predates the November order. |
| `92-challenge_seasonal_restock_shipping_triple` | Stale `delivery_promised_date` predates the December order. |
| `93-challenge_seasonal_repeat_shipping` | Stale `delivery_promised_date` predates the November order. |
| `96-challenge_seasonal_low_value_silver_electronics` | Stale `delivery_promised_date` predates the December order. |
| `127-hard_warranty_recent_expiry_discounted_repair` | `order_date` and `delivery_promised_date` are inconsistent with the intended 2025 delivery/warranty timeline. |
| `128-hard_warranty_recurring_low_value_replace` | `delivery_date` is before `order_date`; likely warranty timeline needs review. |
| `130-hard_warranty_maxed_but_paid_repair` | `delivery_date` is before `order_date`; likely warranty timeline needs review. |
| `137-hard_edge_all_windows_plus_false_defect` | `delivery_date` is before `order_date`; old delivery may be intentional but order chronology must be fixed. |

## T127: `127-hard_warranty_recent_expiry_discounted_repair`

### Files

- Task: `state_bench/domains/customer_support/tasks/127-hard_warranty_recent_expiry_discounted_repair.json`
- Environment: `state_bench/domains/customer_support/task_envs/127-hard_warranty_recent_expiry_discounted_repair.json`

### Task Intent

The task is about a coffee maker warranty that expired recently. The correct resolution is discounted paid repair, not free repair, replacement, refund, goodwill, escalation, or a denial that no warranty options exist.

The intended warranty timeline is coherent:

```text
delivery_date / warranty start: 2025-07-01
warranty end:                  2026-06-26
task now:                      2026-07-20
```

This makes the warranty recently expired at task time and supports the discounted paid repair path.

### Current Inconsistent Fields

In the environment fixture, the order chronology is inconsistent:

```json
"order_date": "2026-06-01T10:00:00",
"delivery_date": "2025-07-01T12:00:00",
"delivery_promised_date": "2026-06-05T18:00:00"
```

Problems:

- The order date is after the delivery date.
- The order date is after the warranty start date.
- The promised delivery date is almost a year after actual delivery.
- The warranty fields themselves appear correct and should not be moved forward.

### Proposed Fix

Change only the order chronology fields so they align with the intended warranty timeline:

```json
"order_date": "2025-06-01T10:00:00",
"delivery_date": "2025-07-01T12:00:00",
"delivery_promised_date": "2025-07-01T18:00:00"
```

Leave the warranty fields unchanged:

```json
"start_date": "2025-07-01",
"end_date": "2026-06-26"
```

Leave task `now` unchanged:

```json
"now": "2026-07-20T10:00:00"
```

### Resulting Timeline

```text
order placed:       2025-06-01 10:00
delivered:          2025-07-01 12:00
promised delivery:  2025-07-01 18:00
warranty starts:    2025-07-01
warranty ends:      2026-06-26
task now:           2026-07-20 10:00
```

This preserves the task's intended policy challenge while removing the impossible order/delivery chronology.
