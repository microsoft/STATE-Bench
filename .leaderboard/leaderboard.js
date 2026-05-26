const entries = [
  {
    id: "main-01",
    track: "main",
    model: "GPT-5.4",
    reasoningLabel: "high",
    agent: "",
    organization: "OpenAI",
    submissionDate: "2026-05-25",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 55.7,
      overallPassAt1Std: 1.9,
      passAt5: 38.0,
      meanUxScore: 3.49,
      costPerTask: 0.0809,
      domains: {
        travel: { passAt1: 55.9, passAt1Std: 2.8, passAt5: 36.0, meanUxScore: 3.37, costPerTask: 0.1224 },
        customerSupport: { passAt1: 57.6, passAt1Std: 2.5, passAt5: 38.0, meanUxScore: 3.49, costPerTask: 0.0716 },
        shoppingAssistant: { passAt1: 53.6, passAt1Std: 2.1, passAt5: 40.0, meanUxScore: 3.61, costPerTask: 0.0486 },
      },
    },
  },
  {
    id: "main-02",
    track: "main",
    model: "Kimi-K2.6",
    agent: "",
    organization: "Moonshot AI",
    submissionDate: "2026-05-25",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 48.3,
      overallPassAt1Std: 2.1,
      passAt5: 29.3,
      meanUxScore: 3.37,
      costPerTask: 0.0496,
      domains: {
        travel: { passAt1: 51.9, passAt1Std: 4.0, passAt5: 26.0, meanUxScore: 3.22, costPerTask: 0.0871 },
        customerSupport: { passAt1: 45.1, passAt1Std: 1.8, passAt5: 26.0, meanUxScore: 3.35, costPerTask: 0.0339 },
        shoppingAssistant: { passAt1: 47.9, passAt1Std: 2.2, passAt5: 36.0, meanUxScore: 3.54, costPerTask: 0.0279 },
      },
    },
  },
  {
    id: "main-03",
    track: "main",
    model: "DeepSeek-v4-Pro",
    agent: "",
    organization: "DeepSeek",
    submissionDate: "2026-05-25",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 47.2,
      overallPassAt1Std: 0.6,
      passAt5: 25.3,
      meanUxScore: 3.36,
      costPerTask: undefined,
      domains: {
        travel: { passAt1: 47.6, passAt1Std: 2.7, passAt5: 22.0, meanUxScore: 3.04, costPerTask: undefined },
        customerSupport: { passAt1: 45.6, passAt1Std: 1.4, passAt5: 23.0, meanUxScore: 3.50, costPerTask: undefined },
        shoppingAssistant: { passAt1: 48.4, passAt1Std: 2.2, passAt5: 31.0, meanUxScore: 3.54, costPerTask: undefined },
      },
    },
  },
  {
    id: "main-04",
    track: "main",
    organization: "OpenAI",
    model: "GPT-5.4",
    agent: "",
    submissionDate: "2026-05-25",
    verificationStatus: "verified",
    metrics: {
      overallPassAt1: 46.9,
      overallPassAt1Std: 0.9,
      passAt5: 26.2,
      meanUxScore: 3.41,
      costPerTask: 0.0351,
      domains: {
        travel: { passAt1: 43.2, passAt1Std: 1.5, passAt5: 22.9, meanUxScore: 3.19, costPerTask: 0.0565 },
        customerSupport: { passAt1: 47.2, passAt1Std: 2.1, passAt5: 28.1, meanUxScore: 3.49, costPerTask: 0.0271 },
        shoppingAssistant: { passAt1: 50.3, passAt1Std: 1.3, passAt5: 30.8, meanUxScore: 3.55, costPerTask: 0.0216 },
      },
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
const scoreViewInputs = Array.from(document.querySelectorAll('input[name="score-view"]'));
const sortButtons = Array.from(document.querySelectorAll(".sort-button"));
const primaryScoreSort = document.querySelector("#primary-score-sort");

const scoreLabels = {
  overall: "pass@1 (%)",
  travel: "Travel pass@1 (%)",
  customerSupport: "Customer Support pass@1 (%)",
  shoppingAssistant: "Shopping pass@1 (%)",
};

function selectedScore(entry) {
  if (state.scoreView === "overall") return entry.metrics.overallPassAt1;
  return entry.metrics.domains[state.scoreView].passAt1;
}

function selectedMetrics(entry) {
  if (state.scoreView === "overall") return entry.metrics;
  return entry.metrics.domains[state.scoreView];
}

function metricValue(entry, key) {
  if (key === "selectedScore") return selectedScore(entry);
  if (key === "submissionDate") return new Date(entry.submissionDate).getTime();
  if (["passAt5", "meanUxScore", "costPerTask"].includes(key)) return selectedMetrics(entry)[key];
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
  const metrics = selectedMetrics(entry);
  const mean = formatPercent(selectedScore(entry));
  const std = state.scoreView === "overall" ? entry.metrics.overallPassAt1Std : metrics.passAt1Std;

  if (std == null) return `<span class="metric-main">${mean}</span>`;
  return `<span class="metric-main">${mean}</span><span class="metric-std">&plusmn; ${formatPercent(std)}</span>`;
}

function formatUx(value) {
  return value.toFixed(2);
}

function formatCost(value) {
  return value == null ? "-" : `$${value.toFixed(2)}`;
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
      const metrics = selectedMetrics(entry);
      return `
        <tr>
          <td class="rank-cell"><span class="rank-pill ${rank <= 3 ? "top" : ""}">${rank}</span></td>
          <td>
            <span class="model-name">${entry.model}${entry.reasoningLabel ? ` <span class="model-variant">(${entry.reasoningLabel})</span>` : ""}</span>
          </td>
          <td>${entry.organization}</td>
          <td class="metric">${formatPassAt1(entry)}</td>
          <td class="metric">${formatPercent(metrics.passAt5)}</td>
          <td class="metric">${formatUx(metrics.meanUxScore)}</td>
          <td class="metric">${formatCost(metrics.costPerTask)}</td>
          <td>${entry.submissionDate}</td>
          <td><span class="status-badge status-${entry.verificationStatus}">${statusLabel(entry.verificationStatus)}</span></td>
        </tr>
      `;
    })
    .join("");

  if (!visible.length) {
    body.innerHTML = '<tr><td class="empty-state" colspan="9">No submitted results for this track yet.</td></tr>';
  }

  toggleRows.hidden = ranked.length <= 10;
  toggleRows.textContent = state.showAll ? "Show top 10" : `Show all ${ranked.length}`;

  tabs.forEach((tab) => {
    const active = tab.dataset.track === state.track;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  scoreViewInputs.forEach((input) => {
    input.checked = input.value === state.scoreView;
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

scoreViewInputs.forEach((input) => {
  input.addEventListener("change", () => {
    state.scoreView = input.value;
    state.sortKey = "selectedScore";
    state.sortDirection = "desc";
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
