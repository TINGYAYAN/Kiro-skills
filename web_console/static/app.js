const state = {
  projects: [],
  currentProject: "",
  objectCache: new Map(),
  objectDropdownIndex: -1,
  taskWatchers: new Map(),
  projectDomains: new Map(),
  historyFilters: {},
  historyPage: 1,
  historyPageSize: 10,
};

const STORAGE_KEYS = {
  selectedProject: "apl_console_selected_project",
};

function $(id) {
  return document.getElementById(id);
}

async function jsonFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || `HTTP ${resp.status}`);
  }
  const ctype = resp.headers.get("content-type") || "";
  if (ctype.includes("application/json")) return resp.json();
  return resp.text();
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderList(container, items, formatter) {
  container.innerHTML = "";
  if (!items || !items.length) {
    container.textContent = "暂无数据";
    return;
  }
  items.forEach((item) => {
    const div = document.createElement("div");
    div.className = "task-item";
    div.innerHTML = formatter(item);
    container.appendChild(div);
  });
}

function debounce(fn, wait = 180) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function fillProjectSelect(select, projects, currentProject, placeholder = "请选择项目") {
  if (!select) return;
  const currentValue = select.value;
  const items = [`<option value="">${placeholder}</option>`];
  projects.forEach((project) => {
    const selectedProject = currentValue || currentProject;
    const selected = project.name === selectedProject ? "selected" : "";
    items.push(`<option value="${escapeHtml(project.name)}" ${selected}>${escapeHtml(project.name)}</option>`);
  });
  select.innerHTML = items.join("");
}

async function loadProjectObjects(project) {
  const projectName = (project || "").trim();
  if (!projectName) return [];
  if (state.objectCache.has(projectName)) return state.objectCache.get(projectName);
  const data = await jsonFetch(`/api/project-objects?project=${encodeURIComponent(projectName)}`);
  const items = data.items || [];
  state.objectCache.set(projectName, items);
  return items;
}

function filterObjects(items, keyword) {
  const query = String(keyword || "").trim().toLowerCase();
  if (!query) return items;
  return items.filter((item) => {
    const api = String(item.api_name || "").toLowerCase();
    const label = String(item.label || "").toLowerCase();
    const display = String(item.display || "").toLowerCase();
    return api.includes(query) || label.includes(query) || display.includes(query);
  });
}

async function refreshObjectSelect(project) {
  const objectApiInput = document.getElementById("single-object-api");
  const objectLabelInput = document.getElementById("single-object-label");
  const objectHint = document.getElementById("single-object-hint");
  const objectSearch = document.getElementById("single-object-search");
  const dropdown = document.getElementById("single-object-dropdown");
  const projectName = (project || "").trim();
  objectApiInput.value = "";
  objectLabelInput.value = "";
  objectSearch.value = "";
  dropdown.innerHTML = "";
  dropdown.classList.add("hidden");
  if (!projectName) {
    objectHint.textContent = "选择项目后会自动加载绑定对象";
    return;
  }
  let items = [];
  try {
    items = await loadProjectObjects(projectName);
  } catch (err) {
    objectHint.textContent = `对象加载失败：${err.message || err}`;
    return;
  }
  if (!items.length) {
    objectHint.textContent = "当前项目没有已拉取对象，请先拉取 sharedev 数据";
    return;
  }
  objectHint.textContent = `已加载 ${items.length} 个对象`;
  dropdown.classList.add("hidden");
  state.objectDropdownIndex = -1;
}

function selectObject(item) {
  const objectApiInput = document.getElementById("single-object-api");
  const objectLabelInput = document.getElementById("single-object-label");
  const objectHint = document.getElementById("single-object-hint");
  const objectSearch = document.getElementById("single-object-search");
  const dropdown = document.getElementById("single-object-dropdown");
  if (!item || !item.api_name) return;
  objectApiInput.value = item.api_name;
  objectLabelInput.value = item.label || item.api_name;
  objectSearch.value = item.display || `${item.label || item.api_name} (${item.api_name})`;
  objectHint.textContent = `当前对象：${objectLabelInput.value} (${item.api_name})`;
  dropdown.classList.add("hidden");
  state.objectDropdownIndex = -1;
}

function getObjectOptionNodes() {
  return Array.from(document.querySelectorAll("#single-object-dropdown .object-option[data-api]"));
}

