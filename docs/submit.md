# Submit Results

Create `outputs.zip` containing the scored trajectories and metrics for every protocol domain you ran:

```
outputs/
  travel/
    run1/<task_id>.json
    run2/<task_id>.json
    ...
    metrics.json
  customer_support/
    ...
  shopping_assistant/
    ...
```

`metrics.json` for each domain is produced by [compute_metrics](eval/compute-metrics.md) and includes the evaluation protocol ID and standardized public metrics.

Submit by opening a GitHub issue in this repository:

1. Attach `outputs.zip` to the issue if it fits within GitHub's upload limit; otherwise include a download link to the archive.
2. Briefly describe your method.
3. Link any relevant paper, GitHub repository, or project page.

After verification, accepted results will be uploaded to the official leaderboard.
