const entries = [
  {
    id: "main-01",
    track: "main",
    model: "GPT-5.1",
    agent: "StateBenchAgent",
    organization: "OpenAI",
    reasoningLevel: "medium",
    submissionDate: "2026-05-20",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 74.8,
      overallPassAt1Std: 1.6,
      passAt5: 43.1,
      meanUxScore: 4.32,
      costPerTask: 0.218,
      domains: { travel: 73.9, customerSupport: 76.0, shoppingAssistant: 74.5 },
    },
  },
  {
    id: "main-02",
    track: "main",
    model: "Claude Sonnet 4.5",
    agent: "Custom tool loop",
    organization: "Anthropic",
    submissionDate: "2026-05-18",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 72.2,
      overallPassAt1Std: 1.8,
      passAt5: 39.6,
      meanUxScore: 4.27,
      costPerTask: 0.174,
      domains: { travel: 71.1, customerSupport: 73.7, shoppingAssistant: 71.8 },
    },
  },
  {
    id: "main-03",
    track: "main",
    model: "o4-mini",
    agent: "StateBenchAgent",
    organization: "OpenAI",
    reasoningLevel: "high",
    submissionDate: "2026-05-17",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 68.5,
      overallPassAt1Std: 2.1,
      passAt5: 34.2,
      meanUxScore: 4.09,
      costPerTask: 0.086,
      domains: { travel: 67.3, customerSupport: 69.9, shoppingAssistant: 68.2 },
    },
  },
  {
    id: "main-04",
    track: "main",
    model: "Gemini 2.5 Pro",
    agent: "Custom client",
    organization: "Google DeepMind",
    submissionDate: "2026-05-14",
    verificationStatus: "pending",
    metrics: {
      overallPassAt1: 66.9,
      overallPassAt1Std: 1.9,
      passAt5: 31.7,
      meanUxScore: 4.04,
      costPerTask: 0.151,
      domains: { travel: 65.8, customerSupport: 68.1, shoppingAssistant: 66.8 },
    },
  },
  {
    id: "main-05",
    track: "main",
    model: "Llama 4 Maverick",
    agent: "Open tools adapter",
    organization: "Meta",
    submissionDate: "2026-05-13",
    verificationStatus: "self_reported",
    metrics: {
      overallPassAt1: 61.4,
      overallPassAt1Std: 2.4,
      passAt5: 24.9,
      meanUxScore: 3.86,
      costPerTask: 0.042,
      domains: { travel: 59.5, customerSupport: 63.2, shoppingAssistant: 61.5 },
    },
  },
  {
    id: "main-06",
    track: "main",
    model: "Mistral Large 2",
    agent: "Custom client",
    organization: "Mistral AI",
    submissionDate: "2026-05-11",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 58.7,
      overallPassAt1Std: 2.2,
      passAt5: 21.3,
      meanUxScore: 3.78,
      costPerTask: 0.063,
      domains: { travel: 57.1, customerSupport: 60.4, shoppingAssistant: 58.6 },
    },
  },
  {
    id: "main-07",
    track: "main",
    model: "Command A",
    agent: "Tool router",
    organization: "Cohere",
    submissionDate: "2026-05-08",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 54.3,
      overallPassAt1Std: 2.7,
      passAt5: 18.8,
      meanUxScore: 3.65,
      costPerTask: 0.052,
      domains: { travel: 53.2, customerSupport: 55.6, shoppingAssistant: 54.1 },
    },
  },
  {
    id: "main-08",
    track: "main",
    model: "Phi-4 Reasoning Plus",
    agent: "StateBenchAgent",
    organization: "Microsoft Research",
    submissionDate: "2026-05-05",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 51.9,
      overallPassAt1Std: 2.6,
      passAt5: 15.4,
      meanUxScore: 3.58,
      costPerTask: 0.031,
      domains: { travel: 50.6, customerSupport: 53.1, shoppingAssistant: 52.0 },
    },
  },
  {
    id: "main-09",
    track: "main",
    model: "Qwen3 Max",
    agent: "Custom client",
    organization: "Alibaba Cloud",
    submissionDate: "2026-05-04",
    verificationStatus: "pending",
    metrics: {
      overallPassAt1: 49.8,
      overallPassAt1Std: 2.9,
      passAt5: 13.9,
      meanUxScore: 3.49,
      costPerTask: 0.047,
      domains: { travel: 48.4, customerSupport: 50.7, shoppingAssistant: 50.3 },
    },
  },
  {
    id: "main-10",
    track: "main",
    model: "DeepSeek V3.2",
    agent: "Tool loop baseline",
    organization: "DeepSeek",
    submissionDate: "2026-05-01",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 46.2,
      overallPassAt1Std: 3.1,
      passAt5: 10.6,
      meanUxScore: 3.33,
      costPerTask: 0.024,
      domains: { travel: 44.8, customerSupport: 47.6, shoppingAssistant: 46.2 },
    },
  },
  {
    id: "main-11",
    track: "main",
    model: "Baseline Tool Agent",
    agent: "Reference baseline",
    organization: "STATE-Bench",
    submissionDate: "2026-04-30",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 38.4,
      overallPassAt1Std: 3.4,
      passAt5: 6.7,
      meanUxScore: 3.02,
      costPerTask: undefined,
      domains: { travel: 37.0, customerSupport: 40.2, shoppingAssistant: 38.1 },
    },
  },
  {
    id: "memory-01",
    track: "memory",
    model: "GPT-5.1",
    agent: "Terminal retrieval memory",
    organization: "OpenAI",
    reasoningLevel: "medium",
    submissionDate: "2026-05-21",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 79.6,
      overallPassAt1Std: 1.4,
      passAt5: 48.8,
      meanUxScore: 4.35,
      costPerTask: 0.239,
      domains: { travel: 78.7, customerSupport: 80.4, shoppingAssistant: 79.8 },
    },
  },
  {
    id: "memory-02",
    track: "memory",
    model: "Claude Sonnet 4.5",
    agent: "BM25 procedural memory",
    organization: "Anthropic",
    submissionDate: "2026-05-19",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 75.1,
      overallPassAt1Std: 1.7,
      passAt5: 42.9,
      meanUxScore: 4.28,
      costPerTask: 0.192,
      domains: { travel: 74.6, customerSupport: 76.3, shoppingAssistant: 74.4 },
    },
  },
  {
    id: "memory-03",
    track: "memory",
    model: "Gemini 2.5 Pro",
    agent: "Embedding retrieval memory",
    organization: "Google DeepMind",
    submissionDate: "2026-05-15",
    verificationStatus: "pending",
    metrics: {
      overallPassAt1: 71.8,
      overallPassAt1Std: 1.9,
      passAt5: 37.4,
      meanUxScore: 4.15,
      costPerTask: 0.169,
      domains: { travel: 70.2, customerSupport: 73.1, shoppingAssistant: 72.1 },
    },
  },
  {
    id: "memory-04",
    track: "memory",
    model: "o4-mini",
    agent: "Summarized trajectory memory",
    organization: "OpenAI",
    reasoningLevel: "high",
    submissionDate: "2026-05-12",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 70.4,
      overallPassAt1Std: 2.0,
      passAt5: 35.8,
      meanUxScore: 4.11,
      costPerTask: 0.094,
      domains: { travel: 68.9, customerSupport: 71.2, shoppingAssistant: 71.1 },
    },
  },
];

