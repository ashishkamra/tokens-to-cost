// All prices in prices.json are USD per 1M tokens.
const SCALE = 1_000_000;

const ALIASES = {
  "o3": "openai/o3",
  "o4-mini": "openai/o4-mini",
  "gpt-4o": "openai/gpt-4o",
  "gpt-4.1": "openai/gpt-4.1",
  "gpt-4.1-mini": "openai/gpt-4.1-mini",
  "gpt-4.1-nano": "openai/gpt-4.1-nano",
  "claude-sonnet-4": "anthropic/claude-sonnet-4",
  "sonnet-4": "anthropic/claude-sonnet-4",
  "claude-opus-4": "anthropic/claude-opus-4",
  "opus-4": "anthropic/claude-opus-4",
  "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
  "claude-3-opus": "anthropic/claude-3-opus",
  "gemini-2.5-pro": "google/gemini-2.5-pro",
  "gemini-2.5-flash": "google/gemini-2.5-flash",
  "mistral-small-24b-w8a8": "mistralai/mistral-small-3.1-24b-instruct",
  "mistral-small": "mistralai/mistral-small-3.2-24b-instruct",
  "mistral-large": "mistralai/mistral-large",
  "mistral-nemo": "mistralai/mistral-nemo",
};

const REQUIRED_COLUMNS = [
  "participant", "model", "input_tokens", "output_tokens",
  "reasoning_tokens", "cached_input_tokens",
];

let pricesData = null;

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

async function init() {
  try {
    const resp = await fetch("./prices.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    pricesData = await resp.json();
    document.getElementById("prices-date").textContent =
      pricesData._meta?.last_updated || "unknown";
    renderPricesTable();
    populateExample();
  } catch (e) {
    showMessage("error", `Failed to load prices.json: ${e.message}`);
  }
}

function populateExample() {
  const textarea = document.getElementById("csv-input");
  if (!textarea.value.trim()) {
    textarea.value =
`participant,model,input_tokens,output_tokens,reasoning_tokens,cached_input_tokens
alice,o3,15000,3000,195000,0
alice,gpt-4.1,20000,5000,0,8000
bob,claude-sonnet-4,25000,8000,0,12000
bob,gemini-2.5-pro,30000,5000,50000,5000`;
  }
}

// ---------------------------------------------------------------------------
// Model resolution — exact match only
// ---------------------------------------------------------------------------

function resolveModel(rawName) {
  const normalized = rawName.trim().toLowerCase();
  const models = pricesData.models;

  if (models[normalized]) return normalized;
  if (ALIASES[normalized] && models[ALIASES[normalized]]) return ALIASES[normalized];

  return null;
}

// ---------------------------------------------------------------------------
// CSV parsing
// ---------------------------------------------------------------------------

function parseCSV(text) {
  const lines = text.trim().split("\n").map(l => l.trim()).filter(l => l);
  if (lines.length < 2) throw new Error("CSV must have a header row and at least one data row");

  const headers = lines[0].split(",").map(h => h.trim().toLowerCase());
  const missing = REQUIRED_COLUMNS.filter(c => !headers.includes(c));
  if (missing.length > 0) {
    throw new Error(`CSV missing required columns: ${missing.join(", ")}\nRequired: ${REQUIRED_COLUMNS.join(", ")}`);
  }

  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split(",").map(v => v.trim());
    const row = {};
    headers.forEach((h, idx) => { row[h] = values[idx] || ""; });

    const parsed = {
      participant: row.participant,
      model: row.model,
      input_tokens: parseInt(row.input_tokens, 10),
      output_tokens: parseInt(row.output_tokens, 10),
      reasoning_tokens: parseInt(row.reasoning_tokens, 10),
      cached_input_tokens: parseInt(row.cached_input_tokens, 10),
    };

    for (const field of ["input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"]) {
      if (isNaN(parsed[field]) || parsed[field] < 0) {
        throw new Error(`Row ${i + 1}: '${field}' must be a non-negative integer`);
      }
    }
    if (!parsed.participant || !parsed.model) {
      throw new Error(`Row ${i + 1}: 'participant' and 'model' must not be empty`);
    }
    rows.push(parsed);
  }
  return rows;
}

// ---------------------------------------------------------------------------
// Cost calculation — mirrors Python compute_cost exactly
// ---------------------------------------------------------------------------