function setActiveObjectOption(index) {
  const nodes = getObjectOptionNodes();
  state.objectDropdownIndex = nodes.length ? Math.max(0, Math.min(index, nodes.length - 1)) : -1;
  nodes.forEach((node, idx) => node.classList.toggle("is-active", idx === state.objectDropdownIndex));
  const active = nodes[state.objectDropdownIndex];
  if (active) {
    active.scrollIntoView({ block: "nearest" });
  }
}

function renderStats(data) {
  const tasks = data.tasks || [];
  const successCount = tasks.filter((item) => item.status === "success").length;
  const failedCount = tasks.filter((item) => item.status === "failed").length;
  document.getElementById("stat-projects").textContent = String((data.projects || []).length);
  document.getElementById("stat-tasks").textContent = String(tasks.length);
  document.getElementById("stat-success").textContent = String(successCount);
  document.getElementById("stat-failed").textContent = String(failedCount);
}

function renderObjectDropdown(project, keyword = "") {
  const dropdown = document.getElementById("single-object-dropdown");
  const hint = document.getElementById("single-object-hint");
  const items = state.objectCache.get((project || "").trim()) || [];
  const filtered = filterObjects(items, keyword);
  if (!items.length || !dropdown || !hint) return;
  if (!filtered.length) {
    dropdown.innerHTML = `<div class="object-option"><div class="object-option-title">未找到匹配对象</div></div>`;
    dropdown.classList.remove("hidden");
    hint.textContent = `未匹配到对象`;
    state.objectDropdownIndex = -1;
    return;
  }
  dropdown.innerHTML = filtered.map((item) => `
    <div class="object-option" data-api="${escapeHtml(item.api_name)}" data-label="${escapeHtml(item.label)}" data-display="${escapeHtml(item.display)}">
      <div class="object-option-title">${escapeHtml(item.label)}</div>
      <div class="object-option-sub">${escapeHtml(item.api_name)}</div>
    </div>
  `).join("");
  dropdown.classList.remove("hidden");
  dropdown.querySelectorAll(".object-option[data-api]").forEach((node) => {
    node.onclick = () => {
      selectObject({
        api_name: node.dataset.api,
        label: node.dataset.label,
        display: node.dataset.display,
      });
    };
  });
  hint.textContent = keyword
    ? `已匹配 ${filtered.length} / ${items.length} 个对象`
    : `已加载 ${items.length} 个对象`;
  setActiveObjectOption(0);
}

function openLogModal(title, content) {
  document.getElementById("log-modal-title").textContent = title || "任务日志";
  document.getElementById("task-log").textContent = content || "暂无日志";
  document.getElementById("log-modal").classList.remove("hidden");
  document.body.classList.add("modal-open");
}

