"use strict";

let currentTaskId = null;
let currentScenes = [];
let currentCandidates = [];
let timer = null;

const $ = (id) => document.getElementById(id);

function formatTs(seconds) {
  seconds = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = String(Math.floor(seconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, "0");
  const s = String(seconds % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
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
}

function taskStatusBadge(task) {
  const cls = task.status || "pending";
  const text = { pending: "等待中", running: "运行中", done: "完成", failed: "失败" }[cls] || cls;
  return `<span class="status ${cls}">${text}</span>`;
}

function renderTasks(tasks) {
  const box = $("task-list");
  if (!tasks.length) {
    box.innerHTML = `<div class="muted">暂无任务，请先创建。</div>`;
    return;
  }
  box.innerHTML = tasks.map((t) => {
    const progress = t.progress || 0;
    return `
      <div class="task-item">
        <div class="info">
          <div class="name">${escapeHtml(t.video_path || "")}</div>
          <div class="meta">${t.id} · ${t.created_at} · ${escapeHtml(t.message || "")}</div>
        </div>
        <div class="progress"><div style="width:${progress}%"></div></div>
        ${taskStatusBadge(t)}
        <button data-id="${t.id}" class="btn-view">查看</button>
          <button data-id="${t.id}" class="btn-delete ghost">删除</button>
      </div>`;
  }).join("");
  document.querySelectorAll(".btn-view").forEach((btn) => {
    btn.addEventListener("click", () => openReport(btn.dataset.id));
  });
    document.querySelectorAll(".btn-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!confirm("确定删除该任务及其所有分析产物？")) return;
        try {
          await api(`/api/tasks/${btn.dataset.id}`, { method: "DELETE" });
          await loadTasks();
        } catch (err) {
          alert("删除失败：" + err.message);
        }
      });
    });
}

function renderReport(task) {
  $("report-title").textContent = `分析报告（${task.id}）`;
  $("report-status").textContent = `状态：${task.status}（${task.progress || 0}%） · ${task.message || ""}`;
  $("link-video").href = `/api/tasks/${task.id}/video`;
  $("link-report-zh").href = `/api/tasks/${task.id}/report?lang=zh&download=1`;
  $("link-report-en").href = `/api/tasks/${task.id}/report?lang=en&download=1`;
  $("link-export-json").href = `/api/tasks/${task.id}/export.json`;
  $("report-card").classList.remove("hidden");
}

function rankName(rank) {
  return { high: "高", medium: "中", low: "低" }[rank] || rank || "低";
}

function renderScenes(scenes) {
  const rankFilter = $("rank-filter").value;
  const scoreFilter = Number($("score-filter").value) || 0;
  const box = $("scenes-container");
  const filtered = scenes.filter((s) => {
    if (rankFilter && s.rank !== rankFilter) return false;
    if (Number(s.final_score || 0) < scoreFilter) return false;
    return true;
  });
  if (!filtered.length) {
    box.innerHTML = `<div class="muted">没有符合条件的片段。</div>`;
    return;
  }
  box.innerHTML = filtered.map((s) => {
    const keywords = (s.danmaku_keywords || []).join("、") || "（无）";
    return `
      <div class="scene-item rank-${s.rank || "low"}">
        <div class="head">
          <span class="title"><a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${s.start}">[${formatTs(s.start)} - ${formatTs(s.end)}]</a> ${escapeHtml(s.title_zh || "")}</span>
          <span class="badge ${s.rank || "low"}">${rankName(s.rank)} · ${s.final_score ?? 0} 分</span>
        </div>
        <div class="detail"><b>内容：</b>${escapeHtml(s.summary_zh || "（无）")}</div>
        <div class="detail"><b>画面：</b>${escapeHtml(s.visual_summary || "（无）")}</div>
        <div class="detail"><b>语音：</b>${escapeHtml(s.asr_text || "（无）")}</div>
        <div class="detail"><b>弹幕：</b>数量 ${s.danmaku_count || 0} / 热度 ${s.danmaku_heat ?? 0} / 情绪 ${s.danmaku_emotion ?? 0} / 高频：${escapeHtml(keywords)}</div>
        ${s.quote ? `<div class="detail"><b>Quote：</b>[${formatTs(s.quote_start ?? s.start)}] ${escapeHtml(s.quote)}</div>` : ""}
      </div>`;
  }).join("");
}

