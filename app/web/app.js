"use strict";

let currentTaskId = null;
let currentAxles = [];
let timer = null;
let reportToken = 0; // 报告打开令牌：守卫快速切换任务时的异步竞态

const $ = (id) => document.getElementById(id);

function formatTs(seconds) {
  seconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const { timeoutMs, ...fetchOptions } = options; // timeoutMs 为内部参数，不透传给 fetch
  const timer = setTimeout(() => controller.abort(), timeoutMs || 45000); // 默认 45s 超时
  try {
    const resp = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      ...fetchOptions,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const j = await resp.json();
        detail = j.detail || detail;
      } catch (e) { /* ignore */ }
      throw new Error(detail);
    }
    return resp.json();
  } catch (e) {
    if (e.name === "AbortError") {
      throw new Error("服务响应超时（可能正在本地转写，稍候重试）");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;");
}

/* ---------------- 任务列表 ---------------- */

function taskStatusBadge(task) {
  const cls = task.status || "pending";
  const text = { pending: "等待中", running: "运行中", done: "完成", failed: "失败" }[cls] || cls;
  return `<span class="status ${cls}">${text}</span>`;
}

function renderTasks(tasks) {
  const html = tasks.length
    ? tasks.map((t) => {
        const progress = t.progress || 0;
        const active = t.id === currentTaskId ? " active" : "";
        const fileName = (t.video_path || "").split(/[\\/]/).pop() || t.video_path || "";
        const pct = (t.status === "running" || t.status === "pending") ? `<span class="task-pct">${progress}%</span>` : "";
        return `
      <div class="task-item${active}" data-id="${t.id}" title="${escapeAttr(t.video_path || "")}（单击查看打轴结果）">
        <div class="info">
          <div class="name">${escapeHtml(fileName)}</div>
          <div class="meta">${escapeHtml(t.message || t.id)}</div>
        </div>
        <div class="row">
          <div class="progress"><div style="width:${progress}%"></div></div>
          ${taskStatusBadge(t)}
          ${pct}
        </div>
        <div class="row">
          <button data-id="${t.id}" class="btn-delete ghost">删除</button>
          <button data-id="${t.id}" class="btn-reaxle-task ghost" title="重新调整切片区间与详细解释（复用转写，不重复计费）">重新打轴</button>
        </div>
      </div>`;
      }).join("")
    : `<div class="task-empty">
         <div class="task-empty-icon">🎬</div>
         <div>还没有任务</div>
         <div class="task-empty-sub">在首页输入视频路径，点击「开始打轴」</div>
       </div>`;

  ["task-list", "win-task-list"].forEach((id) => {
    $(id).innerHTML = html;
  });
  // 列表标题带计数：任务列表 · N
  const countText = tasks.length ? `任务列表 · ${tasks.length}` : "任务列表";
  document.querySelectorAll(".home-tasks-title, .win-tasks-title").forEach((el) => {
    el.textContent = countText;
  });
  document.querySelectorAll(".task-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;  // 按钮点击不触发整块切换
      openReport(el.dataset.id);
    });
  });
  document.querySelectorAll(".btn-reaxle-task").forEach((btn) => {
    btn.addEventListener("click", () => openReaxle(btn.dataset.id));
  });
  document.querySelectorAll(".btn-delete").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("确定删除该任务及其所有分析产物？")) return;
      try {
        await api(`/api/tasks/${btn.dataset.id}`, { method: "DELETE" });
        await loadTasks();
        if (currentTaskId === btn.dataset.id) closeReport();
      } catch (err) {
        if (String(err.message).includes("正在运行") && confirm("任务正在运行，是否强制删除？")) {
          try {
            await api(`/api/tasks/${btn.dataset.id}?force=true`, { method: "DELETE" });
            await loadTasks();
            if (currentTaskId === btn.dataset.id) closeReport();
          } catch (err2) {
            alert("强制删除失败：" + err2.message);
          }
          return;
        }
        alert("删除失败：" + err.message);
      }
    });
  });
}

/* ---------------- 打轴结果 ---------------- */

function renderReport(task) {
  $("report-title").textContent = `打轴结果（${task.id}）`;
  $("report-status").textContent = `状态：${task.status}（${task.progress || 0}%） · ${task.message || ""}`;
  $("link-video").href = `/api/tasks/${task.id}/video`;
  $("link-csv").href = `/api/tasks/${task.id}/axles.csv`;
  $("report-card").classList.remove("hidden");
  $("win-empty").classList.add("hidden");
  const srtBox = $("srt-hint");
  if (task.srt_path) {
    srtBox.textContent = `📝 字幕文件已保存至：${task.srt_path}`;
    srtBox.classList.remove("hidden");
  } else {
    srtBox.classList.add("hidden");
  }
}

function scoreClass(score) {
  const s = Number(score) || 0;
  if (s >= 9) return "score-high";
  if (s >= 7) return "score-mid";
  return "score-low";
}

