"use strict";

let currentTaskId = null;
let currentScenes = [];
let currentCandidates = [];
let currentTopics = [];
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
      const active = t.id === currentTaskId ? " active" : "";
    return `
      <div class="task-item${active}">
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
            if (currentTaskId === btn.dataset.id) {
              currentTaskId = null;
              $("report-card").classList.add("hidden");
              $("empty-state").classList.remove("hidden");
            }
        } catch (err) {
          if (String(err.message).includes("正在运行") && confirm("任务正在运行，是否强制删除？")) {
            try {
              await api(`/api/tasks/${btn.dataset.id}?force=true`, { method: "DELETE" });
              await loadTasks();
              if (currentTaskId === btn.dataset.id) {
                currentTaskId = null;
                $("report-card").classList.add("hidden");
                $("empty-state").classList.remove("hidden");
              }
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

function renderReport(task) {
  $("report-title").textContent = `分析报告（${task.id}）`;
  $("report-status").textContent = `状态：${task.status}（${task.progress || 0}%） · ${task.message || ""}`;
  $("link-video").href = `/api/tasks/${task.id}/video`;
  $("link-report-zh").href = `/api/tasks/${task.id}/report?lang=zh&download=1`;
  $("link-report-en").href = `/api/tasks/${task.id}/report?lang=en&download=1`;
  $("link-export-json").href = `/api/tasks/${task.id}/export.json`;
  $("report-card").classList.remove("hidden");
    $("empty-state").classList.add("hidden");
    document.body.classList.remove("sidebar-open");
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

function renderTopics(topics) {
  const box = $("topics-container");
  if (!topics || !topics.length) {
    box.innerHTML = `<div class="muted">暂无话题段（无音轨或未完成字幕切分）。</div>`;
    return;
  }
  box.innerHTML = topics.map((tp) => {
    const keywords = (tp.keywords || []).join("、") || "（无）";
    return `
      <div class="topic-item">
        <div class="head">
          <span class="title"><a class="time-link" target="_blank" href="/static/preview.html?task=${currentTaskId}&t=${tp.start}">[${formatTs(tp.start)} - ${formatTs(tp.end)}]</a> ${escapeHtml(tp.title_zh || "")}</span>
        </div>
        <div class="detail">${escapeHtml(tp.summary_zh || "（无）")}</div>
        <div class="detail"><b>关键词：</b>${escapeHtml(keywords)}</div>
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
    document.querySelectorAll(".btn-export-one").forEach((btn) => {
      btn.addEventListener("click", () => exportCandidateIds([Number(btn.dataset.id)], btn));
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
      <div class="actions"><button class="btn-edit" data-id="${c.id}">复核编辑</button>
          <button class="btn-export-one" data-id="${c.id}">导出此切片</button></div>
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
    await loadTasks();
    $("export-results").innerHTML = `<div class="muted">暂无导出结果。</div>`;
    await loadExportResults();
  await refreshReportData();
  startPolling(taskId);
}

async function refreshReportData() {
  if (!currentTaskId) return;
  currentScenes = await api(`/api/tasks/${currentTaskId}/scenes`);
  currentCandidates = await api(`/api/tasks/${currentTaskId}/candidates`);
  currentTopics = await api(`/api/tasks/${currentTaskId}/topics`);
  renderScenes(currentScenes);
  renderCandidates(currentCandidates);
  renderTopics(currentTopics);
}

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

async function exportCandidateIds(candidateIds, btn) {
  if (!currentTaskId) return;
  const oldText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "导出中…";
  }
  try {
    const payload = candidateIds ? { candidate_ids: candidateIds } : {};
    if ($("export-accurate").checked) payload.accurate = true;
    const result = await api(`/api/tasks/${currentTaskId}/export`, {
      method: "POST",
      body: JSON.stringify(payload),
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

function escapeAttr(text) {
  return escapeHtml(text).replace(/"/g, "&quot;");
}

/* ---------------- 文件浏览器 ---------------- */
let fbPath = "";
let fbParent = "";
let fbTarget = null;
let fbFilter = "all";

function openFileBrowser(targetId, filter) {
  fbTarget = targetId;
  fbFilter = filter || "all";
  const titles = { video: "选择视频文件", xml: "选择弹幕 XML 文件", all: "选择文件" };
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
      // 当前路径无效（输入框里可能是文件路径或不存在），回退到磁盘根
      loadFileList("");
    } else {
      $("fb-list").innerHTML = `<div class="muted">加载失败：${escapeHtml(err.message)}</div>`;
    }
  }
}

function renderFileList(data) {
  $("fb-path").textContent = fbPath || "我的电脑";
  $("btn-fb-up").disabled = !fbPath; // 只要进入了某个目录（有 path）即可回退
  const parts = [];
  (data.dirs || []).forEach((d) => {
    parts.push(`<div class="fb-item fb-dir" data-path="${escapeAttr(d.path)}"><span class="fb-icon">📁</span><span class="fb-name">${escapeHtml(d.name)}</span></div>`);
  });
  (data.files || []).forEach((f) => {
    parts.push(`<div class="fb-item fb-file" data-path="${escapeAttr(f.path)}"><span class="fb-icon">📄</span><span class="fb-name">${escapeHtml(f.name)}</span><span class="fb-size">${formatSize(f.size)}</span></div>`);
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
      } else {
        $(fbTarget).value = p;
        $("file-modal").classList.add("hidden");
      }
    });
  });
}

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + " MB";
  return (bytes / 1073741824).toFixed(2) + " GB";
}