function closeLogModal() {
  document.getElementById("log-modal").classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function renderHistorySummary(filters, count) {
  const node = document.getElementById("history-filter-summary");
  if (!node) return;
  const labels = [];
  if (filters.project) labels.push(`项目：${filters.project}`);
  if (filters.kind === "single") labels.push("单条生成");
  if (filters.kind === "batch") labels.push("批量生成");
  if (filters.kind === "batch_upload") labels.push("模板批量");
  if (filters.status === "running") labels.push("执行中");
  if (filters.status === "success") labels.push("成功");
  if (filters.status === "failed") labels.push("失败");
  if (filters.deploy_result === "success") labels.push("部署成功");
  if (filters.deploy_result === "failed") labels.push("部署失败");
  if (filters.date_from || filters.date_to) labels.push(`时间：${filters.date_from || "不限"} ~ ${filters.date_to || "不限"}`);
  if (filters.api_name) labels.push(`关键词：${filters.api_name}`);
  node.textContent = labels.length ? `当前筛选：${labels.join(" / ")}，共 ${count} 条` : `当前显示全部记录，共 ${count} 条`;
}

function applyHistoryFilters() {
  const form = $("history-filter-form");
  if (!form) return;
  const data = new FormData(form);
  state.historyFilters = {};
  state.historyPage = 1;
  for (const [key, value] of data.entries()) {
    const text = String(value || "").trim();
    if (text) state.historyFilters[key] = text;
  }
  refreshTasks();
}

async function refreshDashboard() {
  const data = await jsonFetch("/api/dashboard");
  state.projects = data.projects || [];
  const preferredProject = localStorage.getItem(STORAGE_KEYS.selectedProject) || "";
  const configProject = (state.projects.find((p) => p.is_current) || {}).name || "";
  state.currentProject = state.projects.some((p) => p.name === preferredProject) ? preferredProject : configProject;
  const settings = data.settings || {};
  state.projectDomains = new Map(Object.entries(settings.project_domains || {}));
  renderStats(data);

  fillProjectSelect($("single-project"), state.projects, state.currentProject, "请选择项目");
  fillProjectSelect($("batch-project"), state.projects, state.currentProject, "当前项目");
  fillProjectSelect($("batch-upload-project"), state.projects, state.currentProject, "全部项目");
  fillProjectSelect($("history-project"), state.projects, "", "全部项目");
  fillProjectSelect($("settings-project-name"), state.projects, state.currentProject, "请选择项目");
  fillProjectSelect($("cert-project"), state.projects, state.currentProject, "请选择项目");

  if (state.currentProject) {
    if ($("single-project")) $("single-project").value = state.currentProject;
    if ($("batch-project")) $("batch-project").value = state.currentProject;
    if ($("batch-upload-project")) $("batch-upload-project").value = state.currentProject;
    if ($("settings-project-name")) $("settings-project-name").value = state.currentProject;
    if ($("cert-project")) $("cert-project").value = state.currentProject;
  }

  const settingsForm = $("settings-form");
  settingsForm.querySelector('[name="bootstrap_token_url"]').value = settings.bootstrap_token_url || "";
  settingsForm.querySelector('[name="username"]').value = settings.username || "";
  settingsForm.querySelector('[name="password"]').value = "";
  settingsForm.querySelector('[name="agent_login_employee_id"]').value = settings.agent_login_employee_id || "";
  settingsForm.querySelector('[name="domain"]').value = settings.domain || "";

  await refreshObjectSelect(($("single-project") && $("single-project").value) || state.currentProject);
  await renderProjectOverview();
}

async function refreshTasks() {
  const qs = new URLSearchParams(state.historyFilters);
  const data = await jsonFetch(`/api/tasks?${qs.toString()}`);
  const container = document.getElementById("tasks");
  container.innerHTML = "";
  const allItems = data.items || [];
  const total = allItems.length;
  const totalPages = Math.max(1, Math.ceil(total / state.historyPageSize));
  if (state.historyPage > totalPages) state.historyPage = totalPages;
  const startIndex = (state.historyPage - 1) * state.historyPageSize;
  const pageItems = allItems.slice(startIndex, startIndex + state.historyPageSize);
  renderHistorySummary(state.historyFilters, total);
  let lastProject = "";
  pageItems.forEach((task) => {
    const project = (task.req_snapshot && task.req_snapshot.project) || "-";
    if (project !== lastProject) {
      const groupRow = document.createElement("tr");
      groupRow.className = "history-group-row";
      groupRow.innerHTML = `<td colspan="8"><div class="row-title">${escapeHtml(project)}</div></td>`;
      container.appendChild(groupRow);
      lastProject = project;
    }
    const row = document.createElement("tr");
    const statusClass =
      task.status === "success" ? "success" :
      task.status === "failed" ? "failed" : "running";
    const statusLabel = task.status === "success" ? "成功" : task.status === "failed" ? "失败" : "执行中";
    const kindLabel =
      task.kind === "single" ? "单条生成" :
      task.kind === "batch" ? "批量生成" :
      task.kind === "batch_upload" ? "模板批量" : (task.kind || "-");
    row.className = `is-${statusClass}`;
    row.innerHTML = `
      <td>${escapeHtml(project)}</td>
      <td>
        <div class="row-title">${escapeHtml(kindLabel)}</div>
      </td>
      <td><span class="status-dot ${statusClass}">${escapeHtml(statusLabel)}</span></td>
      <td>${escapeHtml(task.started_at || "-")}</td>
      <td>${escapeHtml(task.compile_message || "-")}</td>
      <td>${escapeHtml(task.deploy_message || "-")}</td>
      <td>${escapeHtml(task.api_name || "-")}</td>
      <td>
        <div class="row-actions">
          <button type="button" class="ghost-button action-view-function">查看函数</button>
          ${task.status === "failed" ? `<button type="button" class="ghost-button action-rerun">重新执行</button>` : ""}
          ${task.api_name ? `<button type="button" class="ghost-button action-runtime-log">运行日志</button>` : ""}
          <button type="button" class="ghost-button action-task-log">执行日志</button>
        </div>
      </td>
    `;
    row.onclick = async (event) => {
      if (event.target.closest("button")) return;
      const log = await fetch(`/api/tasks/${task.id}/log`).then((r) => r.text());
      openLogModal(task.title || "任务日志", log);
    };
    const taskLogBtn = row.querySelector(".action-task-log");
    if (taskLogBtn) {
      taskLogBtn.onclick = async (event) => {
        event.stopPropagation();
        const log = await fetch(`/api/tasks/${task.id}/log`).then((r) => r.text());
        openLogModal(task.title || "任务日志", log);
      };
    }
    const functionBtn = row.querySelector(".action-view-function");
    if (functionBtn) {
      functionBtn.onclick = async (event) => {
        event.stopPropagation();
        await viewGeneratedFunction(task);
      };
    }
    const rerunBtn = row.querySelector(".action-rerun");
    if (rerunBtn) {
      rerunBtn.onclick = async (event) => {
        event.stopPropagation();
        rerunBtn.disabled = true;
        rerunBtn.textContent = "重试中...";
        try {
          await jsonFetch(`/api/tasks/${task.id}/rerun`, { method: "POST", body: JSON.stringify({}) });
          await refreshTasks();
        } catch (err) {
          openLogModal("重新执行失败", String(err.message || err));
        } finally {
          rerunBtn.disabled = false;
          rerunBtn.textContent = "重新执行";
        }
      };
    }
    const runtimeBtn = row.querySelector(".action-runtime-log");
    if (runtimeBtn) {
      runtimeBtn.onclick = async (event) => {
        event.stopPropagation();
        await runFunctionLog(project, task.api_name);
      };
    }
    container.appendChild(row);
  });
  renderHistoryPagination(total, totalPages);
}

async function renderProjectOverview() {
  const wrap = $("projects");
  if (!wrap) return;
  try {
    const data = await jsonFetch("/api/session-status");
    const items = data.items || [];
    const sessionMap = new Map(items.map((item) => [item.project, item]));
    wrap.innerHTML = state.projects.map((project) => {
      const session = sessionMap.get(project.name) || {};
      const loggedIn = !!session.logged_in;
      const hasCert = !!project.has_certificate;
      return `
      <div class="project-card ${project.is_current ? "is-current" : ""}">
        <div class="project-card-head">
          <div class="project-card-title">${escapeHtml(project.name)}</div>
          ${project.is_current ? '<span class="pill">当前项目</span>' : ""}
        </div>
        <div class="project-card-body">
          <div class="status-stack">
            <div class="status-row">
              <span class="status-label">登录状态</span>
              <span class="status-dot ${loggedIn ? "logged-in" : "offline"}">${loggedIn ? "已登录" : "未登录"}</span>
            </div>
            <div class="status-row">
              <span class="status-label">session 有效期</span>
              <span class="status-value">${escapeHtml(session.expires_at || "未知")}</span>
            </div>
            <div class="status-row">
              <span class="status-label">开发者证书</span>
              <span class="status-dot ${hasCert ? "logged-in" : "offline"}">${hasCert ? "已配置" : "未配置"}</span>
            </div>
          </div>
        </div>
        <div class="project-card-actions">
          <button type="button" class="ghost-button project-session-refresh" data-project="${escapeHtml(project.name)}">更换 session</button>
          <button type="button" class="ghost-button project-export-functions" data-project="${escapeHtml(project.name)}">导出函数文档</button>
        </div>
      </div>
    `;
    }).join("");
    wrap.querySelectorAll(".project-session-refresh").forEach((btn) => {
      btn.onclick = async () => {
        const project = btn.dataset.project || "";
        btn.disabled = true;
        btn.textContent = "刷新中...";
        try {
          const result = await jsonFetch("/api/session-refresh", {
            method: "POST",
            body: JSON.stringify({ project }),
          });
          await renderProjectOverview();
          $("settings-result").textContent = JSON.stringify(result, null, 2);
        } catch (err) {
          $("settings-result").textContent = String(err.message || err);
        } finally {
          btn.disabled = false;
          btn.textContent = "更换 session";
        }
      };
    });
    wrap.querySelectorAll(".project-export-functions").forEach((btn) => {
      btn.onclick = () => {
        const project = btn.dataset.project || "";
        window.location.href = `/api/functions/export?project=${encodeURIComponent(project)}`;
      };
    });
  } catch (err) {
    wrap.innerHTML = `<div class="row-sub">项目状态加载失败：${escapeHtml(err.message || err)}</div>`;
  }
}

if ($("refresh-history")) $("refresh-history").onclick = refreshTasks;
if ($("log-modal-close")) $("log-modal-close").onclick = closeLogModal;
if ($("log-modal-backdrop")) $("log-modal-backdrop").onclick = closeLogModal;
if ($("function-modal-close")) $("function-modal-close").onclick = closeFunctionModal;
if ($("function-modal-backdrop")) $("function-modal-backdrop").onclick = closeFunctionModal;

if ($("single-project")) $("single-project").onchange = async (e) => {
  localStorage.setItem(STORAGE_KEYS.selectedProject, e.target.value || "");
  await refreshObjectSelect(e.target.value);
};

if ($("batch-project")) $("batch-project").onchange = (e) => {
  localStorage.setItem(STORAGE_KEYS.selectedProject, e.target.value || "");
};

if ($("batch-upload-project")) $("batch-upload-project").onchange = (e) => {
  localStorage.setItem(STORAGE_KEYS.selectedProject, e.target.value || "");
};

if ($("single-object-search")) $("single-object-search").oninput = debounce((e) => {
  const project = $("single-project").value || state.currentProject;
  renderObjectDropdown(project, e.target.value);
});

if ($("single-object-search")) {
  $("single-object-search").onfocus = () => {
    const project = $("single-project").value || state.currentProject;
    renderObjectDropdown(project, $("single-object-search").value || "");
  };
  $("single-object-search").onkeydown = (event) => {
    const dropdown = $("single-object-dropdown");
    const project = $("single-project").value || state.currentProject;
    if (event.key === "ArrowDown") {
      if (dropdown.classList.contains("hidden")) {
        renderObjectDropdown(project, $("single-object-search").value || "");
      } else {
        setActiveObjectOption(state.objectDropdownIndex + 1);
      }
      event.preventDefault();
      return;
    }
    if (event.key === "ArrowUp") {
      if (!dropdown.classList.contains("hidden")) {
        setActiveObjectOption(state.objectDropdownIndex - 1);
        event.preventDefault();
      }
      return;
    }
    if (event.key === "Enter") {
      const nodes = getObjectOptionNodes();
      const active = nodes[state.objectDropdownIndex];
      if (active) {
        active.click();
        event.preventDefault();
      }
      return;
    }
    if (event.key === "Escape") {
      dropdown.classList.add("hidden");
      state.objectDropdownIndex = -1;
    }
  };
}

if ($("settings-project-name")) $("settings-project-name").onchange = (e) => {
  localStorage.setItem(STORAGE_KEYS.selectedProject, e.target.value || "");
  const domainInput = document.querySelector('#settings-form [name="domain"]');
  const project = (e.target.value || "").trim();
  domainInput.value = state.projectDomains.get(project) || "";
};

if ($("single-form")) $("single-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = Object.fromEntries(form.entries());
  payload.web_create_api = true;
  payload.no_notify = true;
  await jsonFetch("/api/run/single", { method: "POST", body: JSON.stringify(payload) });
  refreshTasks();
};

if ($("batch-form")) $("batch-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = Object.fromEntries(form.entries());
  payload.no_notify = true;
  payload.web_create_api = true;
  payload.dry_run = false;
  payload.regenerate = false;
  const res = await jsonFetch("/api/run/batch", { method: "POST", body: JSON.stringify(payload) });
  $("batch-result").textContent = JSON.stringify(res, null, 2);
  refreshTasks();
};

if ($("batch-upload-form")) $("batch-upload-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  if (!form.get("file") || !form.get("file").name) {
    $("batch-result").textContent = "请先选择模板文件";
    return;
  }
  const resp = await fetch("/api/run/batch-upload", { method: "POST", body: form });
  const res = await resp.json();
  $("batch-result").textContent = JSON.stringify(res, null, 2);
  refreshTasks();
};