const state = {
  track: "main",
  scoreView: "overall",
  sortKey: "selectedScore",
  sortDirection: "desc",
  showAll: false,
};

const body = document.querySelector("#leaderboard-body");
const toggleRows = document.querySelector("#toggle-rows");
const tabs = Array.from(document.querySelectorAll(".track-tab"));
const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
const primaryScoreSort = document.querySelector("#primary-score-sort");

const scoreLabels = {
  overall: "pass@1 (%)",
  travel: "Travel",
  customerSupport: "Customer Support",
  shoppingAssistant: "Shopping",
};

function selectedScore(entry) {
  if (state.scoreView === "overall") return entry.metrics.overallPassAt1;
  return entry.metrics.domains[state.scoreView];
}

function metricValue(entry, key) {
  if (key === "selectedScore") return selectedScore(entry);
  if (key === "submissionDate") return new Date(entry.submissionDate).getTime();
  return entry.metrics[key];
}

function sortedEntries() {
  return entries
    .filter((entry) => entry.track === state.track)
    .sort((a, b) => {
      const aValue = metricValue(a, state.sortKey);
      const bValue = metricValue(b, state.sortKey);

      if (aValue == null && bValue == null) return 0;
      if (aValue == null) return 1;
      if (bValue == null) return -1;

      const direction = state.sortDirection === "asc" ? 1 : -1;
      return aValue > bValue ? direction : aValue < bValue ? -direction : 0;
    });
}