function fileListUp() {
  if (!fbPath) return;             // 已在盘符列表，无法再回退
  loadFileList(fbParent || "");    // 盘符根时 fbParent 为空，回到盘符列表
}

/* ---------------- 设置 / 配置页 ---------------- */
async function loadConfig() {
  const cfg = await api("/api/config");
  $("cfg-base-url").value = cfg.base_url || "";
  $("cfg-api-key").value = cfg.api_key || "";
  $("cfg-vision-model").value = cfg.vision_model || "";
  $("cfg-llm-model").value = cfg.llm_model || "";
  $("cfg-asr-model").value = cfg.asr_model || "";
  $("cfg-scene-min").value = cfg.scene_min_seconds ?? 8;
  $("cfg-scene-max").value = cfg.scene_max_seconds ?? 30;
  $("cfg-languages").value = (cfg.report_languages || ["zh", "en"]).join(",");
  $("cfg-asr-lang").value = cfg.asr_language || "";
  $("cfg-export-accurate").checked = !!cfg.export_accurate;
  $("cfg-key-hint").textContent = cfg.has_api_key
    ? "已配置（显示为掩码，保留掩码则不变更）"
    : "尚未配置 API Key，请填入你的密钥";
}

function openConfig() {
  $("config-modal").classList.remove("hidden");
  loadConfig().catch((e) => alert("加载配置失败：" + e.message));
}

async function saveConfig() {
  const payload = {
    base_url: $("cfg-base-url").value.trim(),
    api_key: $("cfg-api-key").value.trim(),
    vision_model: $("cfg-vision-model").value.trim(),
    llm_model: $("cfg-llm-model").value.trim(),
    asr_model: $("cfg-asr-model").value.trim(),
    scene_min_seconds: Number($("cfg-scene-min").value) || 8,
    scene_max_seconds: Number($("cfg-scene-max").value) || 30,
    export_accurate: $("cfg-export-accurate").checked,
    report_languages: $("cfg-languages").value.split(",").map((s) => s.trim()).filter(Boolean),
    asr_language: $("cfg-asr-lang").value.trim(),
  };
  if (!payload.base_url) {
    alert("接口地址 base_url 不能为空");
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

async function init() {
    $("sidebar-toggle").addEventListener("click", () => {
      document.body.classList.toggle("sidebar-open");
    });
  document.querySelectorAll(".btn-browse").forEach((btn) => {
    btn.addEventListener("click", () => openFileBrowser(btn.dataset.target, btn.dataset.filter));
  });
  $("btn-fb-up").addEventListener("click", fileListUp);
  $("btn-fb-cancel").addEventListener("click", () => $("file-modal").classList.add("hidden"));
  $("file-modal").addEventListener("click", (e) => {
    if (e.target === $("file-modal")) $("file-modal").classList.add("hidden");
  });
  $("btn-settings").addEventListener("click", openConfig);
  $("btn-cancel-config").addEventListener("click", () => $("config-modal").classList.add("hidden"));
  $("btn-save-config").addEventListener("click", saveConfig);
  $("config-modal").addEventListener("click", (e) => {
    if (e.target === $("config-modal")) $("config-modal").classList.add("hidden");
  });
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
    $("btn-export-all").addEventListener("click", async () => {
      if (!confirm("确定批量导出当前全部候选切片？")) return;
      await exportCandidateIds(null, $("btn-export-all"));
    });
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