if ($("settings-form")) $("settings-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = Object.fromEntries(form.entries());
  const res = await jsonFetch("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  $("settings-result").textContent = JSON.stringify(res, null, 2);
  refreshDashboard();
};

if ($("cert-form")) $("cert-form").onsubmit = async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const payload = {
    certificate: {
      project: form.get("project"),
      certificate: form.get("certificate"),
    }
  };
  const res = await jsonFetch("/api/settings", { method: "POST", body: JSON.stringify(payload) });
  $("settings-result").textContent = JSON.stringify(res, null, 2);
  refreshDashboard();
};

if ($("history-filter-form")) $("history-filter-form").onsubmit = async (e) => {
  e.preventDefault();
  applyHistoryFilters();
};

["history-project", "history-kind", "history-status", "history-deploy-result", "history-date-from", "history-date-to"].forEach((id) => {
  const el = document.getElementById(id);
  if (el) {
    el.onchange = applyHistoryFilters;
  }
});

const historyApiInput = document.getElementById("history-api-name");
if (historyApiInput) {
  historyApiInput.oninput = debounce(() => applyHistoryFilters(), 260);
}

if ($("history-reset")) $("history-reset").onclick = () => {
  $("history-filter-form").reset();
  state.historyFilters = {};
  state.historyPage = 1;
  refreshTasks();
};