function formatPercent(value) {
  return value.toFixed(1);
}

function formatPassAt1(entry) {
  const mean = formatPercent(selectedScore(entry));
  const std = entry.metrics.overallPassAt1Std;

  if (state.scoreView !== "overall" || std == null) return `<span class="metric-main">${mean}</span>`;
  return `<span class="metric-main">${mean}</span><span class="metric-std">&plusmn; ${formatPercent(std)}</span>`;
}

function formatUx(value) {
  return value.toFixed(2);
}

function formatCost(value) {
  return value == null ? "-" : `$${value.toFixed(3)}`;
}

function statusLabel(status) {
  return status.replace("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function render() {
  const ranked = sortedEntries();
  const visible = state.showAll ? ranked : ranked.slice(0, 10);

  primaryScoreSort.textContent = scoreLabels[state.scoreView];

  body.innerHTML = visible
    .map((entry) => {
      const rank = ranked.indexOf(entry) + 1;
      const meta = [entry.agent, entry.reasoningLevel ? `reasoning: ${entry.reasoningLevel}` : ""]
        .filter(Boolean)
        .join(" | ");

      return `
        <tr>
          <td class="rank-cell"><span class="rank-pill ${rank <= 3 ? "top" : ""}">${rank}</span></td>
          <td>
            <span class="model-name">${entry.model}</span>
            <span class="model-meta">${meta || "-"}</span>
          </td>
          <td>${entry.organization}</td>
          <td class="metric">${formatPassAt1(entry)}</td>
          <td class="metric">${formatPercent(entry.metrics.passAt5)}</td>
          <td class="metric">${formatUx(entry.metrics.meanUxScore)}</td>
          <td class="metric">${formatCost(entry.metrics.costPerTask)}</td>
          <td>${entry.submissionDate}</td>
          <td><span class="status-badge status-${entry.verificationStatus}">${statusLabel(entry.verificationStatus)}</span></td>
        </tr>
      `;
    })
    .join("");

  toggleRows.hidden = ranked.length <= 10;
  toggleRows.textContent = state.showAll ? "Show top 10" : `Show all ${ranked.length}`;

  tabs.forEach((tab) => {
    const active = tab.dataset.track === state.track;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  sortButtons.forEach((button) => {
    const active = button.dataset.sort === state.sortKey;
    button.classList.toggle("active", active);
    button.classList.toggle("asc", active && state.sortDirection === "asc");
  });

}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    state.track = tab.dataset.track;
    state.showAll = false;
    render();
  });
});

sortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const nextKey = button.dataset.sort;
    const defaultDirection = nextKey === "costPerTask" ? "asc" : "desc";

    if (state.sortKey === nextKey) {
      state.sortDirection = state.sortDirection === "asc" ? "desc" : "asc";
    } else {
      state.sortKey = nextKey;
      state.sortDirection = defaultDirection;
    }

    render();
  });
});

toggleRows.addEventListener("click", () => {
  state.showAll = !state.showAll;
  render();
});

render();