function computeCost(row, modelPrices) {
  const inputCost = row.input_tokens * modelPrices.input / SCALE;
  const outputCost = row.output_tokens * modelPrices.output / SCALE;

  let reasoningPrice = modelPrices.reasoning;
  const warnings = [];
  if (reasoningPrice === null || reasoningPrice === undefined) {
    if (row.reasoning_tokens > 0) {
      warnings.push(`Model ${row.resolved_model} has no reasoning price; using output price`);
      reasoningPrice = modelPrices.output;
    } else {
      reasoningPrice = 0;
    }
  }
  const reasoningCost = row.reasoning_tokens * reasoningPrice / SCALE;
  const cachedPrice = modelPrices.cached_input ?? modelPrices.input;
  const cachedCost = row.cached_input_tokens * cachedPrice / SCALE;

  return {
    participant: row.participant,
    model: row.resolved_model,
    model_input: row.model,
    input_tokens: row.input_tokens,
    output_tokens: row.output_tokens,
    reasoning_tokens: row.reasoning_tokens,
    cached_input_tokens: row.cached_input_tokens,
    input_cost: inputCost,
    output_cost: outputCost,
    reasoning_cost: reasoningCost,
    cached_input_cost: cachedCost,
    total_cost: inputCost + outputCost + reasoningCost + cachedCost,
    warnings,
  };
}

// ---------------------------------------------------------------------------
// Aggregation
// ---------------------------------------------------------------------------