document.addEventListener("click", (event) => {
  const combo = $("single-object-combobox");
  const dropdown = $("single-object-dropdown");
  if (!combo || !dropdown) return;
  if (!combo.contains(event.target)) {
    dropdown.classList.add("hidden");
    state.objectDropdownIndex = -1;
  }
});

refreshDashboard();
refreshTasks();
setInterval(refreshTasks, 5000);

function closeFunctionModal() {
  $("function-modal").classList.add("hidden");
  document.body.classList.remove("modal-open");
}

function openFunctionModal(item) {
  $("function-modal-title").textContent = item.function_name || "函数详情";
  $("function-modal-subtitle").textContent = `${item.function_type || ""} · ${item.api_name || ""}`;
  $("function-meta").innerHTML = [
    ["项目", item.project],
    ["函数类型", item.function_type],
    ["绑定对象", item.binding_object_label || item.binding_object_api_name],
    ["绑定对象 API", item.binding_object_api_name],
    ["系统 API", item.api_name],
    ["执行时间", item.updated_at],
    ["需求描述", item.description],
  ].map(([label, value]) => `
    <div class="function-meta-card">
      <div class="function-meta-label">${escapeHtml(label)}</div>
      <div class="function-meta-value">${escapeHtml(value || "-")}</div>
    </div>
  `).join("");
  $("function-code").textContent = item.body || "暂无函数内容";
  $("function-modal").classList.remove("hidden");
  document.body.classList.add("modal-open");
}

