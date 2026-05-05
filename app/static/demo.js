const state = {
  events: [],
  maxEvents: 30,
};

const els = {
  readyDot: document.querySelector("#readyDot"),
  readyText: document.querySelector("#readyText"),
  clientSelect: document.querySelector("#clientSelect"),
  endpointSelect: document.querySelector("#endpointSelect"),
  adminKeyInput: document.querySelector("#adminKeyInput"),
  sendOneBtn: document.querySelector("#sendOneBtn"),
  burstBtn: document.querySelector("#burstBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  signalsBtn: document.querySelector("#signalsBtn"),
  persistentTelemetryBtn: document.querySelector("#persistentTelemetryBtn"),
  recommendationsBtn: document.querySelector("#recommendationsBtn"),
  rulesBtn: document.querySelector("#rulesBtn"),
  historyBtn: document.querySelector("#historyBtn"),
  dryRunBtn: document.querySelector("#dryRunBtn"),
  updateRulesBtn: document.querySelector("#updateRulesBtn"),
  reloadRulesBtn: document.querySelector("#reloadRulesBtn"),
  rollbackRulesBtn: document.querySelector("#rollbackRulesBtn"),
  statusBadge: document.querySelector("#statusBadge"),
  remainingMeter: document.querySelector("#remainingMeter"),
  limitValue: document.querySelector("#limitValue"),
  remainingValue: document.querySelector("#remainingValue"),
  resetValue: document.querySelector("#resetValue"),
  retryValue: document.querySelector("#retryValue"),
  requestIdValue: document.querySelector("#requestIdValue"),
  bodyOutput: document.querySelector("#bodyOutput"),
  timeline: document.querySelector("#timeline"),
  eventCount: document.querySelector("#eventCount"),
  signalsOutput: document.querySelector("#signalsOutput"),
  persistedEventsValue: document.querySelector("#persistedEventsValue"),
  persistedDeniedValue: document.querySelector("#persistedDeniedValue"),
  persistedFailOpenValue: document.querySelector("#persistedFailOpenValue"),
  persistentTelemetryOutput: document.querySelector("#persistentTelemetryOutput"),
  recommendationsOutput: document.querySelector("#recommendationsOutput"),
  rulesOutput: document.querySelector("#rulesOutput"),
  historyOutput: document.querySelector("#historyOutput"),
  dryRunInput: document.querySelector("#dryRunInput"),
  dryRunOutput: document.querySelector("#dryRunOutput"),
  auditActorInput: document.querySelector("#auditActorInput"),
  auditSourceInput: document.querySelector("#auditSourceInput"),
  auditReasonInput: document.querySelector("#auditReasonInput"),
  rollbackVersionInput: document.querySelector("#rollbackVersionInput"),
  ruleChangeOutput: document.querySelector("#ruleChangeOutput"),
};

function requestHeaders(includeAdmin = false, includeAudit = false) {
  const headers = {};
  const apiKey = els.clientSelect.value;
  const adminKey = els.adminKeyInput.value.trim();

  if (apiKey) {
    headers["X-API-Key"] = apiKey;
  }

  if (includeAdmin && adminKey) {
    headers["X-Admin-Key"] = adminKey;
  }

  if (includeAudit) {
    const actor = els.auditActorInput.value.trim();
    const source = els.auditSourceInput.value.trim();
    const reason = els.auditReasonInput.value.trim();

    if (actor) {
      headers["X-Audit-Actor"] = actor;
    }

    if (source) {
      headers["X-Audit-Source"] = source;
    }

    if (reason) {
      headers["X-Audit-Reason"] = reason;
    }
  }

  return headers;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function readJson(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function setStatusBadge(status) {
  els.statusBadge.textContent = status || "Idle";
  els.statusBadge.classList.toggle("ok", status >= 200 && status < 300);
  els.statusBadge.classList.toggle("bad", status >= 400);
}

function updateHeaders(response) {
  const limit = response.headers.get("X-RateLimit-Limit") || "-";
  const remaining = response.headers.get("X-RateLimit-Remaining") || "-";
  const reset = response.headers.get("X-RateLimit-Reset") || "-";
  const retry = response.headers.get("Retry-After") || "-";
  const requestId = response.headers.get("X-Request-ID") || "-";

  els.limitValue.textContent = limit;
  els.remainingValue.textContent = remaining;
  els.resetValue.textContent = reset;
  els.retryValue.textContent = retry;
  els.requestIdValue.textContent = requestId;

  const limitNumber = Number(limit);
  const remainingNumber = Number(remaining);
  const percent = Number.isFinite(limitNumber) && limitNumber > 0 && Number.isFinite(remainingNumber)
    ? Math.max(0, Math.min(100, (remainingNumber / limitNumber) * 100))
    : 0;
  els.remainingMeter.style.width = `${percent}%`;
}

function addTimelineEvent(event) {
  state.events.unshift(event);
  state.events = state.events.slice(0, state.maxEvents);
  els.eventCount.textContent = String(state.events.length);

  els.timeline.replaceChildren(
    ...state.events.map((item) => {
      const row = document.createElement("li");
      const code = document.createElement("span");
      const meta = document.createElement("span");
      const retry = document.createElement("span");

      code.className = `code ${item.status >= 400 ? "bad" : "ok"}`;
      code.textContent = item.status;
      meta.className = "meta";
      meta.textContent = `${item.endpoint} / ${item.client || "anonymous"} / remaining ${item.remaining}`;
      retry.className = "meta";
      retry.textContent = item.retry === "-" ? item.time : `retry ${item.retry}s`;

      row.append(code, meta, retry);
      return row;
    }),
  );
}

async function sendRequest() {
  const endpoint = els.endpointSelect.value;
  const client = els.clientSelect.value;
  const response = await fetch(endpoint, { headers: requestHeaders(false) });
  const body = await readJson(response);

  setStatusBadge(response.status);
  updateHeaders(response);
  els.bodyOutput.textContent = pretty(body);

  addTimelineEvent({
    status: response.status,
    endpoint,
    client,
    remaining: response.headers.get("X-RateLimit-Remaining") || "-",
    retry: response.headers.get("Retry-After") || "-",
    time: new Date().toLocaleTimeString(),
  });
}

async function burstRequests() {
  els.burstBtn.disabled = true;
  try {
    for (let i = 0; i < 8; i += 1) {
      await sendRequest();
      await new Promise((resolve) => setTimeout(resolve, 80));
    }
  } finally {
    els.burstBtn.disabled = false;
  }
}

async function loadAdminJson(path, options, output) {
  const response = await fetch(path, {
    ...options,
    headers: requestHeaders(true),
  });
  const body = await readJson(response);
  output.textContent = pretty(body);
}

async function refreshSignals() {
  await loadAdminJson("/ai/signals", { method: "GET" }, els.signalsOutput);
}

function renderPersistentTelemetry(body) {
  const summary = body.summary || {};
  els.persistedEventsValue.textContent = summary.enabled ? summary.events ?? 0 : "Off";
  els.persistedDeniedValue.textContent = summary.enabled ? summary.denied ?? 0 : "-";
  els.persistedFailOpenValue.textContent = summary.enabled ? summary.redis_fail_open ?? 0 : "-";

  els.persistentTelemetryOutput.textContent = pretty({
    enabled: Boolean(summary.enabled),
    path: summary.path,
    persistent_errors: summary.persistent_errors ?? 0,
    routes: body.analytics?.routes || [],
    top_offenders: body.analytics?.top_offenders || [],
    recent_events: body.events || [],
  });
}

async function loadPersistentTelemetry() {
  const response = await fetch("/admin/telemetry/persistent?limit=10", {
    headers: requestHeaders(true),
  });
  renderPersistentTelemetry(await readJson(response));
}

async function runRecommendations() {
  await loadAdminJson("/ai/recommendations", { method: "POST" }, els.recommendationsOutput);
}

async function loadRules() {
  const response = await fetch("/admin/rules", { headers: requestHeaders(true) });
  const body = await readJson(response);
  els.rulesOutput.textContent = pretty(body);

  if (body.rules && !els.dryRunInput.value.trim()) {
    els.dryRunInput.value = pretty(body.rules);
  }
}

async function loadHistory() {
  const response = await fetch("/admin/rules/history", { headers: requestHeaders(true) });
  const body = await readJson(response);
  els.historyOutput.textContent = pretty(body);

  if (!els.rollbackVersionInput.value && body.current_version > 1) {
    els.rollbackVersionInput.value = String(body.current_version - 1);
  }
}

async function dryRunRules() {
  let payload;
  try {
    payload = JSON.parse(els.dryRunInput.value);
  } catch (error) {
    els.dryRunOutput.textContent = pretty({ error: error.message });
    return;
  }

  const response = await fetch("/admin/rules/dry-run", {
    method: "POST",
    headers: {
      ...requestHeaders(true),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await readJson(response);
  els.dryRunOutput.textContent = pretty(body);
}

function parseRulesEditor(output) {
  try {
    return JSON.parse(els.dryRunInput.value);
  } catch (error) {
    output.textContent = pretty({ error: error.message });
    return null;
  }
}

async function applyRulesUpdate() {
  const payload = parseRulesEditor(els.ruleChangeOutput);
  if (!payload) {
    return;
  }

  const response = await fetch("/admin/rules", {
    method: "PUT",
    headers: {
      ...requestHeaders(true, true),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await readJson(response);
  els.ruleChangeOutput.textContent = pretty(body);

  if (response.ok) {
    els.rulesOutput.textContent = pretty(body);
    await loadHistory();
  }
}

async function reloadRules() {
  const response = await fetch("/admin/rules/reload", {
    method: "POST",
    headers: requestHeaders(true, true),
  });
  const body = await readJson(response);
  els.ruleChangeOutput.textContent = pretty(body);

  if (response.ok) {
    els.rulesOutput.textContent = pretty(body);
    await loadHistory();
  }
}

async function rollbackRules() {
  const version = Number.parseInt(els.rollbackVersionInput.value, 10);
  if (!Number.isInteger(version) || version < 1) {
    els.ruleChangeOutput.textContent = pretty({ error: "Rollback version must be a positive integer." });
    return;
  }

  const response = await fetch(`/admin/rules/rollback/${version}`, {
    method: "POST",
    headers: requestHeaders(true, true),
  });
  const body = await readJson(response);
  els.ruleChangeOutput.textContent = pretty(body);

  if (response.ok) {
    els.rulesOutput.textContent = pretty(body);
    await loadHistory();
  }
}

async function refreshAll() {
  await Promise.allSettled([
    checkReady(),
    refreshSignals(),
    loadPersistentTelemetry(),
    loadRules(),
    loadHistory(),
  ]);
}

async function checkReady() {
  try {
    const response = await fetch("/ready");
    const body = await readJson(response);
    const ok = response.ok;
    els.readyDot.classList.toggle("ok", ok);
    els.readyDot.classList.toggle("bad", !ok);
    els.readyText.textContent = ok ? "Ready" : body.redis || "Not ready";
  } catch {
    els.readyDot.classList.remove("ok");
    els.readyDot.classList.add("bad");
    els.readyText.textContent = "Offline";
  }
}

els.sendOneBtn.addEventListener("click", () => {
  sendRequest().catch((error) => {
    els.bodyOutput.textContent = pretty({ error: error.message });
  });
});

els.burstBtn.addEventListener("click", () => {
  burstRequests().catch((error) => {
    els.bodyOutput.textContent = pretty({ error: error.message });
  });
});

els.refreshBtn.addEventListener("click", () => {
  refreshAll();
});

els.signalsBtn.addEventListener("click", () => {
  refreshSignals();
});

els.persistentTelemetryBtn.addEventListener("click", () => {
  loadPersistentTelemetry();
});

els.recommendationsBtn.addEventListener("click", () => {
  runRecommendations();
});

els.rulesBtn.addEventListener("click", () => {
  loadRules();
});

els.historyBtn.addEventListener("click", () => {
  loadHistory();
});

els.dryRunBtn.addEventListener("click", () => {
  dryRunRules();
});

els.updateRulesBtn.addEventListener("click", () => {
  applyRulesUpdate();
});

els.reloadRulesBtn.addEventListener("click", () => {
  reloadRules();
});

els.rollbackRulesBtn.addEventListener("click", () => {
  rollbackRules();
});

checkReady();