function aggregateResults(costs) {
  const groups = {};
  for (const c of costs) {
    const key = c.participant.trim().toLowerCase();
    if (!groups[key]) {
      groups[key] = { display_name: c.participant, rows: [], totals: {} };
      for (const f of ["input_cost", "output_cost", "reasoning_cost", "cached_input_cost", "total_cost",
                        "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"]) {
        groups[key].totals[f] = 0;
      }
    }
    groups[key].rows.push(c);
    for (const f of ["input_cost", "output_cost", "reasoning_cost", "cached_input_cost", "total_cost",
                      "input_tokens", "output_tokens", "reasoning_tokens", "cached_input_tokens"]) {
      groups[key].totals[f] += c[f];
    }
  }
  return Object.values(groups).sort((a, b) => a.totals.total_cost - b.totals.total_cost);
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function formatDollar(val) {
  if (val === 0) return "$0.000";
  if (val < 0.001) return "$" + val.toFixed(6);
  if (val < 1) return "$" + val.toFixed(4);
  return "$" + val.toFixed(2);
}

function formatNumber(val) {
  return val.toLocaleString();
}

function dominantCostType(totals) {
  const total = totals.total_cost;
  if (total === 0) return "n/a";
  const costs = {
    input: totals.input_cost,
    output: totals.output_cost,
    reasoning: totals.reasoning_cost,
    cached: totals.cached_input_cost,
  };
  let topType = "input";
  let topVal = 0;
  for (const [k, v] of Object.entries(costs)) {
    if (v > topVal) { topType = k; topVal = v; }
  }
  const pct = Math.round(topVal / total * 100);
  return `${topType} (${pct}%)`;
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

function clearMessages() {
  document.getElementById("messages").innerHTML = "";
}

function showMessage(type, text) {
  const div = document.createElement("div");
  div.className = `msg msg-${type}`;
  div.textContent = text;
  document.getElementById("messages").appendChild(div);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function renderResults(results) {
  const container = document.getElementById("results-container");
  container.innerHTML = "";

  for (const p of results) {
    const header = document.createElement("div");
    header.className = "participant-header";
    header.textContent = `Participant: ${p.display_name}`;
    container.appendChild(header);

    const table = document.createElement("table");
    table.className = "results-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");
    const columns = [
      "Model", "Input Tok", "Output Tok", "Reason Tok", "Cached Tok",
      "Input$", "Output$", "Reason$", "Cached$", "Total$",
    ];
    columns.forEach(col => {
      const th = document.createElement("th");
      th.textContent = col;
      headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    for (const r of p.rows) {
      const tr = document.createElement("tr");
      const cells = [
        r.model, formatNumber(r.input_tokens), formatNumber(r.output_tokens),
        formatNumber(r.reasoning_tokens), formatNumber(r.cached_input_tokens),
        formatDollar(r.input_cost), formatDollar(r.output_cost),
        formatDollar(r.reasoning_cost), formatDollar(r.cached_input_cost),
        formatDollar(r.total_cost),
      ];
      cells.forEach(val => {
        const td = document.createElement("td");
        td.textContent = val;
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    }

    // Total row
    const t = p.totals;
    const totalTr = document.createElement("tr");
    totalTr.className = "total-row";
    const totalCells = [
      "TOTAL", formatNumber(t.input_tokens), formatNumber(t.output_tokens),
      formatNumber(t.reasoning_tokens), formatNumber(t.cached_input_tokens),
      formatDollar(t.input_cost), formatDollar(t.output_cost),
      formatDollar(t.reasoning_cost), formatDollar(t.cached_input_cost),
      formatDollar(t.total_cost),
    ];
    totalCells.forEach(val => {
      const td = document.createElement("td");
      td.textContent = val;
      totalTr.appendChild(td);
    });
    tbody.appendChild(totalTr);

    table.appendChild(tbody);
    container.appendChild(table);
  }

  document.getElementById("results-section").classList.remove("hidden");
}

function renderSummary(results) {
  const tbody = document.getElementById("summary-body");
  tbody.innerHTML = "";

  results.forEach((p, i) => {
    const tr = document.createElement("tr");
    const cells = [
      i + 1,
      p.display_name,
      formatDollar(p.totals.total_cost),
      dominantCostType(p.totals),
    ];
    cells.forEach(val => {
      const td = document.createElement("td");
      td.textContent = val;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  document.getElementById("summary-section").classList.remove("hidden");
}

function renderPricesTable() {
  if (!pricesData) return;
  const tbody = document.getElementById("prices-body");
  tbody.innerHTML = "";

  const models = Object.keys(pricesData.models).sort();
  for (const modelId of models) {
    const p = pricesData.models[modelId];
    const tr = document.createElement("tr");
    const reasoning = p.reasoning !== null && p.reasoning !== undefined
      ? formatDollar(p.reasoning) : "\u2014";
    const cells = [
      modelId,
      formatDollar(p.input),
      formatDollar(p.output),
      reasoning,
      formatDollar(p.cached_input ?? p.input),
    ];
    cells.forEach(val => {
      const td = document.createElement("td");
      td.textContent = val;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// Main calculation
// ---------------------------------------------------------------------------

function calculate() {
  clearMessages();
  document.getElementById("results-section").classList.add("hidden");
  document.getElementById("summary-section").classList.add("hidden");

  if (!pricesData) {
    showMessage("error", "Prices not loaded. Refresh the page.");
    return;
  }

  const csvText = document.getElementById("csv-input").value;
  if (!csvText.trim()) {
    showMessage("error", "Please paste or upload a CSV file.");
    return;
  }

  let rows;
  try {
    rows = parseCSV(csvText);
  } catch (e) {
    showMessage("error", e.message);
    return;
  }

  const costs = [];
  let errors = 0;
  const allWarnings = [];

  for (const row of rows) {
    const resolved = resolveModel(row.model);
    if (!resolved) {
      const available = Object.keys(pricesData.models).sort().join(", ");
      showMessage("error",
        `Unknown model: '${row.model}'\nAvailable: ${available}\nAdd to aliases if this is a known model under a different name.`
      );
      errors++;
      continue;
    }
    row.resolved_model = resolved;
    const modelPrices = pricesData.models[resolved];
    const result = computeCost(row, modelPrices);
    result.warnings.forEach(w => allWarnings.push(w));
    costs.push(result);
  }

  for (const w of allWarnings) {
    showMessage("warning", w);
  }

  if (costs.length === 0) {
    if (errors === 0) showMessage("error", "No valid rows to process.");
    return;
  }

  const results = aggregateResults(costs);
  renderResults(results);
  renderSummary(results);
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  init();

  document.getElementById("calculate-btn").addEventListener("click", calculate);

  // File upload
  document.getElementById("csv-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      document.getElementById("csv-input").value = ev.target.result;
    };
    reader.readAsText(file);
  });

  // Collapsible price reference
  document.getElementById("prices-toggle").addEventListener("click", () => {
    const header = document.getElementById("prices-toggle");
    const content = document.getElementById("prices-content");
    header.classList.toggle("open");
    content.classList.toggle("open");
  });
});