async function viewFunction(project, apiName) {
  const data = await jsonFetch(`/api/functions/detail?project=${encodeURIComponent(project)}&api_name=${encodeURIComponent(apiName)}`);
  openFunctionModal(data.item || {});
}

async function viewGeneratedFunction(task) {
  if (task.api_name) {
    await viewFunction((task.req_snapshot && task.req_snapshot.project) || "-", task.api_name);
    return;
  }
  const data = await jsonFetch(`/api/tasks/${task.id}/artifact`);
  openFunctionModal(data.item || {});
}

async function runFunctionLog(project, apiName) {
  const data = await jsonFetch("/api/functions/runtime-log", {
    method: "POST",
    body: JSON.stringify({ project, api_name: apiName }),
  });
  const title = `${data.function_name || apiName} · 运行日志`;
  const content = data.log_info || data.error_info || "暂无运行日志";
  openLogModal(title, content);
}

function renderHistoryPagination(total, totalPages) {
  const wrap = $("history-pagination");
  if (!wrap) return;
  if (!total) {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = `
    <div class="pagination-info">第 ${state.historyPage} / ${totalPages} 页，共 ${total} 条</div>
    <button type="button" class="ghost-button" id="history-prev" ${state.historyPage <= 1 ? "disabled" : ""}>上一页</button>
    <button type="button" class="ghost-button" id="history-next" ${state.historyPage >= totalPages ? "disabled" : ""}>下一页</button>
  `;
  const prev = $("history-prev");
  const next = $("history-next");
  if (prev) {
    prev.onclick = () => {
      if (state.historyPage <= 1) return;
      state.historyPage -= 1;
      refreshTasks();
    };
  }
  if (next) {
    next.onclick = () => {
      if (state.historyPage >= totalPages) return;
      state.historyPage += 1;
      refreshTasks();
    };
  }
}