function renderAxles(axles) {
  const scoreFilter = Number($("score-filter").value) || 0;
  const box = $("axles-container");
  const countEl = $("score-filter-count");
  if (countEl) {
    countEl.textContent = axles.length ? `显示 ${axles.filter((a) => (Number(a.score) || 0) >= scoreFilter).length} / ${axles.length} 个轴` : "";
  }
  if (!axles.length) {
    box.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">✂️</div>
      <div>暂无切片轴</div>
      <div>任务完成后自动生成；若任务已完成，可点「重新打轴」调整参数重试</div>
    </div>`;
    return;
  }
  const filtered = axles.filter((a) => Number(a.score || 0) >= scoreFilter);
  if (!filtered.length) {
    box.innerHTML = `<div class="empty-state">
      <div class="empty-state-icon">🔍</div>
      <div>没有符合条件的轴</div>
      <div>当前最低评分 ${scoreFilter} 分，试试调低筛选值</div>
    </div>`;
    return;
  }
  box.innerHTML = filtered.map((a) => {
    const start = a.review_start ?? a.start;
    const end = a.review_end ?? a.end;
    const title = a.review_title || a.title || "";
    const duration = Math.max(0, Math.round(end - start));
    const reviewed = a.reviewed ? " · 已复核" : "";
    const cls = scoreClass(a.score);
    const peaks = a.danmaku_peaks || [];
    const peaksHtml = peaks.length
      ? `<div class="axle-peaks">🔥 弹幕高峰：${peaks.map((p) =>
          `<a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${p.t}">${formatTs(p.t)}（${p.count}条/分）</a>`
        ).join("  ")}</div>`
      : "";
    const copyText = `[${formatTs(start)} - ${formatTs(end)}] ${title}`;
    return `
      <div class="axle-item ${cls}">
        <div class="head">
          <span class="title"><a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${start}">[${formatTs(start)} - ${formatTs(end)}]</a> ${escapeHtml(title)}</span>
          <span class="badge ${cls}">${a.score ?? 0} 分 · ${duration}s${reviewed}</span>
        </div>
        <div class="meta"><b>理由：</b>${escapeHtml(a.reason || "（无）")}</div>
        ${peaksHtml}
        <div class="actions">
          <button class="btn-edit" data-id="${a.id}">复核打轴</button>
          <button class="btn-export-one" data-id="${a.id}">导出此切片</button>
          <button class="btn-copy-one" data-text="${escapeAttr(copyText)}">复制</button>
        </div>
      </div>`;
  }).join("");
  document.querySelectorAll(".btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => openEdit(btn.dataset.id));
  });
  document.querySelectorAll(".btn-export-one").forEach((btn) => {
    btn.addEventListener("click", () => exportAxleIds([Number(btn.dataset.id)], btn));
  });
  document.querySelectorAll(".btn-copy-one").forEach((btn) => {
    btn.addEventListener("click", () => copyToClipboard(btn.dataset.text, "该轴时间标记"));
  });
}

/* ---------------- 复制（共享表格友好） ---------------- */

async function copyToClipboard(text, label) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast(`✅ 已复制${label || ""}到剪贴板（可直接粘贴到 Excel / 共享表格）`);
}

function toast(msg) {
  // 轻量提示条：不占用报告状态栏（避免被进度轮询冲掉）
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.remove("show"), 2500);
}

/* ---------------- 深浅主题 ---------------- */

function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("lca-theme", theme); } catch (e) { /* ignore */ }
  updateThemeIcon();
}

function updateThemeIcon() {
  const btn = $("btn-theme");
  if (!btn) return;
  const light = currentTheme() === "light";
  btn.textContent = light ? "☀️" : "🌙";
  btn.title = light ? "切换到深色主题" : "切换到浅色主题";
}

function initTheme() {
  $("btn-theme").addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark");
  });
  updateThemeIcon();
}

function buildAxlesTsv() {
  const rows = [["开始", "结束", "时长(秒)", "标题", "推荐理由", "评分"]];
  const sorted = [...currentAxles].sort((x, y) => (x.review_start ?? x.start) - (y.review_start ?? y.start));
  for (const a of sorted) {
    const start = a.review_start ?? a.start;
    const end = a.review_end ?? a.end;
    rows.push([
      formatTs(start),
      formatTs(end),
      String(Math.max(0, Math.round(end - start))),
      a.review_title || a.title || "",
      a.reason || "",
      String(a.score ?? 0),
    ]);
  }
  return rows.map((r) => r.join("\t")).join("\n");
}

function openEdit(axleId) {
  const a = currentAxles.find((x) => String(x.id) === String(axleId));
  if (!a) return;
  $("edit-id").value = a.id;
  $("edit-start").value = a.review_start ?? a.start ?? 0;
  $("edit-end").value = a.review_end ?? a.end ?? 0;
  $("edit-title").value = a.review_title || a.title || "";
  $("edit-modal").classList.remove("hidden");
}

/* ---------------- 窗口开关（第二页嵌套覆盖） ---------------- */

function openWindow() {
  document.body.classList.add("view-report");
}

function closeReport() {
  document.body.classList.remove("view-report");
  reportToken++; // 使在飞的 openReport/轮询回调失效
  currentTaskId = null;
  $("report-card").classList.add("hidden");
  $("win-empty").classList.remove("hidden");
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

async function openReport(taskId) {
  const token = ++reportToken;
  currentTaskId = taskId;
  resetSubtitleState();
  $("score-filter").value = "0"; // 评分筛选随任务切换重置
  openWindow();
  const task = await api(`/api/tasks/${taskId}`);
  if (token !== reportToken) return;
  renderReport(task);
  await loadTasks();
  if (token !== reportToken) return;
  $("export-results").innerHTML = `<div class="muted">暂无导出结果。</div>`;
  await loadExportResults();
  if (token !== reportToken) return;
  await refreshReportData(taskId);
  if (token !== reportToken) return;
  startPolling(taskId, token);
}

async function refreshReportData(taskId) {
  const tid = taskId || currentTaskId;
  if (!tid) return;
  const axles = await api(`/api/tasks/${tid}/axles`);
  if (currentTaskId !== tid) return; // 已被切换到其他任务，丢弃过期数据
  currentAxles = axles;
  renderAxles(axles);
}

/* ---------------- 导出 ---------------- */

function renderExportResults(files) {
  const box = $("export-results");
  if (!files || !files.length) {
    box.innerHTML = `<div class="muted">暂无导出结果。</div>`;
    return;
  }
  box.innerHTML = files.map((f) => {
    const timeText = `[${formatTs(f.start)} - ${formatTs(f.end)}]`;
    if (f.status !== "ok") {
      return `<div class="export-item">${timeText} ${escapeHtml(f.title)} — 失败：${escapeHtml(f.error || "未知错误")}</div>`;
    }
    const href = `/api/tasks/${currentTaskId}/exports/${encodeURIComponent(f.filename)}`;
    return `<div class="export-item">
      ${timeText} ${escapeHtml(f.title || "")}
      <a class="btn" href="${href}" target="_blank">下载</a>
      <a class="btn ghost" href="/static/preview.html?task=${currentTaskId}&t=${f.start}" target="_blank">预览</a>
    </div>`;
  }).join("");
}

async function loadExportResults() {
  if (!currentTaskId) return;
  try {
    const files = await api(`/api/tasks/${currentTaskId}/exports`);
    renderExportResults(files || []);
  } catch (err) {
    console.error("加载导出结果失败", err);
  }
}

async function exportAxleIds(axleIds, btn) {
  if (!currentTaskId) return;
  const oldText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "导出中…";
  }
  try {
    const payload = axleIds ? { axle_ids: axleIds } : {};
    if ($("export-accurate").checked) payload.accurate = true;
    const result = await api(`/api/tasks/${currentTaskId}/export`, {
      method: "POST",
      body: JSON.stringify(payload),
      timeoutMs: 600000, // 导出（尤其精切重编码）可能远超 45s 默认超时
    });
    renderExportResults(result.files || []);
    const okCount = (result.files || []).filter((f) => f.status === "ok").length;
    $("report-status").textContent = `导出完成：成功 ${okCount} / 共 ${(result.files || []).length} 个，目录：${result.export_dir || ""}`;
  } catch (err) {
    alert("导出失败：" + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  }
}

function startPolling(taskId, token) {
  if (timer) clearInterval(timer);
  const myToken = token === undefined ? reportToken : token;
  timer = setInterval(async () => {
    try {
      const task = await api(`/api/tasks/${taskId}`);
      // 报告已切换到其他任务：静默退出，不碰新任务的 timer / 状态
      if (myToken !== reportToken || currentTaskId !== taskId) return;
      $("report-status").textContent = `状态：${task.status}（${task.progress || 0}%） · ${task.message || ""}`;
      if (task.status === "done" || task.status === "failed") {
        clearInterval(timer);
        timer = null;
        await refreshReportData(taskId);
      }
    } catch (e) {
      if (myToken === reportToken) {
        clearInterval(timer);
        timer = null;
      }
    }
  }, 3000);
}

/* ---------------- 重新打轴 ---------------- */

let reaxleTaskId = null;

async function openReaxle(taskId) {
  reaxleTaskId = taskId || currentTaskId;
  if (!reaxleTaskId) return;
  // 预填当前生效的打轴参数（设置页保存的新配置自动生效）
  try {
    const cfg = await api("/api/config");
    $("reaxle-min").value = cfg.target_min_seconds ?? 30;
    $("reaxle-max").value = cfg.target_max_seconds ?? 3600;
  } catch (e) {
    $("reaxle-min").value = 30;
    $("reaxle-max").value = 3600;
  }
  $("reaxle-fine").checked = false;
  $("reaxle-modal").classList.remove("hidden");
}

/* ---------------- 字幕页 ---------------- */

let subtitleContentRaw = "";
let subtitleEntries = []; // [{start, end, text}]

function parseSrt(content) {
  const entries = [];
  const lines = content.split(String.fromCharCode(10));
  for (let i = 0; i < lines.length - 2; i++) {
    const m = (lines[i + 1] || "").match(
      /(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})/
    );
    if (m) {
      const toSec = (h, mi, s, ms) => Number(h) * 3600 + Number(mi) * 60 + Number(s) + Number(ms) / 1000;
      entries.push({
        start: toSec(m[1], m[2], m[3], m[4]),
        end: toSec(m[5], m[6], m[7], m[8]),
        text: (lines[i + 2] || "").trim(),
      });
      i += 2;
    }
  }
  return entries;
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function resetSubtitleState() {
  // 打开新任务时清空字幕页状态，避免展示上一个任务的陈旧字幕
  subtitleContentRaw = "";
  subtitleEntries = [];
  const box = $("subtitle-content");
  if (box) box.textContent = "";
  const results = $("subtitle-results");
  if (results) {
    results.classList.add("hidden");
    results.innerHTML = "";
  }
  const search = $("subtitle-search");
  if (search) search.value = "";
  const pathEl = $("subtitle-path");
  if (pathEl) pathEl.textContent = "";
  const countEl = $("subtitle-count");
  if (countEl) countEl.textContent = "";
  const copyBtn = $("btn-copy-srt-path");
  if (copyBtn) copyBtn.disabled = true;
  // 回到「切片轴」标签页
  document.querySelectorAll(".win-tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === "axles");
  });
  $("tab-axles").classList.remove("hidden");
  $("tab-subtitle").classList.add("hidden");
}

async function loadSubtitle() {
  if (!currentTaskId) return;
  const box = $("subtitle-content");
  try {
    const data = await api(`/api/tasks/${currentTaskId}/subtitle`);
    $("subtitle-path").textContent = data.path;
    subtitleContentRaw = data.content || "";
    subtitleEntries = parseSrt(subtitleContentRaw);
    box.textContent = subtitleContentRaw || "（空）";
    $("subtitle-search").value = "";
    $("subtitle-results").classList.add("hidden");
    $("subtitle-results").innerHTML = "";
    const countEl = $("subtitle-count");
    if (countEl) countEl.textContent = subtitleEntries.length ? `共 ${subtitleEntries.length} 句` : "";
    $("btn-copy-srt-path").disabled = false;
  } catch (err) {
    box.textContent = "字幕文件尚未生成（ASR 转写完成后自动生成），错误：" + err.message;
    $("btn-copy-srt-path").disabled = true;
  }
}

function renderSubtitleHighlight(keyword) {
  const box = $("subtitle-content");
  if (!keyword) {
    box.textContent = subtitleContentRaw;
    return;
  }
  const esc = escapeHtml(subtitleContentRaw);
  const re = new RegExp(escapeRegExp(escapeHtml(keyword)), "gi");
  box.innerHTML = esc.replace(re, (m) => `<mark>${m}</mark>`);
}

function searchSubtitle() {
  const q = $("subtitle-search").value.trim();
  const resultsBox = $("subtitle-results");
  if (!q) {
    resultsBox.classList.add("hidden");
    resultsBox.innerHTML = "";
    renderSubtitleHighlight("");
    return;
  }
  const matches = subtitleEntries.filter((e) => e.text.includes(q));
  if (!matches.length) {
    resultsBox.classList.remove("hidden");
    resultsBox.innerHTML = `<div class="muted">无匹配内容</div>`;
    renderSubtitleHighlight(q);
    return;
  }
  resultsBox.classList.remove("hidden");
  resultsBox.innerHTML = matches.slice(0, 50).map((m) =>
    `<div class="subtitle-result">
      <a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${m.start}">${formatTs(m.start)}</a>
      ${escapeHtml(m.text)}
    </div>`
  ).join("") + (matches.length > 50 ? `<div class="muted">…共 ${matches.length} 条匹配，仅显示前 50 条</div>` : "");
  renderSubtitleHighlight(q);
}

function switchTab(name) {
  document.querySelectorAll(".win-tab").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === name);
  });
  $("tab-axles").classList.toggle("hidden", name !== "axles");
  $("tab-subtitle").classList.toggle("hidden", name !== "subtitle");
  if (name === "subtitle") loadSubtitle();
}

async function confirmReaxle() {
  const tid = reaxleTaskId || currentTaskId;
  const payload = {
    target_min_seconds: Number($("reaxle-min").value) || 30,
    target_max_seconds: Number($("reaxle-max").value) || 3600,
    fine_mode: $("reaxle-fine").checked,
  };
  if (payload.target_min_seconds >= payload.target_max_seconds) {
    alert("目标最短必须小于目标最长");
    return;
  }
  try {
    await api(`/api/tasks/${tid}/reaxle`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    $("reaxle-modal").classList.add("hidden");
    if (tid === currentTaskId) {
      $("report-status").textContent = "重新打轴进行中…（复用 ASR 结果，不重复计费）";
      startPolling(tid);
    } else {
      await loadTasks();
      alert("已开始重新打轴，任务列表可查看进度");
    }
  } catch (err) {
    alert("重新打轴失败：" + err.message);
  }
}

/* ---------------- 批量多选（chips） ---------------- */

let selectedVideos = []; // [{path, name}]

function renderChips() {
  const box = $("video-chips");
  if (!selectedVideos.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = selectedVideos.map((v, i) =>
    `<span class="chip" title="${escapeAttr(v.path)}">${escapeHtml(v.name)}<button class="chip-del" data-i="${i}" title="移除">×</button></span>`
  ).join("");
  document.querySelectorAll(".chip-del").forEach((b) => {
    b.addEventListener("click", () => {
      selectedVideos.splice(Number(b.dataset.i), 1);
      renderChips();
    });
  });
}

function addVideoChips(paths) {
  for (const p of paths) {
    if (!selectedVideos.some((v) => v.path === p)) {
      selectedVideos.push({ path: p, name: p.split(/[\\/]/).pop() });
    }
  }
  renderChips();
  // 选择视频后检查同目录同名弹幕并显示（单视频时自动填入弹幕路径）
  if (selectedVideos.length === 1) {
    checkSiblingDanmaku(selectedVideos[0].path);
  } else {
    $("danmaku-hint").classList.add("hidden");
  }
}

async function checkSiblingDanmaku(videoPath) {
  const hint = $("danmaku-hint");
  try {
    const r = await api(`/api/files/sibling-danmaku?video_path=${encodeURIComponent(videoPath)}`);
    if (r.path) {
      $("danmaku_path").value = r.path;
      hint.textContent = `✅ 已自动关联同名弹幕文件：${r.path}`;
      hint.classList.remove("hidden");
    } else {
      if ($("danmaku_path").value) {
        hint.textContent = "未发现同名弹幕文件（可手动填写弹幕路径）";
        hint.classList.remove("hidden");
      }
    }
  } catch (e) {
    hint.classList.add("hidden");
  }
}

/* ---------------- 文件浏览器 ---------------- */

let fbPath = "";
let fbParent = "";
let fbTarget = null;
let fbFilter = "all";
let fbSelected = new Map(); // path -> name

function openFileBrowser(targetId, filter) {
  fbTarget = targetId;
  fbFilter = filter || "all";
  fbSelected.clear();
  updateFbFooter();
  const titles = { video: "选择视频文件（可勾选多个）", xml: "选择弹幕 XML 文件", all: "选择文件" };
  $("file-modal-title").textContent = titles[fbFilter] || "选择文件";
  $("file-modal").classList.remove("hidden");
  const cur = ($(targetId).value || "").trim();
  loadFileList(cur ? dirOf(cur) : "");
}

function dirOf(path) {
  const p = path.replace(/[\\/]+$/, "");
  const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
  return i > 0 ? p.slice(0, i) : p;
}

async function loadFileList(path) {
  const url = path
    ? `/api/files/ls?path=${encodeURIComponent(path)}&filter=${fbFilter}`
    : "/api/files/drives";
  try {
    const data = await api(url);
    fbPath = data.path || "";
    fbParent = data.parent || "";
    renderFileList(data);
  } catch (err) {
    if (path) {
      loadFileList("");
    } else {
      $("fb-list").innerHTML = `<div class="muted">加载失败：${escapeHtml(err.message)}</div>`;
    }
  }
}

function updateFbFooter() {
  const n = fbSelected.size;
  $("fb-selected-count").textContent = n
    ? `已选中 ${n} 个文件（颜色高亮，点击可取消）`
    : "点击文件 = 选中（视频可多选，再次点击取消）；点击文件夹进入";
  const btn = $("btn-fb-confirm");
  btn.classList.toggle("hidden", n === 0);
  btn.textContent = n ? `确认选择（${n} 个）` : "确认选择";
}

/* ---------------- 收藏路径 ---------------- */

function getFavorites() {
  try { return JSON.parse(localStorage.getItem("lca-favorite-dirs") || "[]"); } catch (e) { return []; }
}

function saveFavorites(list) {
  localStorage.setItem("lca-favorite-dirs", JSON.stringify(list));
}

function renderFavorites() {
  const favs = getFavorites();
  $("fb-favorites").classList.toggle("hidden", favs.length === 0);
  $("fb-fav-list").innerHTML = favs.map((d, i) =>
    `<div class="fb-fav-item"><span class="fb-fav-path" data-path="${escapeAttr(d)}" title="点击进入">⭐ ${escapeHtml(d)}</span><button class="fb-fav-del" data-i="${i}" title="移除收藏">×</button></div>`
  ).join("");
  document.querySelectorAll(".fb-fav-path").forEach((el) => {
    el.addEventListener("click", () => loadFileList(el.dataset.path));
  });
  document.querySelectorAll(".fb-fav-del").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const favs = getFavorites();
      favs.splice(Number(el.dataset.i), 1);
      saveFavorites(favs);
      renderFavorites();
      renderFavButton();
    });
  });
}

function renderFavButton() {
  const favs = getFavorites();
  const btn = $("btn-fb-fav");
  const on = favs.includes(fbPath);
  btn.textContent = on ? "★ 已收藏当前路径" : "☆ 收藏当前路径";
  btn.classList.toggle("fav-on", on);
}

function toggleFavorite() {
  if (!fbPath) return;
  let favs = getFavorites();
  if (favs.includes(fbPath)) {
    favs = favs.filter((d) => d !== fbPath);
  } else {
    favs.push(fbPath);
  }
  saveFavorites(favs);
  renderFavorites();
  renderFavButton();
}

/* ---------------- 视频时长渐进填充 ---------------- */

function formatDuration(sec) {
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.round(sec % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fillDurations() {
  const queue = [];
  document.querySelectorAll("#fb-list .fb-file").forEach((el) => {
    const durEl = el.querySelector(".fb-duration");
    if (durEl && !durEl.dataset.loaded) {
      queue.push({ el: durEl, path: el.dataset.path });
    }
  });
  if (!queue.length) return;
  let cursor = 0;
  const CONCURRENCY = 2;
  async function worker() {
    while (cursor < queue.length) {
      const item = queue[cursor++];
      try {
        const r = await api(`/api/files/media-info?path=${encodeURIComponent(item.path)}`);
        if (r.duration > 0) {
          item.el.textContent = `⏱ ${formatDuration(r.duration)}`;
          item.el.dataset.loaded = "1";
        }
      } catch (e) { /* 忽略个别探测失败 */ }
    }
  }
  for (let i = 0; i < Math.min(CONCURRENCY, queue.length); i++) worker();
}

function renderFileList(data) {
  $("fb-path").textContent = fbPath || "我的电脑";
  $("btn-fb-up").disabled = !fbPath;
  renderFavorites();
  renderFavButton();
  const parts = [];
  (data.dirs || []).forEach((d) => {
    parts.push(`<div class="fb-item fb-dir" data-path="${escapeAttr(d.path)}"><span class="fb-icon">📁</span><span class="fb-name">${escapeHtml(d.name)}</span></div>`);
  });
  (data.files || []).forEach((f) => {
    const selected = fbSelected.has(f.path) ? " selected" : "";
    const isVideo = /\.(mp4|flv|mkv|mov|avi|ts|m4v|wmv|webm|m2ts)$/i.test(f.name);
    parts.push(`<div class="fb-item fb-file${selected}" data-path="${escapeAttr(f.path)}"><span class="fb-icon">${isVideo ? "🎬" : "📄"}</span><span class="fb-name">${escapeHtml(f.name)}</span>${isVideo ? `<span class="fb-duration" data-loaded=""></span>` : ""}<span class="fb-size">${formatSize(f.size)}</span></div>`);
  });
  if (!parts.length) {
    $("fb-list").innerHTML = `<div class="muted">（空目录，或没有匹配类型的文件）</div>`;
    return;
  }
  $("fb-list").innerHTML = parts.join("");
  document.querySelectorAll(".fb-item").forEach((el) => {
    el.addEventListener("click", () => {
      const p = el.dataset.path;
      if (el.classList.contains("fb-dir")) {
        loadFileList(p);
        return;
      }
      // 点击切换选中：视频模式可多选，其余模式单选
      const nameEl = el.querySelector(".fb-name");
      if (fbSelected.has(p)) {
        fbSelected.delete(p);
        el.classList.remove("selected");
      } else {
        if (fbFilter !== "video") fbSelected.clear();
        fbSelected.set(p, nameEl ? nameEl.textContent : p);
        el.classList.add("selected");
      }
      updateFbFooter();
    });
  });
  setTimeout(fillDurations, 60);
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function fileListUp() {
  if (!fbPath) return;
  loadFileList(fbParent || "");
}

/* ---------------- 设置 / 配置页 ---------------- */

async function loadConfig() {
  const cfg = await api("/api/config");
  $("cfg-base-url").value = cfg.base_url || "";
  $("cfg-api-key").value = cfg.api_key || "";
  $("cfg-vision-model").value = cfg.vision_model || "";
  $("cfg-llm-model").value = cfg.llm_model || "";
  $("cfg-asr-model").value = cfg.asr_model || "";
  $("cfg-llm-base-url").value = cfg.llm_base_url || "";
  $("cfg-llm-api-key").value = cfg.llm_api_key || "";
  $("cfg-vision-base-url").value = cfg.vision_base_url || "";
  $("cfg-vision-api-key").value = cfg.vision_api_key || "";
  $("cfg-asr-base-url").value = cfg.asr_base_url || "";
  $("cfg-asr-api-key").value = cfg.asr_api_key || "";
  $("cfg-asr-engine").value = cfg.asr_engine || "local";
  $("cfg-local-model-path").value = cfg.local_model_path || "";
  $("cfg-subtitle-max-chars").value = cfg.subtitle_max_chars ?? 30;
  $("cfg-target-min").value = cfg.target_min_seconds ?? 30;
  $("cfg-target-max").value = cfg.target_max_seconds ?? 3600;
  $("cfg-export-accurate").checked = !!cfg.export_accurate;
  const hint = $("cfg-key-hint");
  if (cfg.has_api_key) {
    hint.textContent = "✅ 已配置（显示为掩码，保留掩码则不变更）";
    hint.classList.remove("warn");
  } else {
    hint.textContent = "⚠️ 尚未配置 API Key，请在下方填入真实密钥后保存";
    hint.classList.add("warn");
  }
}

async function saveConfig() {
  const payload = {
    base_url: $("cfg-base-url").value.trim(),
    api_key: $("cfg-api-key").value.trim(),
    vision_model: $("cfg-vision-model").value.trim(),
    llm_model: $("cfg-llm-model").value.trim(),
    asr_model: $("cfg-asr-model").value.trim(),
    llm_base_url: $("cfg-llm-base-url").value.trim(),
    llm_api_key: $("cfg-llm-api-key").value.trim(),
    vision_base_url: $("cfg-vision-base-url").value.trim(),
    vision_api_key: $("cfg-vision-api-key").value.trim(),
    asr_base_url: $("cfg-asr-base-url").value.trim(),
    asr_api_key: $("cfg-asr-api-key").value.trim(),
    asr_engine: $("cfg-asr-engine").value,
    local_model_path: $("cfg-local-model-path").value.trim(),
    subtitle_max_chars: Number($("cfg-subtitle-max-chars").value) || 30,
    target_min_seconds: Number($("cfg-target-min").value) || 30,
    target_max_seconds: Number($("cfg-target-max").value) || 3600,
    export_accurate: $("cfg-export-accurate").checked,
  };
  if (!payload.base_url) {
    alert("接口地址 base_url 不能为空");
    return;
  }
  if (payload.target_min_seconds >= payload.target_max_seconds) {
    alert("目标最短时长必须小于目标最长时长");
    return;
  }
  try {
    await api("/api/config", { method: "PUT", body: JSON.stringify(payload) });
    $("config-modal").classList.add("hidden");
    alert("配置已保存，下一个新建任务生效");
  } catch (err) {
    alert("保存失败：" + err.message);
  }
}

/* ---------------- 模型下拉（按功能筛选） ---------------- */

const MODEL_PATTERNS = {
  asr: /asr|whisper|sensevoice|paraformer|funasr|speech2text|audio2text|transcri/i,
  vision: /vl|vision|visual|llava|internvl|minicpm-v|glm-4v|glm-4\.5v|deepseek-vl|vlm|ocr/i,
};
const MODEL_LABELS = { llm: "文本模型", vision: "视觉模型", asr: "ASR 模型" };

function classifyModel(name) {
  const n = name.toLowerCase();
  if (MODEL_PATTERNS.asr.test(n)) return "asr";
  if (MODEL_PATTERNS.vision.test(n)) return "vision";
  return "llm";
}

function fillModelLists(models) {
  const buckets = { llm: [], vision: [], asr: [] };
  (models || []).forEach((m) => buckets[classifyModel(m)].push(m));
  window.modelCatalog = buckets;
  ["llm", "vision", "asr"].forEach((kind) => renderModelSelect(kind));
}

function renderModelSelect(kind) {
  const items = (window.modelCatalog && window.modelCatalog[kind]) || [];
  const info = $(`ms-${kind}-info`);
  const list = $(`ms-${kind}-list`);
  if (!items.length) {
    info.textContent = "未筛选出该类模型（点「测试连接」获取列表）";
    info.classList.remove("ok");
    list.innerHTML = "";
    return;
  }
  info.textContent = `✅ 已筛选出 ${items.length} 个${MODEL_LABELS[kind]}（共 ${totalCatalogCount()} 个模型）`;
  info.classList.add("ok");
  list.innerHTML = items.map((m) =>
    `<div class="ms-option" data-kind="${kind}" data-model="${escapeAttr(m)}">${escapeHtml(m)}</div>`
  ).join("");
}

function totalCatalogCount() {
  const c = window.modelCatalog;
  return c ? c.llm.length + c.vision.length + c.asr.length : 0;
}

function toggleModelPanel(kind, forceOpen) {
  const panel = document.querySelector(`.ms-panel[data-kind="${kind}"]`);
  if (!panel) return;
  const shouldOpen = forceOpen === undefined ? panel.classList.contains("hidden") : forceOpen;
  document.querySelectorAll(".ms-panel").forEach((p) => p.classList.add("hidden"));
  if (shouldOpen) {
    panel.classList.remove("hidden");
    // 面板可能超出滚动容器可视区：滚动到最近可见位置
    setTimeout(() => panel.scrollIntoView({ block: "nearest" }), 0);
  }
}

function initModelSelects() {
  document.querySelectorAll(".ms-toggle").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleModelPanel(btn.dataset.kind);
    });
  });
  document.querySelectorAll(".ms-input").forEach((input) => {
    input.addEventListener("click", (e) => e.stopPropagation()); // 点击输入框不触发 document 级关闭
    input.addEventListener("focus", () => toggleModelPanel(input.id.replace("cfg-", "").replace("-model", ""), true));
  });
  document.addEventListener("click", () => {
    document.querySelectorAll(".ms-panel").forEach((p) => p.classList.add("hidden"));
  });
  document.querySelectorAll(".ms-panel").forEach((panel) => {
    panel.addEventListener("click", (e) => {
      e.stopPropagation();
      const opt = e.target.closest(".ms-option");
      if (opt) {
        $(`cfg-${opt.dataset.kind}-model`).value = opt.dataset.model;
        panel.classList.add("hidden");
      }
    });
  });
}

async function testConnection(kind) {
  const isGlobal = kind === "global";
  const btn = document.querySelector(`.btn-test[data-kind="${kind}"]`);
  const statusBox = $(`ping-status-${kind}`);
  const baseUrl = isGlobal
    ? $("cfg-base-url").value.trim()
    : ($(`cfg-${kind}-base-url`).value.trim() || $("cfg-base-url").value.trim());
  const key = isGlobal
    ? $("cfg-api-key").value.trim()
    : ($(`cfg-${kind}-api-key`).value.trim() || $("cfg-api-key").value.trim());
  if (!baseUrl) {
    alert("请先填写接口地址（本组或全局均可）");
    return;
  }
  btn.disabled = true;
  btn.textContent = "测试中…";
  statusBox.textContent = "";
  statusBox.className = "cfg-ping-status";
  try {
    const result = await api("/api/config/test-connection", {
      method: "POST",
      body: JSON.stringify({ kind, base_url: baseUrl, api_key: key }),
    });
    if (result.ok) {
      if (isGlobal) {
        // 全局接口连通：按功能筛选后填充三个模型下拉
        statusBox.textContent = `✅ 已连通（${result.url}）——发现 ${result.count} 个模型，已按功能筛选到下方三个模型下拉（点击 ▾ 选择）`;
        statusBox.classList.add("ok");
        fillModelLists(result.models || []);
      } else {
        statusBox.textContent = `✅ 已连通（${result.url}）——发现 ${result.count} 个模型，点击 ▾ 下拉选择`;
        statusBox.classList.add("ok");
        // 单端点 ping：把模型按功能分类，仅填充对应分类
        if (!window.modelCatalog) window.modelCatalog = { llm: [], vision: [], asr: [] };
        const buckets = { llm: [], vision: [], asr: [] };
        (result.models || []).forEach((m) => buckets[classifyModel(m)].push(m));
        window.modelCatalog[kind] = buckets[kind];
        renderModelSelect(kind);
        const modelInput = $(`cfg-${kind}-model`);
        if (buckets[kind].length && !modelInput.value) {
          modelInput.value = buckets[kind][0];
        }
      }
    } else {
      let msg = "❌ " + (result.detail || "无法连接，请检查地址与密钥");
      if (String(result.detail || "").includes("401") && !isGlobal) {
        msg += "｜密钥可能无效——可清空本组的 API Key 后保存，将回退使用全局密钥";
      }
      statusBox.textContent = msg;
      statusBox.classList.add("fail");
    }
  } catch (err) {
    statusBox.textContent = "❌ " + err.message;
    statusBox.classList.add("fail");
  } finally {
    btn.disabled = false;
    btn.textContent = "测试连接";
  }
}

function openConfig() {
  $("config-modal").classList.remove("hidden");
  loadConfig().catch((e) => alert("加载配置失败：" + e.message));
}

/* ---------------- 初始化 ---------------- */

async function init() {
  initTheme();
  $("btn-settings").addEventListener("click", openConfig);
  $("btn-back-home").addEventListener("click", closeReport);
  document.querySelectorAll(".btn-browse").forEach((btn) => {
    btn.addEventListener("click", () => openFileBrowser(btn.dataset.target, btn.dataset.filter));
  });
  document.querySelectorAll(".btn-test").forEach((btn) => {
    btn.addEventListener("click", () => testConnection(btn.dataset.kind));
  });
  initModelSelects();
  $("btn-fb-up").addEventListener("click", fileListUp);
  $("btn-fb-fav").addEventListener("click", toggleFavorite);
  $("btn-fb-cancel").addEventListener("click", () => $("file-modal").classList.add("hidden"));
  $("file-modal").addEventListener("click", (e) => {
    if (e.target === $("file-modal")) $("file-modal").classList.add("hidden");
  });
  $("btn-cancel-config").addEventListener("click", () => $("config-modal").classList.add("hidden"));
  $("btn-save-config").addEventListener("click", saveConfig);
  $("config-modal").addEventListener("click", (e) => {
    if (e.target === $("config-modal")) $("config-modal").classList.add("hidden");
  });

  $("btn-start").addEventListener("click", async () => {
    const danmaku = $("danmaku_path").value.trim() || null;
    const offset = Number($("offset_seconds").value) || 0;
    const btn = $("btn-start");
    const oldText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "创建中…";
    try {
      // 视频来源：手动输入 + 已选 chips 合并（去重），单选走单任务接口以便自动关联弹幕提示
      const manual = $("video_path").value.trim();
      const paths = selectedVideos.map((v) => v.path);
      if (manual && !paths.includes(manual)) paths.unshift(manual);
      if (!paths.length) {
        alert("请先填写视频路径，或通过 📂 浏览选择");
        return;
      }
      if (paths.length === 1) {
        const task = await api("/api/tasks", {
          method: "POST",
          body: JSON.stringify({
            video_path: paths[0],
            danmaku_path: danmaku,
            offset_seconds: offset,
          }),
        });
        selectedVideos = [];
        renderChips();
        $("video_path").value = "";
        $("danmaku_path").value = "";
        $("offset_seconds").value = "0";
        await loadTasks();
        await openReport(task.id);
        if (task._auto_danmaku) {
          alert(`已在视频同目录发现同名弹幕文件，已自动关联：\n${task.danmaku_path}`);
        }
        return;
      }
      // 批量：一次创建 N 个任务并行分析
      const tasks = await api("/api/tasks/batch", {
        method: "POST",
        body: JSON.stringify({
          video_paths: paths,
          danmaku_path: danmaku,
          offset_seconds: offset,
        }),
      });
      selectedVideos = [];
      renderChips();
      $("video_path").value = "";
      $("danmaku_path").value = "";
      $("offset_seconds").value = "0";
      await loadTasks();
      await openReport(tasks[0].id);
      const danmakuNote = danmaku ? "\n（注意：批量任务统一关联了同一个弹幕文件）" : "";
      alert(`已创建 ${tasks.length} 个任务，正在并行分析（任务列表可查看进度）${danmakuNote}`);
    } catch (err) {
      alert("创建失败：" + err.message);
    } finally {
      btn.disabled = false;
      btn.textContent = oldText;
    }
  });

  $("score-filter").addEventListener("input", () => renderAxles(currentAxles));
  $("btn-refresh").addEventListener("click", () => refreshReportData().catch((e) => alert(e.message)));
  $("btn-export-all").addEventListener("click", async () => {
    if (!confirm("确定批量导出当前全部切片轴？")) return;
    await exportAxleIds(null, $("btn-export-all"));
  });
  $("btn-cancel-review").addEventListener("click", () => $("edit-modal").classList.add("hidden"));
  $("btn-confirm-reaxle").addEventListener("click", confirmReaxle);
  $("btn-cancel-reaxle").addEventListener("click", () => $("reaxle-modal").classList.add("hidden"));
  $("reaxle-modal").addEventListener("click", (e) => {
    if (e.target === $("reaxle-modal")) $("reaxle-modal").classList.add("hidden");
  });
  $("btn-score-help").addEventListener("click", () => {
    $("score-help").classList.toggle("hidden");
  });
  $("btn-copy-all").addEventListener("click", () => {
    if (!currentAxles.length) {
      alert("当前没有轴可复制");
      return;
    }
    copyToClipboard(buildAxlesTsv(), `全部 ${currentAxles.length} 个轴清单（制表符分隔）`);
  });
  $("subtitle-search").addEventListener("input", searchSubtitle);
  document.querySelectorAll(".win-tab").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
  $("btn-fb-confirm").addEventListener("click", () => {
    const paths = [...fbSelected.keys()];
    fbSelected.clear();
    updateFbFooter();
    $("file-modal").classList.add("hidden");
    if (fbTarget === "video_path") {
      addVideoChips(paths);
    } else {
      $(fbTarget).value = paths[0] || "";
    }
  });
  $("btn-save-review").addEventListener("click", async () => {
    const id = $("edit-id").value;
    const start = Number($("edit-start").value);
    const end = Number($("edit-end").value);
    if (!(start >= 0) || end <= 0 || start >= end) {
      alert("时间无效：开始时间必须小于结束时间，且结束时间大于 0");
      return;
    }
    const payload = { start, end, title: $("edit-title").value };
    const btn = $("btn-save-review");
    btn.disabled = true;
    try {
      await api(`/api/tasks/${currentTaskId}/axles/${id}/review`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      $("edit-modal").classList.add("hidden");
      await refreshReportData();
    } catch (err) {
      alert("保存失败：" + err.message);
    } finally {
      btn.disabled = false;
    }
  });

  await loadTasks();
  setInterval(() => {
    if (!document.hidden) loadTasks(); // 页面切后台时暂停轮询
  }, 5000);

  // 多行路径粘贴：一次性粘贴多个视频路径自动解析成多选 chips
  $("video_path").addEventListener("paste", (e) => {
    const text = (e.clipboardData || window.clipboardData).getData("text") || "";
    const lines = text.split(/\r?\n/).map((s) => s.trim().replace(/^["']+|["']+$/g, "")).filter(Boolean);
    if (lines.length > 1) {
      e.preventDefault();
      addVideoChips(lines);
      $("video_path").value = "";
      toast(`已解析 ${lines.length} 个路径，加入待处理列表`);
    }
  });

  // 字幕路径复制
  $("btn-copy-srt-path").addEventListener("click", async () => {
    const p = ($("subtitle-path").textContent || "").trim();
    if (!p) { toast("暂无字幕路径"); return; }
    try {
      await navigator.clipboard.writeText(p);
      toast("✅ 已复制字幕文件路径");
    } catch (err) {
      toast("复制失败：" + err.message);
    }
  });

  // 报告窗口：滚动后显示「回到顶部」
  const winMain = $("win-main");
  const scrollTopBtn = $("btn-scroll-top");
  winMain.addEventListener("scroll", () => {
    scrollTopBtn.classList.toggle("hidden", winMain.scrollTop < 300);
  });
  scrollTopBtn.addEventListener("click", () => {
    winMain.scrollTo({ top: 0, behavior: "smooth" });
  });
}

async function loadTasks() {
  try {
    const tasks = await api("/api/tasks");
    renderTasks(tasks);
  } catch (err) {
    console.error(err);
  }
}

document.addEventListener("DOMContentLoaded", init);
