# Compute Metrics

After [run_batch](run-batch.md) finishes, compute the standardized public metrics for a domain:

```bash
uv run python -m state_bench.scripts.compute_metrics \
  --domain <domain> \
  --results-dir outputs/<domain>/ \
  --num-runs 5 \
  --output-dir outputs/<domain>/
```

## Arguments

- `--domain`: Benchmark domain to score: `travel`, `customer_support`, or `shopping_assistant`.
- `--results-dir`: Directory containing the scored trajectories from `run_batch`.
- `--num-runs`: Number of runs to include. Must match the `--num-runs` used in `run_batch`. Set to `5` for official submissions.
- `--output-dir`: Directory where `metrics.json` and per-task metrics are written.

Metrics default to the protocol test split and **fail if any expected test task is missing or unscored**. For local partial analysis only, add `--ignore-missing-runs`; submissions must not use this flag.

Repeat for every protocol domain, then proceed to [Submit Results](../SUBMIT.md).
