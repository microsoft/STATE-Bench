# Reporting Avg. Cost Per Task

Average cost per task is one of the four headline metrics. Reporting cost is **optional** but strongly encouraged — without pricing, your submission will show `$0` cost in `metrics.json` and cannot be compared on the cost axis. Other metrics (completion, reliability, UX) still score correctly.

## Pricing flags

Pass these to `run_batch`:

```bash
--agent-input-cost-per-1m <input-price> \
--agent-output-cost-per-1m <output-price>
```

If your provider reports cached input tokens **and** has a separate cached-input rate, also pass:

```bash
--agent-cached-input-cost-per-1m <cached-input-price>
```

If cached tokens are reported without a cached rate, they are charged at the normal input rate.

`--agent-input-cost-per-1m` and `--agent-output-cost-per-1m` are required together — passing only one raises an error.

## Where token counts come from

### OOTB StateBenchAgent (Azure AI Foundry/OpenAI)

Token counts come straight from the Responses API usage metadata. No extra code is required; the agent records usage automatically.

### Custom client + agent

You must report provider-reported token counts yourself. After each provider LLM call returns, call `self.add_token_usage(...)` from inside your custom agent. The natural place is immediately after `self.client.generate(...)` returns inside `generate_next_turn()`:

```python
self.add_token_usage(
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    cached_input_tokens=cached_input_tokens,
)
```

- `input_tokens` and `output_tokens` are **required** for usage and cost to be recorded.
- `cached_input_tokens` is optional.
- If either input or output tokens are missing, STATE-Bench skips usage and cost recording for that call.

See the full signature in [`state_bench/agents/base.py`](../../state_bench/agents/base.py).

### ⚠️ Silent-$0 trap

If you pass pricing flags **but** your custom agent never calls `self.add_token_usage(...)`, every trajectory ships with zero recorded tokens. `compute_metrics` detects this case and **fails loudly** with an actionable error pointing back to this section — so a forgotten `add_token_usage` call is caught at scoring time rather than silently producing `$0` cost.
