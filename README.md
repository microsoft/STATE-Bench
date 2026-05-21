# STATE-Bench

<p align="center">
  <img src="https://img.shields.io/badge/🏆%20Leaderboard-Coming%20Soon-crimson?style=for-the-badge" alt="Leaderboard" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
  <a href="https://opensource.microsoft.com/blog/2026/05/19/introducing-state-bench-a-benchmark-for-ai-agent-memory/"><img src="https://img.shields.io/badge/Blog-Read-blue" alt="Blog" /></a>
</p>

<p align="center">
  <a href="RUN_BENCHMARK.md">Main Track</a> &nbsp;·&nbsp; <a href="MEMORY_TRACK.md">Memory Track</a>
</p>

STATE-Bench evaluates AI agents on realistic, multi-turn enterprise tasks across **travel**, **customer support**, and **shopping assistant** domains.

Each task gives the agent a task-local sandbox database, domain-specific tools, and a simulated user. To pass a task, the agent must do multi-step reasoning by gathering the right information with domain tools, applying the correct policy, taking actions to update the database to the right final state when needed, and following the required procedure in conversation.

## What STATE-Bench Includes

STATE-Bench includes 450 challenging enterprise tasks across three domains.

| Domain | Tasks | Description |
| --- | ---: | --- |
| **Travel** | 150 | Flight, hotel, and car rental bookings; cancellations, updates, fee and policy reasoning, cross-product trip planning |
| **Customer Support** | 150 | Returns, refunds, exchanges, warranty claims, cancellations, shipping issues, and order changes |
| **Shopping Assistant** | 150 | Product search, cart updates, applying promos, loyalty redemption, shipping options, and compatibility checks |

## Choose Your Benchmark Track

Start with the track that matches what you want to evaluate. Each track guide links to the setup and reference docs only when you need them.

| Goal | Start here |
| --- | --- |
| Evaluate an agent or model directly on the provided enterprise benchmark tasks | **[Main Track](RUN_BENCHMARK.md)** |
| Evaluate agentic memory | **[Memory Track](MEMORY_TRACK.md)** |

The **Main Track** is the default benchmark path. The **Memory Track** uses the same simulator, domain tools, judges, and metrics, but adds train trajectories and a retrieval hook for procedural learnings.

<br/>

<p align="center">
  <img src="assets/chat_bubble_2.svg" alt="Sample task trajectory from the Travel domain" width="55%" />
  <br/>
  <em>Sample task trajectory from the Travel domain.</em>
</p>

## Metrics

STATE-Bench reports four headline metrics:

| Metric | What it measures |
| --- | --- |
| **Task Completion pass@1** | Average task completion rate across five runs per task. |
| **Task Completion pass^5** | Percentage of tasks completed successfully on all five runs. |
| **UX Score** | LLM-judged conversation quality on a 1-5 scale. |
| **Cost Per Task** | Average agent cost from user-reported token usage and pricing. |

## License

STATE-Bench is released under the MIT License. See [LICENSE](LICENSE).

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow Microsoft's Trademark & Brand Guidelines. Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos are subject to those third-party's policies.

## Disclosures

Datasets provided in this benchmark were synthetically generated using large language models. The benchmark is intended for research purposes and users should exercise caution and consider the limitations of synthetic data when interpreting results.
