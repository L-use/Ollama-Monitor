/* Ollama Monitor dashboard logic. */
(function () {
  const $ = (id) => document.getElementById(id);
  const t = (k, p) => window.I18N.t(k, p);

  const state = {
    page: 1,
    limit: 20,
    charts: {},
    status: null,
    settings: {},
  };

  // ---------------- formatting helpers ----------------
  function fmtNum(n) {
    if (n == null) return "—";
    return Number(n).toLocaleString();
  }
  function fmtBytes(n) {
    if (n == null) return "N/A";
    const v = Number(n);
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0, x = v;
    while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
    return x.toFixed(x >= 100 ? 0 : 1) + " " + units[i];
  }
  function fmtNs(ns) {
    if (ns == null) return "N/A";
    const s = Number(ns) / 1e9;
    if (s < 1) return (s * 1000).toFixed(0) + " ms";
    return s.toFixed(2) + " s";
  }
  function fmtUptime(sec) {
    if (sec == null) return "—";
    sec = Math.floor(sec);
    if (sec < 60) return sec + "s";
    const m = Math.floor(sec / 60);
    if (m < 60) return m + "m " + (sec % 60) + "s";
    const h = Math.floor(m / 60);
    return h + "h " + (m % 60) + "m";
  }
  function fmtDate(ts) {
    if (ts == null) return "—";
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  function fmtTps(v) {
    if (v == null) return "N/A";
    return Number(v).toFixed(2);
  }

  // ---------------- data fetchers ----------------
  async function getJSON(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  // ---------------- section renderers ----------------
  function renderStatus(s) {
    const online = s.online;
    const pill = $("ollamaPill");
    pill.dataset.state = online ? "online" : "offline";
    $("ollamaPillText").textContent = t(online ? "status.online" : "status.offline");

    const el = $("ovOllama");
    el.textContent = t(online ? "status.online" : "status.offline");
    el.className = "stat-value " + (online ? "online" : "offline");
    $("ovOllamaVersion").textContent = s.version ? "v" + s.version : "";

    const running = s.running || [];
    if (running.length === 0) {
      $("ovRunningModel").textContent = "—";
      $("ovRunningModelSub").textContent = t("common.noData");
    } else {
      const r0 = running[0];
      $("ovRunningModel").textContent = r0.name;
      $("ovRunningModelSub").textContent =
        (r0.size_vram_human ? "VRAM " + r0.size_vram_human : "") +
        (running.length > 1 ? " +" + (running.length - 1) : "");
    }

    $("ovInstalled").textContent = (s.installed || []).length;

    renderModels(s.installed || [], running);
    state.status = s;
  }

  function renderModels(installed, running) {
    const body = $("modelsBody");
    if (!installed.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">${t("common.emptyModels")}</td></tr>`;
      return;
    }
    const runningByName = {};
    (running || []).forEach((r) => (runningByName[r.name] = r));

    body.innerHTML = installed
      .map((m) => {
        const r = runningByName[m.name];
        const isRunning = !!r;
        const status = isRunning
          ? `<span class="badge online">${t("status.running")}</span>`
          : `<span class="badge offline">${t("status.idle")}</span>`;
        const vram = isRunning && r.size_vram_human ? r.size_vram_human : "N/A";
        const uptime = isRunning ? fmtUptime(r.running_for_seconds) : "—";
        return `<tr>
          <td class="mono">${m.name}</td>
          <td>${m.parameter_size || "—"}</td>
          <td>${m.size_human || "—"}</td>
          <td>${m.context_length ? fmtNum(m.context_length) : "—"}</td>
          <td>${status}</td>
          <td class="mono">${vram}</td>
          <td class="mono">${uptime}</td>
        </tr>`;
      })
      .join("");
  }

  function renderHardware(h) {
    const g = h.gpu || {};
    $("ovGpu").textContent = g.util != null ? g.util + "%" : "N/A";
    $("ovGpuSub").textContent =
      (g.name ? g.name + " · " : "") +
      (g.temp != null ? g.temp + "°C" : "") +
      (g.power != null ? " · " + g.power + "W" : "");
    $("ovCpu").textContent = h.cpu_util != null ? h.cpu_util + "%" : "N/A";
    const m = h.memory || {};
    if (m.percent != null) {
      $("ovMem").textContent = m.percent + "%";
      $("ovMemSub").textContent = fmtBytes(m.used_bytes) + " / " + fmtBytes(m.total_bytes);
    } else {
      $("ovMem").textContent = "N/A";
    }
  }

  function renderStats(s) {
    const today = s.today || {};
    $("tkTodayIn").textContent = fmtNum(today.prompt_tokens);
    $("tkTodayOut").textContent = fmtNum(today.completion_tokens);
    $("tkTodayTotal").textContent = fmtNum(today.total_tokens);
    $("tkTotal").textContent = fmtNum(s.total_tokens);
    $("tkCurrentSpeed").textContent = fmtTps(s.latest_tps);
    $("tkAvgSpeed").textContent = fmtTps(s.avg_tps);

    // per-model list
    const list = $("perModelList");
    const pm = s.per_model || [];
    if (!pm.length) {
      list.innerHTML = `<div class="empty">${t("common.noData")}</div>`;
    } else {
      const max = Math.max(...pm.map((x) => x.total_tokens), 1);
      list.innerHTML = pm
        .map((x) => {
          const pct = Math.round((x.total_tokens / max) * 100);
          return `<div class="per-model-item">
            <span class="name">${x.model}</span>
            <span class="tokens">${fmtNum(x.total_tokens)} (${pct}%)</span>
          </div>`;
        })
        .join("");
    }

    // daily chart (last 7 days ascending)
    const daily = (s.daily || []).slice(0, 7).reverse();
    if (daily.length) {
      updateChart("dailyChart", {
        labels: daily.map((d) => d.day.slice(5)),
        datasets: [
          { label: t("tokens.todayIn"), data: daily.map((d) => d.prompt_tokens), borderColor: "#4f8cff", backgroundColor: "rgba(79,140,255,.12)" },
          { label: t("tokens.todayOut"), data: daily.map((d) => d.completion_tokens), borderColor: "#35d0a5", backgroundColor: "rgba(53,208,165,.12)" },
        ],
      });
    }
  }

  function renderHistory(data) {
    const body = $("historyBody");
    if (!data.items.length) {
      body.innerHTML = `<tr><td colspan="8" class="empty">${t("common.emptyHistory")}</td></tr>`;
    } else {
      body.innerHTML = data.items
        .map((r) => {
          const statusCls = r.status === "success" ? "success" : r.status === "interrupted" ? "interrupted" : "error";
          return `<tr>
            <td class="mono">${fmtDate(r.created_at)}</td>
            <td class="mono">${r.model || "—"}</td>
            <td class="num">${fmtNum(r.prompt_tokens)}</td>
            <td class="num">${fmtNum(r.completion_tokens)}</td>
            <td class="num">${fmtTps(r.tokens_per_sec)}</td>
            <td class="mono">${fmtNs(r.total_duration_ns)}</td>
            <td><span class="badge ${statusCls}">${t("status." + r.status)}</span></td>
            <td><button class="btn" data-id="${r.id}">⤢</button></td>
          </tr>`;
        })
        .join("");
    }
    body.querySelectorAll("button[data-id]").forEach((b) =>
      b.addEventListener("click", () => openDetail(Number(b.dataset.id)))
    );
    renderPagination(data);
  }

  function renderPagination(data) {
    const totalPages = Math.max(1, Math.ceil(data.total / data.limit));
    const p = $("pagination");
    p.innerHTML = `
      <button id="pgPrev" ${data.page <= 1 ? "disabled" : ""}>${t("common.prev")}</button>
      <span class="page-info">${t("common.page", { page: data.page, total: totalPages })}</span>
      <button id="pgNext" ${data.page >= totalPages ? "disabled" : ""}>${t("common.next")}</button>
      <span class="page-info">${fmtNum(data.total)} ${t("common.requests")}</span>`;
    $("pgPrev").addEventListener("click", () => { state.page--; refreshHistory(); });
    $("pgNext").addEventListener("click", () => { state.page++; refreshHistory(); });
  }

  async function openDetail(id) {
    try {
      const r = await getJSON("/api/monitor/requests/" + id);
      const rows = [
        [t("detail.model"), r.model || "—"],
        [t("detail.time"), fmtDate(r.created_at)],
        [t("detail.stream"), r.stream ? t("common.yes") : t("common.no")],
        [t("detail.status"), t("status." + r.status)],
        [t("detail.promptTokens"), fmtNum(r.prompt_tokens)],
        [t("detail.completionTokens"), fmtNum(r.completion_tokens)],
        [t("detail.totalTokens"), fmtNum(r.total_tokens)],
        [t("detail.speed"), fmtTps(r.tokens_per_sec) + " tok/s"],
        [t("detail.totalDuration"), fmtNs(r.total_duration_ns)],
        [t("detail.evalDuration"), fmtNs(r.eval_duration_ns)],
        [t("detail.loadDuration"), fmtNs(r.load_duration_ns)],
        [t("detail.ttft"), r.time_to_first_token_ms != null ? r.time_to_first_token_ms + " ms" : "N/A"],
      ];
      if (r.error) rows.push([t("detail.error"), r.error]);
      if (r.client) rows.push([t("detail.client"), r.client]);
      $("detailBody").innerHTML =
        `<dl class="kv">` + rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") + `</dl>`;
      $("detailModal").hidden = false;
    } catch (e) {
      $("detailBody").innerHTML = `<div class="empty">${t("common.loading")} — ${t("common.noData")}</div>`;
      $("detailModal").hidden = false;
    }
  }

  // ---------------- charts ----------------
  function baseChart(elId) {
    const el = $(elId);
    if (state.charts[elId]) return state.charts[elId];
    const chart = new Chart(el, {
      type: "line",
      data: { labels: [], datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { display: false },
          y: { beginAtZero: true, ticks: { color: _cssVar("--muted") || "#8a94a8", font: { size: 10 } }, grid: { color: _cssVar("--grid-line") || "rgba(255,255,255,.05)" } },
        },
        plugins: { legend: { display: false } },
      },
    });
    state.charts[elId] = chart;
    return chart;
  }
  function updateChart(elId, cfg) {
    const chart = baseChart(elId);
    chart.data.labels = cfg.labels;
    chart.data.datasets = cfg.datasets;
    chart.update();
  }

  function renderHardwareHistory(samples) {
    if (!samples.length) return;
    const labels = samples.map((s) => {
      const d = new Date(s.created_at * 1000);
      return d.getHours() + ":" + String(d.getMinutes()).padStart(2, "0") + ":" + String(d.getSeconds()).padStart(2, "0");
    });
    const ds = (key, color, fill) => ({
      label: "", data: samples.map((s) => s[key]), borderColor: color, backgroundColor: fill, borderWidth: 1, pointRadius: 0, tension: 0.3, fill: true,
    });
    updateChart("gpuChart", { labels, datasets: [ds("gpu_util", "#4f8cff", "rgba(79,140,255,.10)")] });
    updateChart("vramChart", { labels, datasets: [ds("gpu_mem_used", "#35d0a5", "rgba(53,208,165,.10)")] });
    updateChart("tempChart", { labels, datasets: [ds("gpu_temp", "#ffb454", "rgba(255,180,84,.10)")] });
    updateChart("cpuChart", { labels, datasets: [ds("cpu_util", "#b48cff", "rgba(180,140,255,.10)")] });
    const memPct = samples.map((s) => (s.mem_total ? Math.round((s.mem_used / s.mem_total) * 1000) / 10 : null));
    updateChart("memChart", { labels, datasets: [{ label: "", data: memPct, borderColor: "#ff7aa2", backgroundColor: "rgba(255,122,162,.10)", borderWidth: 1, pointRadius: 0, tension: 0.3, fill: true }] });
  }

  // ---------------- refresh orchestration ----------------
  async function refreshStatus() {
    try { renderStatus(await getJSON("/api/monitor/status")); } catch (e) {}
  }
  async function refreshHardware() {
    try { renderHardware(await getJSON("/api/monitor/hardware")); } catch (e) {}
  }
  async function refreshStats() {
    try { renderStats(await getJSON("/api/monitor/stats")); } catch (e) {}
  }
  async function refreshHistory() {
    try {
      const model = $("filterModel").value;
      const date = $("filterDate").value;
      const q = $("filterSearch").value.trim();
      const params = new URLSearchParams({ page: state.page, limit: state.limit });
      if (model) params.set("model", model);
      if (date) params.set("date", date);
      if (q) params.set("q", q);
      renderHistory(await getJSON("/api/monitor/requests?" + params));
    } catch (e) {}
  }
  async function refreshHwHistory() {
    try {
      const data = await getJSON("/api/monitor/hardware/history?minutes=30");
      renderHardwareHistory(data.samples || []);
    } catch (e) {}
  }
  async function refreshModelsFilter() {
    try {
      const data = await getJSON("/api/monitor/models");
      const sel = $("filterModel");
      const cur = sel.value;
      sel.innerHTML = `<option value="">${t("history.model")} — all</option>` +
        (data.models || []).map((m) => `<option value="${m}">${m}</option>`).join("");
      sel.value = cur;
    } catch (e) {}
  }

  window.refreshAll = () => {
    refreshStatus();
    refreshHardware();
    refreshStats();
    refreshHistory();
    refreshModelsFilter();
    refreshHwHistory();
  };

  // ---------------- theme (dark / light / system) ----------------
  const THEME_KEY = "om-theme";  // 'dark' | 'light' | 'system'
  const THEME_ICONS = { dark: "🌙", light: "☀️", system: "🌓" };
  const THEME_NEXT = { dark: "light", light: "system", system: "dark" };

  function currentTheme() {
    return localStorage.getItem(THEME_KEY) || "system";
  }
  function resolvedTheme() {
    const t = currentTheme();
    if (t === "system") {
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    return t;
  }
  function applyTheme() {
    const resolved = resolvedTheme();
    document.documentElement.setAttribute("data-theme", resolved);
    const btn = $("themeToggle");
    if (btn) { btn.textContent = THEME_ICONS[currentTheme()]; btn.title = "主题：" + currentTheme(); }
    // 同步图表坐标轴颜色
    const cs = getComputedStyle(document.documentElement);
    const muted = cs.getPropertyValue("--muted").trim() || "#8a94a8";
    const grid = cs.getPropertyValue("--grid-line").trim() || "rgba(255,255,255,.05)";
    Object.values(state.charts).forEach((c) => {
      try {
        c.options.scales.y.ticks.color = muted;
        c.options.scales.y.grid.color = grid;
        c.update();
      } catch (e) {}
    });
  }
  function cycleTheme() {
    localStorage.setItem(THEME_KEY, THEME_NEXT[currentTheme()]);
    applyTheme();
  }

  // ---------------- events ----------------
  function bindEvents() {
    $("langToggle").addEventListener("click", () => window.I18N.toggle());
    $("themeToggle").addEventListener("click", cycleTheme);
    $("filterModel").addEventListener("change", () => { state.page = 1; refreshHistory(); });
    $("filterDate").addEventListener("change", () => { state.page = 1; refreshHistory(); });
    $("filterSearch").addEventListener("input", debounce(() => { state.page = 1; refreshHistory(); }, 400));
    $("btnClearDate").addEventListener("click", () => { $("filterDate").value = ""; state.page = 1; refreshHistory(); });
    $("btnExport").addEventListener("click", () => { window.open("/api/monitor/export.csv", "_blank"); });
    $("btnClearHistory").addEventListener("click", async () => {
      if (!confirm(t("common.confirmClear"))) return;
      try {
        await fetch("/api/monitor/requests", { method: "DELETE" });
        state.page = 1;
        // Reset every filter so records created AFTER the clear are not
        // silently hidden by leftover search / date / model criteria.
        $("filterSearch").value = "";
        $("filterDate").value = "";
        $("filterModel").value = "";
        refreshStats();
        refreshHistory();
        refreshModelsFilter();
      } catch (e) {}
    });
    $("detailClose").addEventListener("click", () => { $("detailModal").hidden = true; });
    $("detailModal").addEventListener("click", (e) => {
      if (e.target === $("detailModal")) $("detailModal").hidden = true;
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !$("detailModal").hidden) $("detailModal").hidden = true;
    });
  }

  function debounce(fn, ms) {
    let h;
    return (...args) => { clearTimeout(h); h = setTimeout(() => fn(...args), ms); };
  }

  // ---------------- boot ----------------
  async function boot() {
    let lang = localStorage.getItem("om-language");
    try {
      const s = await getJSON("/api/settings");
      state.settings = s;
      lang = s.language || lang;
      $("appVersion").textContent = "";
    } catch (e) {}
    await window.I18N.load(lang || "zh-CN");
    bindEvents();
    applyTheme();
    refreshAll();

    // Self-healing 1s polling: each loop waits for the previous fetch to
    // finish, then sleeps 1s before re-running. This gives ~1 Hz updates
    // (near-real-time) without piling up overlapping requests.
    const POLL_EVERY = 1000;
    (async function liveLoop() {
      while (true) {
        const started = Date.now();
        await Promise.all([
          refreshHardware(),
          refreshStatus(),
          refreshStats(),
          refreshHwHistory(),
          refreshHistory(),
        ]);
        const elapsed = Date.now() - started;
        await sleep(Math.max(0, POLL_EVERY - elapsed));
      }
    })();
  }

  function _cssVar(name) {
    try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
    catch (e) { return null; }
  }
  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