function renderCandidates(candidates) {
  const longBox = $("long-candidates");
  const sentenceBox = $("sentence-candidates");
  const long = candidates.filter((c) => c.type === "long");
  const sentence = candidates.filter((c) => c.type === "sentence");

  longBox.innerHTML = long.length ? long.map((c) => candidateCard(c)).join("") : `<div class="muted">暂无长切片候选。</div>`;
  sentenceBox.innerHTML = sentence.length ? sentence.map((c) => candidateCard(c)).join("") : `<div class="muted">暂无单句素材候选。</div>`;

  document.querySelectorAll(".btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => openEdit(btn.dataset.id));
  });
}

function candidateCard(c) {
  const start = c.review_start ?? c.start;
  const end = c.review_end ?? c.end;
  const score = c.review_score ?? c.score;
  const rank = c.review_rank || (score >= 7.5 ? "high" : score >= 5 ? "medium" : "low");
  const title = c.review_title || c.title_zh || "";
  const timeText = c.type === "sentence" ? `[${formatTs(start)}]` : `[${formatTs(start)} - ${formatTs(end)}]`;
  return `
    <div class="candidate">
      <div class="head">
        <span class="title"><a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${start}">${timeText}</a> ${escapeHtml(title)}</span>
        <span class="badge ${rank}">${rankName(rank)} · ${score ?? 0} 分</span>
      </div>
      <div class="meta"><b>理由：</b>${escapeHtml(c.reason_zh || "（无）")}</div>
      ${(c.keywords || []).length ? `<div class="meta"><b>关键词：</b>${escapeHtml(c.keywords.join("、"))}</div>` : ""}
      <div class="actions"><button class="btn-edit" data-id="${c.id}">复核编辑</button></div>
    </div>`;
}

function openEdit(candidateId) {
  const c = currentCandidates.find((x) => String(x.id) === String(candidateId));
  if (!c) return;
  $("edit-id").value = c.id;
  $("edit-type").value = c.type;
  $("edit-start").value = c.review_start ?? c.start ?? 0;
  $("edit-end").value = c.review_end ?? c.end ?? 0;
  $("edit-title").value = c.review_title || c.title_zh || "";
  $("edit-score").value = c.review_score ?? c.score ?? 0;
  $("edit-rank").value = c.review_rank || "medium";
  $("edit-modal").classList.remove("hidden");
}

async function openReport(taskId) {
  currentTaskId = taskId;
  const task = await api(`/api/tasks/${taskId}`);
  renderReport(task);
  await refreshReportData();
  startPolling(taskId);
}

async function refreshReportData() {
  if (!currentTaskId) return;
  currentScenes = await api(`/api/tasks/${currentTaskId}/scenes`);
  currentCandidates = await api(`/api/tasks/${currentTaskId}/candidates`);
  renderScenes(currentScenes);
  renderCandidates(currentCandidates);
}

function startPolling(taskId) {
  if (timer) clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const task = await api(`/api/tasks/${taskId}`);
      $("report-status").textContent = `状态：${task.status}（${task.progress || 0}%） · ${task.message || ""}`;
      if (task.status === "done" || task.status === "failed") {
        clearInterval(timer);
        timer = null;
        await refreshReportData();
      }
    } catch (e) {
      clearInterval(timer);
      timer = null;
    }
  }, 3000);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

async function init() {
  $("create-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      video_path: $("video_path").value.trim(),
      danmaku_path: $("danmaku_path").value.trim() || null,
      offset_seconds: Number($("offset_seconds").value) || 0,
      output_languages: $("output_languages").value.split(",").map((x) => x.trim()).filter(Boolean),
    };
    try {
      const task = await api("/api/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      $("create-form").reset();
      $("offset_seconds").value = "0";
      $("output_languages").value = "zh,en";
      await loadTasks();
        await openReport(task.id);
    } catch (err) {
      alert("创建失败：" + err.message);
    }
  });

  $("rank-filter").addEventListener("change", () => renderScenes(currentScenes));
  $("score-filter").addEventListener("input", () => renderScenes(currentScenes));
  $("btn-refresh").addEventListener("click", () => refreshReportData().catch((e) => alert(e.message)));
  $("btn-cancel-review").addEventListener("click", () => $("edit-modal").classList.add("hidden"));
  $("btn-save-review").addEventListener("click", async () => {
    const id = $("edit-id").value;
    const payload = {
      start: Number($("edit-start").value),
      end: Number($("edit-end").value),
      title: $("edit-title").value,
      score: Number($("edit-score").value),
      rank: $("edit-rank").value,
    };
    try {
      await api(`/api/tasks/${currentTaskId}/candidates/${id}/review`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      $("edit-modal").classList.add("hidden");
      await refreshReportData();
    } catch (err) {
      alert("保存失败：" + err.message);
    }
  });

  await loadTasks();
  setInterval(loadTasks, 5000);
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
