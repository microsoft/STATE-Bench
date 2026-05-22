# Locked Evaluation Client

The user simulator and judges are pinned by the evaluation protocol so results are comparable across submissions. The current protocol, [`state_bench/configs/eval_protocols/gpt51.json`](../../state_bench/configs/eval_protocols/gpt51.json), fixes the tasks, splits, user simulator prompt, judge prompts, and required simulator/judge model. The current protocol requires **GPT-5.1** for the user simulator and judge. The agent model itself is user-configurable.

> Prompt files are hashed by the protocol. Editing any simulator or judge prompt changes its hash and the run will fail. This guarantees every submission used the same prompts.

Set these in your `.env`:

```bash
STATE_BENCH_EVAL_ENDPOINT="https://your-gpt51-resource.openai.azure.com"
STATE_BENCH_EVAL_DEPLOYMENTS="<your gpt 5.1 deployment name>"
# Optional. If omitted, Azure token auth is tried.
# STATE_BENCH_EVAL_API_KEY="<your gpt 5.1 resource api key>"
```

Deployment names vary by resource. If `STATE_BENCH_EVAL_API_KEY` is omitted, the client falls back to Azure token auth via local CLI credentials and then `DefaultAzureCredential`.

For multiple GPT-5.1 deployments (recommended for higher throughput), pass a comma-separated list:

```bash
STATE_BENCH_EVAL_DEPLOYMENTS="gpt51-a, gpt51-b"
```

The harness load-balances across the listed deployments with sticky routing for Responses API calls that chain on `previous_response_id`.
