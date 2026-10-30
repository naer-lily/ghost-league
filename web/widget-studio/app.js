(() => {
  "use strict";

  const TOKEN_KEY = "gl.token.v1";
  const LAST_TEMPLATE_KEY = "gl.widget-studio.last-template.v1";
  const API = "/v1/widget-studio";
  const CANVAS_W = 1536;
  const CANVAS_H = 914;
  const THEME = "#f6b545";
  const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

  const $ = (id) => document.getElementById(id);

  class ApiError extends Error {
    constructor(status, detail) {
      const text = typeof detail === "string" ? detail : JSON.stringify(detail || {});
      super(text || `HTTP ${status}`);
      this.status = status;
      this.detail = detail;
    }
  }

  const state = {
    token: "",
    templates: [],
    template: null,
    selectedLayerId: null,
    selectedBgId: null,
    manualBgId: null,
    autoSelect: true,
    preview: {
      hour: 10,
      weekday: 1,
      streak: 12,
      xp: 345,
      rank: 3,
      name: "那尔",
      completed_today: false,
      league: "",
      event: "",
    },
    library: null,
    dirty: false,
    revision: 0,
    saving: null,
    saveTimer: null,
    drag: null,
    raf: 0,
    imageCache: new Map(),
    toastTimer: null,
  };

  // -- small helpers -------------------------------------------------
  function esc(value) {
    return String(value == null ? "" : value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function num(value, fallback = 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function round(value) {
    return Math.round(num(value) * 10) / 10;
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function clampInt(value, minimum, maximum, fallback) {
    if (value === "" || value == null || !Number.isFinite(Number(value))) return fallback;
    return Math.max(minimum, Math.min(maximum, Math.round(Number(value))));
  }

  function slugify(value) {
    return String(value)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 48);
  }

  function uniqueId(base, existing) {
    const ids = new Set(existing);
    let candidate = base || "item";
    let suffix = 1;
    while (ids.has(candidate)) {
      suffix += 1;
      candidate = `${base}-${suffix}`;
    }
    return candidate;
  }

  function toast(message, kind = "") {
    const element = $("toast");
    element.textContent = message;
    element.className = `toast${kind ? ` is-${kind}` : ""}`;
    element.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => {
      element.hidden = true;
    }, 3600);
  }

  function setStatus(message, kind = "") {
    const element = $("sync-status");
    element.textContent = message;
    element.className = `sync-status${kind ? ` is-${kind}` : ""}`;
  }

  function clearPendingSave() {
    if (state.saveTimer) {
      clearTimeout(state.saveTimer);
      state.saveTimer = null;
    }
  }

  // -- HTTP ----------------------------------------------------------
  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    let body = options.body;
    if (options.form) {
      body = options.form;
    } else if (body !== undefined && body !== null && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    const response = await fetch(`${API}${path}`, {
      method: options.method || "GET",
      headers,
      body,
      cache: "no-store",
      keepalive: Boolean(options.keepalive),
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      if (response.status === 401) {
        requireLogin("令牌无效或已过期，请重新粘贴 Ghost 令牌。");
      }
      const detail = payload && typeof payload === "object" ? payload.detail : payload;
      throw new ApiError(response.status, detail);
    }
    return payload;
  }

  function requireLogin(message) {
    state.token = "";
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* storage may be unavailable */
    }
    $("auth-error").textContent = message || "";
    $("auth-gate").hidden = false;
    $("studio-shell").hidden = true;
    setStatus("需要 Ghost 令牌");
  }

  // -- boot ----------------------------------------------------------
  async function boot() {
    $("auth-gate").hidden = true;
    $("studio-shell").hidden = false;
    setStatus("正在加载…", "saving");
    try {
      const templates = await api("/templates");
      state.templates = Array.isArray(templates) ? templates : [];
      renderTemplateSelect();
      if (!state.templates.length) {
        state.template = null;
        state.selectedLayerId = null;
        state.selectedBgId = null;
        renderAll();
        setStatus("等待新建模版");
        openTemplateModal();
        return;
      }
      let target = null;
      try {
        target = localStorage.getItem(LAST_TEMPLATE_KEY);
      } catch {
        target = null;
      }
      if (!state.templates.some((item) => item.id === target)) {
        target = state.templates[0].id;
      }
      await openTemplate(target);
    } catch (error) {
      if (error.status === 401) return;
      setStatus(`加载失败：${error.message}`, "error");
      toast(`加载失败：${error.message}`, "error");
    }
  }

  async function loadTemplates() {
    const templates = await api("/templates");
    state.templates = Array.isArray(templates) ? templates : [];
    renderTemplateSelect();
  }

  function storeLastTemplate(id) {
    try {
      localStorage.setItem(LAST_TEMPLATE_KEY, id);
    } catch {
      /* ignore */
    }
  }

  async function openTemplate(id) {
    await flushSave();
    const template = await api(`/templates/${encodeURIComponent(id)}`);
    state.template = template;
    state.imageCache.clear();
    state.selectedLayerId = template.layers[0]?.id || null;
    const fallback = template.backgrounds.find((bg) => !Object.keys(bg.when || {}).length);
    state.selectedBgId = (fallback || template.backgrounds[0])?.id || null;
    state.manualBgId = state.selectedBgId;
    if (!state.autoSelect && !template.backgrounds.some((bg) => bg.id === state.manualBgId)) {
      state.manualBgId = state.selectedBgId;
    }
    state.dirty = false;
    state.revision += 1;
    state.drag = null;
    storeLastTemplate(template.id);
    renderAll();
    setStatus(`已同步到 data/widgets/${template.id}`, "saved");
  }

  // -- template list ------------------------------------------------
  function renderTemplateSelect() {
    const select = $("template-select");
    select.innerHTML = "";
    if (!state.templates.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "暂无模版";
      select.append(option);
      select.disabled = true;
      $("duplicate-template-btn").disabled = true;
      $("delete-template-btn").disabled = true;
      $("copy-production-url").disabled = true;
      return;
    }
    select.disabled = false;
    $("duplicate-template-btn").disabled = false;
    $("delete-template-btn").disabled = false;
    $("copy-production-url").disabled = false;
    for (const template of state.templates) {
      const option = document.createElement("option");
      option.value = template.id;
      option.textContent = `${template.name} (${template.id})`;
      select.append(option);
    }
    if (state.template) select.value = state.template.id;
  }

  // -- layers --------------------------------------------------------
  function selectedLayer() {
    if (!state.template) return null;
    return state.template.layers.find((layer) => layer.id === state.selectedLayerId) || null;
  }

  function renderLayerList() {
    const list = $("layer-list");
    list.innerHTML = "";
    if (!state.template) return;
    for (const layer of state.template.layers) {
      const item = document.createElement("li");
      item.className = `layer-item${layer.id === state.selectedLayerId ? " is-selected" : ""}`;
      item.dataset.layerId = layer.id;
      const preview =
        layer.type === "text"
          ? String(layer.text || "").replace(/\s+/g, " ").slice(0, 24) || "（空文字）"
          : layer.src;
      item.innerHTML = `
        <span class="layer-icon" aria-hidden="true">${layer.type === "text" ? "文" : "图"}</span>
        <span class="layer-main">
          <strong>${esc(layer.role || layer.type)}</strong>
          <small>${esc(preview)}</small>
        </span>`;
      item.addEventListener("click", () => selectLayer(layer.id));
      list.append(item);
    }
  }

  function selectLayer(id) {
    state.selectedLayerId = id;
    renderLayerList();
    renderLayerInspector();
    requestDraw();
  }

  function renderLayerInspector() {
    const layer = selectedLayer();
    const kind = $("layer-kind");
    const inspector = $("layer-inspector");
    if (!layer) {
      kind.textContent = "未选择";
      inspector.innerHTML = '<p class="empty">在画布或左侧图层列表选择一个图层。</p>';
      return;
    }
    kind.textContent = layer.type === "text" ? "文字" : "图片";
    if (layer.type === "text") {
      const shadow = layer.shadow;
      inspector.innerHTML = `
        <label class="field"><span>文字内容</span>
          <textarea id="layer-text" maxlength="500">${esc(layer.text)}</textarea>
        </label>
        <div class="field-grid">
          <label class="field"><span>X</span><input id="layer-x" type="number" step="1" value="${esc(layer.x)}"></label>
          <label class="field"><span>Y</span><input id="layer-y" type="number" step="1" value="${esc(layer.y)}"></label>
          <label class="field"><span>宽 W</span><input id="layer-w" type="number" step="1" min="1" value="${esc(layer.w)}"></label>
          <label class="field"><span>高 H</span><input id="layer-h" type="number" step="1" min="1" value="${esc(layer.h)}"></label>
        </div>
        <div class="field-grid">
          <label class="field"><span>字号</span><input id="layer-font-size" type="number" step="1" min="1" value="${esc(layer.fontSize)}"></label>
          <label class="field"><span>字重</span><input id="layer-font-weight" type="number" step="100" min="100" max="900" value="${esc(layer.fontWeight)}"></label>
        </div>
        <div class="field-grid">
          <label class="field"><span>颜色</span><input id="layer-color" type="text" value="${esc(layer.color)}"></label>
          <label class="field"><span>对齐</span>
            <select id="layer-align">
              <option value="left"${layer.align === "left" ? " selected" : ""}>左对齐</option>
              <option value="center"${layer.align === "center" ? " selected" : ""}>居中</option>
              <option value="right"${layer.align === "right" ? " selected" : ""}>右对齐</option>
            </select>
          </label>
        </div>
        <div class="field-grid">
          <label class="field"><span>行高</span><input id="layer-line-height" type="number" step="0.05" min="0.1" value="${esc(layer.lineHeight)}"></label>
          <label class="field"><span>占位符</span><input type="text" value="{streak} {xp} {rank} {name}" readonly></label>
        </div>
        <div class="divider"></div>
        <label class="check-row"><input id="layer-shadow-enabled" type="checkbox"${shadow ? " checked" : ""}> 启用阴影</label>
        <div id="layer-shadow-fields" class="inspector"${shadow ? "" : " hidden"}>
          <div class="field-grid">
            <label class="field"><span>阴影颜色</span><input id="layer-shadow-color" type="text" value="${esc(shadow ? shadow.color : "rgba(0,0,0,0.35)")}"></label>
            <label class="field"><span>模糊</span><input id="layer-shadow-blur" type="number" step="1" min="0" value="${esc(shadow ? shadow.blur : 0)}"></label>
            <label class="field"><span>X 偏移</span><input id="layer-shadow-x" type="number" step="1" value="${esc(shadow ? shadow.offsetX : 0)}"></label>
            <label class="field"><span>Y 偏移</span><input id="layer-shadow-y" type="number" step="1" value="${esc(shadow ? shadow.offsetY : 0)}"></label>
          </div>
        </div>`;
      bindLayerTextInputs(layer);
      return;
    }
    inspector.innerHTML = `
      <div class="field"><span>来源</span><input type="text" value="${esc(layer.src)}" readonly></div>
      <div class="field-grid">
        <label class="field"><span>X</span><input id="layer-x" type="number" step="1" value="${esc(layer.x)}"></label>
        <label class="field"><span>Y</span><input id="layer-y" type="number" step="1" value="${esc(layer.y)}"></label>
        <label class="field"><span>宽 W</span><input id="layer-w" type="number" step="1" min="1" value="${esc(layer.w)}"></label>
        <label class="field"><span>高 H</span><input id="layer-h" type="number" step="1" min="1" value="${esc(layer.h)}"></label>
      </div>
      <label class="field"><span>透明度 ${esc(layer.opacity)}</span><input id="layer-opacity" type="number" step="0.05" min="0" max="1" value="${esc(layer.opacity)}"></label>`;
    bindLayerGeometry(layer);
    $("layer-opacity").addEventListener("input", (event) => {
      layer.opacity = Math.max(0, Math.min(1, num(event.target.value, 1)));
      requestDraw();
      scheduleSave();
    });
  }

  function bindLayerGeometry(layer) {
    for (const [key, id, minimum] of [
      ["x", "layer-x", null],
      ["y", "layer-y", null],
      ["w", "layer-w", 1],
      ["h", "layer-h", 1],
    ]) {
      $(id)?.addEventListener("input", (event) => {
        let value = round(event.target.value);
        if (minimum != null) value = Math.max(minimum, value);
        layer[key] = value;
        requestDraw();
        scheduleSave();
      });
    }
  }

  function bindLayerTextInputs(layer) {
    bindLayerGeometry(layer);
    $("layer-text").addEventListener("input", (event) => {
      layer.text = event.target.value;
      renderLayerList();
      requestDraw();
      scheduleSave();
    });
    for (const [key, id, minimum] of [
      ["fontSize", "layer-font-size", 1],
      ["fontWeight", "layer-font-weight", 100],
      ["lineHeight", "layer-line-height", 0.1],
    ]) {
      $(id).addEventListener("input", (event) => {
        layer[key] = Math.max(minimum, round(event.target.value));
        requestDraw();
        scheduleSave();
      });
    }
    $("layer-color").addEventListener("input", (event) => {
      layer.color = event.target.value;
      requestDraw();
      scheduleSave();
    });
    $("layer-align").addEventListener("change", (event) => {
      layer.align = event.target.value;
      requestDraw();
      scheduleSave();
    });
    $("layer-shadow-enabled").addEventListener("change", (event) => {
      layer.shadow = event.target.checked
        ? { color: "rgba(0,0,0,0.35)", blur: 0, offsetX: 0, offsetY: 0 }
        : null;
      renderLayerInspector();
      requestDraw();
      scheduleSave();
    });
    const shadowBindings = [
      ["color", "layer-shadow-color", "text"],
      ["blur", "layer-shadow-blur", "number"],
      ["offsetX", "layer-shadow-x", "number"],
      ["offsetY", "layer-shadow-y", "number"],
    ];
    for (const [key, id, type] of shadowBindings) {
      $(id)?.addEventListener("input", (event) => {
        if (!layer.shadow) return;
        layer.shadow[key] = type === "number" ? round(event.target.value) : event.target.value;
        requestDraw();
        scheduleSave();
      });
    }
  }

  function syncLayerGeometryInputs() {
    const layer = selectedLayer();
    if (!layer) return;
    for (const [key, id] of [
      ["x", "layer-x"],
      ["y", "layer-y"],
      ["w", "layer-w"],
      ["h", "layer-h"],
    ]) {
      const input = $(id);
      if (input && document.activeElement !== input) input.value = round(layer[key]);
    }
  }

  function addTextLayer() {
    if (!state.template) return;
    const id = uniqueId("text", state.template.layers.map((layer) => layer.id));
    state.template.layers.push({
      id,
      type: "text",
      role: "text",
      text: "新文字",
      x: 200,
      y: 200,
      w: 480,
      h: 100,
      fontSize: 48,
      fontWeight: 400,
      color: "#17324d",
      align: "left",
      lineHeight: 1.2,
      shadow: null,
    });
    state.selectedLayerId = id;
    renderLayerList();
    renderLayerInspector();
    requestDraw();
    scheduleSave();
  }

  // -- backgrounds ---------------------------------------------------
  function selectedBg() {
    if (!state.template) return null;
    return state.template.backgrounds.find((bg) => bg.id === state.selectedBgId) || null;
  }

  function conditionBits(when) {
    const bits = [];
    const value = when || {};
    if (value.hour_from != null && value.hour_to != null) {
      bits.push(`${pad2(value.hour_from)}–${pad2(value.hour_to)} 点`);
    }
    if (Array.isArray(value.weekdays) && value.weekdays.length) {
      const days = [...value.weekdays].sort((a, b) => a - b);
      if (days.join(",") === "1,2,3,4,5") bits.push("工作日");
      else if (days.join(",") === "6,7") bits.push("周末");
      else bits.push(days.map((day) => WEEKDAY_LABELS[day - 1]).join("、"));
    }
    if (value.streak_min != null && value.streak_max != null) {
      bits.push(`${pad2(value.streak_min)}–${pad2(value.streak_max)} 天`);
    } else if (value.streak_min != null) {
      bits.push(`≥${pad2(value.streak_min)} 天`);
    } else if (value.streak_max != null) {
      bits.push(`≤${pad2(value.streak_max)} 天`);
    }
    if (value.completed_today === true) bits.push("今日已完成");
    if (value.completed_today === false) bits.push("今日未完成");
    if (value.league) bits.push(`段位 ${value.league}`);
    if (value.event) bits.push(`事件 ${value.event}`);
    return bits;
  }

  function conditionSummary(when) {
    const bits = conditionBits(when);
    return bits.length ? bits.join(" · ") : "默认（fallback）";
  }

  function renderBackgroundList() {
    const list = $("background-list");
    list.innerHTML = "";
    if (!state.template) return;
    for (const bg of state.template.backgrounds) {
      const item = document.createElement("li");
      item.className = `bg-card${bg.id === state.selectedBgId ? " is-selected" : ""}`;
      item.dataset.bgId = bg.id;
      const thumb = `${API}/templates/${encodeURIComponent(state.template.id)}/backgrounds/${encodeURIComponent(bg.id)}/thumb?w=240`;
      const ghost = String(bg.src).startsWith("ghost:");
      item.innerHTML = `
        <div class="bg-card-head" data-role="select-bg">
          <img class="bg-thumb" src="${esc(thumb)}" alt="${esc(bg.name)} 底图缩略图" loading="lazy">
          <div class="bg-meta">
            <strong>${esc(bg.name)}</strong>
            <span class="bg-summary">${esc(conditionSummary(bg.when))}</span>
            <span class="bg-tags">
              <span class="tag is-priority">P${esc(bg.priority)}</span>
              ${ghost ? '<span class="tag is-ghost">Ghost 资源</span>' : '<span class="tag">本地</span>'}
              ${Object.keys(bg.when || {}).length ? "" : '<span class="tag">fallback</span>'}
            </span>
          </div>
        </div>
        <div class="bg-actions">
          <button class="btn icon" type="button" data-act="up" title="上移" aria-label="上移">↑</button>
          <button class="btn icon" type="button" data-act="down" title="下移" aria-label="下移">↓</button>
          <button class="btn" type="button" data-act="copy">复制</button>
          <button class="btn btn-danger" type="button" data-act="delete">删除</button>
        </div>`;
      list.append(item);
    }
  }

  function selectBackground(id) {
    state.selectedBgId = id;
    renderBackgroundList();
    renderBackgroundInspector();
    requestDraw();
  }

  function bgChanged() {
    renderBackgroundList();
    renderManualBgSelect();
    refreshConditionSummary();
    updateMatchBadge();
    requestDraw();
    scheduleSave();
  }

  function refreshConditionSummary() {
    const bg = selectedBg();
    const element = $("bg-cond-summary");
    if (element && bg) element.textContent = conditionSummary(bg.when);
  }

  function hourPreset(when) {
    if (!when || when.hour_from == null) return "any";
    const key = `${when.hour_from}-${when.hour_to}`;
    return ["5-11", "11-17", "17-22", "22-5"].includes(key) ? key : "custom";
  }

  function weekdayPreset(when) {
    if (!when || !Array.isArray(when.weekdays) || !when.weekdays.length) return "any";
    const days = [...when.weekdays].sort((a, b) => a - b).join(",");
    if (days === "1,2,3,4,5") return "workdays";
    if (days === "6,7") return "weekend";
    return "custom";
  }

  function renderBackgroundInspector() {
    const bg = selectedBg();
    const kind = $("bg-kind");
    const inspector = $("background-inspector");
    if (!bg) {
      kind.textContent = "未选择";
      inspector.innerHTML = '<p class="empty">在左侧底图列表选择一张底图。</p>';
      return;
    }
    kind.textContent = String(bg.src).startsWith("ghost:") ? "Ghost 资源" : "本地底图";
    const when = bg.when || (bg.when = {});
    const hp = hourPreset(when);
    const wp = weekdayPreset(when);
    const customDays = Array.isArray(when.weekdays) && when.weekdays.length ? when.weekdays : [1];
    inspector.innerHTML = `
      <div class="field-grid">
        <label class="field"><span>名称</span><input id="bg-name" type="text" maxlength="80" value="${esc(bg.name)}"></label>
        <label class="field"><span>优先级</span><input id="bg-priority" type="number" step="1" value="${esc(bg.priority)}"></label>
      </div>
      <div id="bg-cond-summary" class="cond-summary">${esc(conditionSummary(when))}</div>
      <h3>条件 when</h3>
      <label class="field"><span>时间</span>
        <select id="cond-hour-preset">
          <option value="any"${hp === "any" ? " selected" : ""}>任意</option>
          <option value="5-11"${hp === "5-11" ? " selected" : ""}>05–11</option>
          <option value="11-17"${hp === "11-17" ? " selected" : ""}>11–17</option>
          <option value="17-22"${hp === "17-22" ? " selected" : ""}>17–22</option>
          <option value="22-5"${hp === "22-5" ? " selected" : ""}>22–05</option>
          <option value="custom"${hp === "custom" ? " selected" : ""}>自定义</option>
        </select>
      </label>
      <div id="cond-hour-custom" class="field-grid"${hp === "custom" ? "" : " hidden"}>
        <label class="field"><span>起（含）</span><input id="cond-hour-from" type="number" min="0" max="23" value="${esc(when.hour_from ?? 5)}"></label>
        <label class="field"><span>止（不含）</span><input id="cond-hour-to" type="number" min="0" max="23" value="${esc(when.hour_to ?? 11)}"></label>
      </div>
      <label class="field"><span>星期</span>
        <select id="cond-weekday-preset">
          <option value="any"${wp === "any" ? " selected" : ""}>任意</option>
          <option value="workdays"${wp === "workdays" ? " selected" : ""}>工作日</option>
          <option value="weekend"${wp === "weekend" ? " selected" : ""}>周末</option>
          <option value="custom"${wp === "custom" ? " selected" : ""}>多选</option>
        </select>
      </label>
      <div id="cond-weekdays" class="weekday-grid"${wp === "custom" ? "" : " hidden"}>
        ${WEEKDAY_LABELS.map((label, index) => {
          const day = index + 1;
          return `<label><input type="checkbox" data-day="${day}"${customDays.includes(day) ? " checked" : ""}>${label}</label>`;
        }).join("")}
      </div>
      <div class="field-grid">
        <label class="field"><span>连胜最小值</span><input id="cond-streak-min" type="number" min="0" placeholder="不限" value="${esc(when.streak_min ?? "")}"></label>
        <label class="field"><span>连胜最大值</span><input id="cond-streak-max" type="number" min="0" placeholder="不限" value="${esc(when.streak_max ?? "")}"></label>
      </div>
      <label class="field"><span>今日已完成</span>
        <select id="cond-completed">
          <option value="any"${when.completed_today == null ? " selected" : ""}>任意</option>
          <option value="yes"${when.completed_today === true ? " selected" : ""}>是</option>
          <option value="no"${when.completed_today === false ? " selected" : ""}>否</option>
        </select>
      </label>
      <div class="field-grid">
        <label class="field"><span>段位（可空）</span><input id="cond-league" type="text" maxlength="64" value="${esc(when.league ?? "")}" placeholder="bronze"></label>
        <label class="field"><span>事件标签（可空）</span><input id="cond-event" type="text" maxlength="64" value="${esc(when.event ?? "")}" placeholder="rush"></label>
      </div>
      <h3>底图适配</h3>
      <div class="field-grid three">
        <label class="field"><span>fit</span>
          <select id="bg-fit">
            <option value="cover"${bg.fit === "cover" ? " selected" : ""}>cover</option>
            <option value="contain"${bg.fit === "contain" ? " selected" : ""}>contain</option>
          </select>
        </label>
        <label class="field"><span>scale</span><input id="bg-scale" type="number" step="0.05" min="0.05" value="${esc(bg.scale)}"></label>
        <label class="field"><span>优先级</span><input type="text" value="P${esc(bg.priority)}" readonly></label>
      </div>
      <div class="field-grid">
        <label class="field"><span>offsetX</span><input id="bg-offset-x" type="number" step="1" value="${esc(bg.offsetX)}"></label>
        <label class="field"><span>offsetY</span><input id="bg-offset-y" type="number" step="1" value="${esc(bg.offsetY)}"></label>
      </div>`;
    bindBackgroundInspector(bg, when);
  }

  function bindBackgroundInspector(bg, when) {
    $("bg-name").addEventListener("input", (event) => {
      bg.name = event.target.value || bg.id;
      renderBackgroundList();
      scheduleSave();
    });
    $("bg-priority").addEventListener("input", (event) => {
      bg.priority = Math.round(num(event.target.value, 0));
      renderBackgroundList();
      scheduleSave();
    });
    $("cond-hour-preset").addEventListener("change", (event) => {
      const value = event.target.value;
      $("cond-hour-custom").hidden = value !== "custom";
      if (value === "any") {
        delete when.hour_from;
        delete when.hour_to;
      } else if (value !== "custom") {
        const [from, to] = value.split("-").map(Number);
        when.hour_from = from;
        when.hour_to = to;
      } else {
        when.hour_from = clampInt($("cond-hour-from").value, 0, 23, 5);
        when.hour_to = clampInt($("cond-hour-to").value, 0, 23, 11);
      }
      bgChanged();
    });
    for (const [id, key] of [["cond-hour-from", "hour_from"], ["cond-hour-to", "hour_to"]]) {
      $(id).addEventListener("input", (event) => {
        when[key] = clampInt(event.target.value, 0, 23, 0);
        bgChanged();
      });
    }
    $("cond-weekday-preset").addEventListener("change", (event) => {
      const value = event.target.value;
      $("cond-weekdays").hidden = value !== "custom";
      if (value === "any") delete when.weekdays;
      else if (value === "workdays") when.weekdays = [1, 2, 3, 4, 5];
      else if (value === "weekend") when.weekdays = [6, 7];
      else {
        const checked = [...document.querySelectorAll("#cond-weekdays input:checked")].map((input) => Number(input.dataset.day));
        when.weekdays = checked.length ? checked : [1];
        document.querySelectorAll("#cond-weekdays input").forEach((input) => {
          input.checked = when.weekdays.includes(Number(input.dataset.day));
        });
      }
      bgChanged();
    });
    for (const input of document.querySelectorAll("#cond-weekdays input")) {
      input.addEventListener("change", () => {
        const days = [...document.querySelectorAll("#cond-weekdays input:checked")].map((element) => Number(element.dataset.day));
        if (days.length) when.weekdays = days;
        else delete when.weekdays;
        bgChanged();
      });
    }
    $("cond-streak-min").addEventListener("input", (event) => {
      const value = event.target.value;
      if (value === "") delete when.streak_min;
      else {
        when.streak_min = Math.max(0, Math.round(num(value, 0)));
        if (when.streak_max != null && when.streak_min > when.streak_max) {
          when.streak_max = when.streak_min;
          $("cond-streak-max").value = when.streak_max;
        }
      }
      bgChanged();
    });
    $("cond-streak-max").addEventListener("input", (event) => {
      const value = event.target.value;
      if (value === "") delete when.streak_max;
      else {
        when.streak_max = Math.max(0, Math.round(num(value, 0)));
        if (when.streak_min != null && when.streak_min > when.streak_max) {
          when.streak_min = when.streak_max;
          $("cond-streak-min").value = when.streak_min;
        }
      }
      bgChanged();
    });
    $("cond-completed").addEventListener("change", (event) => {
      const value = event.target.value;
      if (value === "any") delete when.completed_today;
      else when.completed_today = value === "yes";
      bgChanged();
    });
    for (const [id, key] of [["cond-league", "league"], ["cond-event", "event"]]) {
      $(id).addEventListener("input", (event) => {
        const value = event.target.value.trim();
        if (value) when[key] = value;
        else delete when[key];
        bgChanged();
      });
    }
    $("bg-fit").addEventListener("change", (event) => {
      bg.fit = event.target.value;
      requestDraw();
      scheduleSave();
    });
    for (const [id, key, minimum] of [
      ["bg-scale", "scale", 0.05],
      ["bg-offset-x", "offsetX", null],
      ["bg-offset-y", "offsetY", null],
    ]) {
      $(id).addEventListener("input", (event) => {
        let value = round(event.target.value);
        if (minimum != null) value = Math.max(minimum, value);
        bg[key] = value;
        requestDraw();
        scheduleSave();
      });
    }
  }

  function renderManualBgSelect() {
    const select = $("manual-bg-select");
    select.innerHTML = "";
    if (!state.template) {
      select.disabled = true;
      return;
    }
    for (const bg of state.template.backgrounds) {
      const option = document.createElement("option");
      option.value = bg.id;
      option.textContent = `${bg.name} · ${bg.id}`;
      select.append(option);
    }
    if (state.manualBgId) select.value = state.manualBgId;
    select.disabled = state.autoSelect;
  }

  function duplicateBackground(id) {
    const template = state.template;
    if (!template) return;
    const source = template.backgrounds.find((bg) => bg.id === id);
    if (!source) return;
    const base = `${source.id}-copy`;
    const newId = uniqueId(base, template.backgrounds.map((bg) => bg.id));
    const copy = JSON.parse(JSON.stringify(source));
    copy.id = newId;
    copy.name = `${source.name} 副本`;
    const index = template.backgrounds.indexOf(source);
    template.backgrounds.splice(index + 1, 0, copy);
    state.selectedBgId = newId;
    renderBackgroundList();
    renderBackgroundInspector();
    renderManualBgSelect();
    requestDraw();
    scheduleSave();
  }

  function deleteBackground(id) {
    const template = state.template;
    if (!template) return;
    if (template.backgrounds.length <= 1) {
      toast("至少保留一张底图，删除已拒绝。", "error");
      return;
    }
    const target = template.backgrounds.find((bg) => bg.id === id);
    if (!target) return;
    const fallbacks = template.backgrounds.filter((bg) => !Object.keys(bg.when || {}).length);
    if (!Object.keys(target.when || {}).length && fallbacks.length <= 1) {
      toast("这是唯一 fallback，删除已拒绝；请先给另一张底图设置条件或保留默认底图。", "error");
      return;
    }
    const index = template.backgrounds.indexOf(target);
    template.backgrounds.splice(index, 1);
    state.selectedBgId = (template.backgrounds[Math.max(0, index - 1)] || template.backgrounds[0]).id;
    if (state.manualBgId === id) state.manualBgId = state.selectedBgId;
    renderBackgroundList();
    renderBackgroundInspector();
    renderManualBgSelect();
    requestDraw();
    scheduleSave();
  }

  function moveBackground(id, direction) {
    const template = state.template;
    if (!template) return;
    const index = template.backgrounds.findIndex((bg) => bg.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= template.backgrounds.length) return;
    const [item] = template.backgrounds.splice(index, 1);
    template.backgrounds.splice(target, 0, item);
    renderBackgroundList();
    renderBackgroundInspector();
    renderManualBgSelect();
    requestDraw();
    scheduleSave();
  }

  function bindBackgroundActions() {
    const list = $("background-list");
    list.addEventListener("click", (event) => {
      const card = event.target.closest(".bg-card");
      if (!card) return;
      const id = card.dataset.bgId;
      const action = event.target.closest("[data-act]");
      if (!action) {
        selectBackground(id);
        return;
      }
      event.stopPropagation();
      const act = action.dataset.act;
      if (act === "up") moveBackground(id, -1);
      else if (act === "down") moveBackground(id, 1);
      else if (act === "copy") duplicateBackground(id);
      else if (act === "delete") deleteBackground(id);
    });
  }

  // -- selection -----------------------------------------------------
  function matchBackground(bg, context) {
    const when = bg.when || {};
    if (!Object.keys(when).length) return true;
    if (when.hour_from != null) {
      const hour = context.hour;
      const start = when.hour_from;
      const end = when.hour_to;
      const inside = start <= end ? hour >= start && hour < end : hour >= start || hour < end;
      if (!inside) return false;
    }
    if (Array.isArray(when.weekdays) && when.weekdays.length) {
      if (!when.weekdays.includes(context.weekday)) return false;
    }
    if (when.streak_min != null && context.streak < when.streak_min) return false;
    if (when.streak_max != null && context.streak > when.streak_max) return false;
    if (when.completed_today != null && context.completed_today !== when.completed_today) return false;
    if (when.league && context.league !== when.league) return false;
    if (when.event && context.event !== when.event) return false;
    return true;
  }

  function selectBackgroundForPreview() {
    const template = state.template;
    if (!template) return null;
    if (!state.autoSelect) {
      const manual = template.backgrounds.find((bg) => bg.id === state.manualBgId);
      return { bg: manual || template.backgrounds[0], fallback: false, manual: true };
    }
    const conditional = template.backgrounds
      .map((bg, index) => ({ bg, index }))
      .filter((item) => Object.keys(item.bg.when || {}).length)
      .sort((a, b) => (b.bg.priority - a.bg.priority) || (a.index - b.index));
    for (const item of conditional) {
      if (matchBackground(item.bg, state.preview)) {
        return { bg: item.bg, fallback: false, manual: false };
      }
    }
    const fallback = template.backgrounds.find((bg) => !Object.keys(bg.when || {}).length);
    return { bg: fallback || template.backgrounds[0], fallback: true, manual: false };
  }

  function updateMatchBadge() {
    const badge = $("bg-match-badge");
    const selected = selectBackgroundForPreview();
    if (!selected || !selected.bg) {
      badge.textContent = "没有可用底图";
      return;
    }
    if (!state.autoSelect) {
      badge.textContent = `手动 · ${selected.bg.id}`;
    } else if (selected.fallback) {
      badge.textContent = `自动 · 未命中，fallback · ${selected.bg.id}`;
    } else {
      badge.textContent = `自动 · 命中 · ${selected.bg.id}`;
    }
  }

  // -- canvas --------------------------------------------------------
  function requestDraw() {
    if (state.raf) return;
    state.raf = requestAnimationFrame(() => {
      state.raf = 0;
      draw();
    });
  }

  function roundRectPath(ctx, width, height, radius) {
    const r = Math.max(0, Math.min(radius, width / 2, height / 2));
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
      ctx.roundRect(0, 0, width, height, r);
      return;
    }
    ctx.moveTo(r, 0);
    ctx.lineTo(width - r, 0);
    ctx.quadraticCurveTo(width, 0, width, r);
    ctx.lineTo(width, height - r);
    ctx.quadraticCurveTo(width, height, width - r, height);
    ctx.lineTo(r, height);
    ctx.quadraticCurveTo(0, height, 0, height - r);
    ctx.lineTo(0, r);
    ctx.quadraticCurveTo(0, 0, r, 0);
    ctx.closePath();
  }

  function assetUrl(src) {
    if (!state.template) return "";
    if (String(src).startsWith("ghost:")) return `/${String(src).slice(6)}`;
    const encoded = String(src).split("/").map(encodeURIComponent).join("/");
    return `${API}/templates/${encodeURIComponent(state.template.id)}/assets/${encoded}`;
  }

  function imageEntry(url) {
    if (state.imageCache.has(url)) return state.imageCache.get(url);
    const entry = { image: null, failed: false };
    state.imageCache.set(url, entry);
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      entry.image = image;
      requestDraw();
    };
    image.onerror = () => {
      entry.failed = true;
      requestDraw();
    };
    image.src = url;
    return entry;
  }

  function replacePlaceholders(text) {
    return String(text || "").replace(/\{(streak|xp|rank|name)\}/g, (_, key) => {
      const value = state.preview[key];
      return value == null ? "" : String(value);
    });
  }

  function wrapCanvasText(ctx, text, maxWidth) {
    const lines = [];
    const flush = (current) => {
      const cleaned = current.replace(/\s+$/, "");
      lines.push({ text: cleaned, width: ctx.measureText(cleaned).width });
    };
    for (const paragraph of String(text).split("\n")) {
      if (!paragraph) {
        lines.push({ text: "", width: 0 });
        continue;
      }
      let current = "";
      const tokens = paragraph.match(/\s+|[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]|[^\s\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]+/g) || [];
      for (const token of tokens) {
        if (/^\s+$/.test(token)) {
          if (current && !current.endsWith(" ")) current += " ";
          continue;
        }
        let remaining = token;
        const chunks = [];
        while (remaining && ctx.measureText(remaining).width > maxWidth) {
          let cut = 1;
          while (cut < remaining.length && ctx.measureText(remaining.slice(0, cut + 1)).width <= maxWidth) cut += 1;
          chunks.push(remaining.slice(0, cut));
          remaining = remaining.slice(cut);
        }
        if (remaining) chunks.push(remaining);
        for (const chunk of chunks) {
          const candidate = current + chunk;
          if (current && ctx.measureText(candidate).width > maxWidth) {
            flush(current);
            current = chunk.replace(/^\s+/, "");
          } else {
            current = candidate;
          }
        }
      }
      if (current) flush(current);
      else if (!lines.length || lines[lines.length - 1].text !== "") lines.push({ text: "", width: 0 });
    }
    return lines;
  }

  function drawTextLayer(ctx, layer) {
    const width = Math.max(1, layer.w);
    const height = Math.max(1, layer.h);
    const size = Math.max(1, layer.fontSize);
    const weight = layer.fontWeight || 400;
    const font = `${weight} ${size}px "Noto Sans SC", "Noto Sans CJK SC", system-ui, sans-serif`;
    ctx.save();
    ctx.font = font;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const text = replacePlaceholders(layer.text);
    const lines = wrapCanvasText(ctx, text, width);
    const lineHeight = size * (layer.lineHeight || 1.2);
    const maxLines = Math.max(0, Math.floor(height / lineHeight));
    const visible = lines.slice(0, maxLines);
    ctx.beginPath();
    ctx.rect(layer.x, layer.y, width, height);
    ctx.clip();
    if (layer.shadow) {
      ctx.shadowColor = layer.shadow.color || "rgba(0,0,0,0.35)";
      ctx.shadowBlur = Math.max(0, layer.shadow.blur || 0);
      ctx.shadowOffsetX = layer.shadow.offsetX || 0;
      ctx.shadowOffsetY = layer.shadow.offsetY || 0;
    }
    ctx.fillStyle = layer.color || "#17324d";
    visible.forEach((line, index) => {
      if (!line.text) return;
      let left = layer.x;
      if (layer.align === "center") left += (width - line.width) / 2;
      else if (layer.align === "right") left += width - line.width;
      ctx.fillText(line.text, left, layer.y + index * lineHeight);
    });
    ctx.restore();
  }

  function drawImageLayer(ctx, layer) {
    const entry = imageEntry(assetUrl(layer.src));
    if (!entry.image) return;
    const image = entry.image;
    const ratio = Math.min(layer.w / image.width, layer.h / image.height);
    const width = image.width * ratio;
    const height = image.height * ratio;
    const x = layer.x + (layer.w - width) / 2;
    const y = layer.y + (layer.h - height) / 2;
    ctx.save();
    ctx.globalAlpha = Math.max(0, Math.min(1, layer.opacity ?? 1));
    ctx.drawImage(image, x, y, width, height);
    ctx.restore();
  }

  function drawSelection(ctx) {
    const layer = selectedLayer();
    if (!layer) return;
    ctx.save();
    ctx.strokeStyle = "#53d6bd";
    ctx.lineWidth = 4;
    ctx.setLineDash([12, 7]);
    ctx.strokeRect(layer.x, layer.y, layer.w, layer.h);
    ctx.setLineDash([]);
    ctx.fillStyle = "#53d6bd";
    ctx.fillRect(layer.x + layer.w - 9, layer.y + layer.h - 9, 18, 18);
    ctx.restore();
  }

  function draw() {
    if (state.raf) {
      cancelAnimationFrame(state.raf);
      state.raf = 0;
    }
    const canvas = $("studio-canvas");
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H);
    const template = state.template;
    if (!template) return;
    const canvasSpec = template.canvas || { width: CANVAS_W, height: CANVAS_H, radius: 128 };
    const width = canvasSpec.width || CANVAS_W;
    const height = canvasSpec.height || CANVAS_H;
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const rounded = template.canvas?.radius ?? 128;
    ctx.save();
    roundRectPath(ctx, width, height, rounded);
    ctx.clip();
    ctx.fillStyle = "#f2eadb";
    ctx.fillRect(0, 0, width, height);
    const selected = selectBackgroundForPreview();
    if (selected?.bg) {
      const entry = imageEntry(assetUrl(selected.bg.src));
      if (entry.image) {
        const image = entry.image;
        const scale = Math.max(0.01, selected.bg.scale || 1);
        const cover = Math.max(width / image.width, height / image.height);
        const contain = Math.min(width / image.width, height / image.height);
        const ratio = (selected.bg.fit === "contain" ? contain : cover) * scale;
        const drawWidth = image.width * ratio;
        const drawHeight = image.height * ratio;
        const x = (width - drawWidth) / 2 + (selected.bg.offsetX || 0);
        const y = (height - drawHeight) / 2 + (selected.bg.offsetY || 0);
        ctx.drawImage(image, x, y, drawWidth, drawHeight);
      }
    }
    for (const layer of template.layers) {
      if (layer.type === "text") drawTextLayer(ctx, layer);
      else if (layer.type === "image") drawImageLayer(ctx, layer);
    }
    ctx.restore();
    drawSelection(ctx);
    updateMatchBadge();
    updateProductionDisplay();
  }

  function updateProductionDisplay() {
    const input = $("production-url-inline");
    if (!input) return;
    const value = state.template ? productionUrl() : "";
    if (input.value !== value) input.value = value;
  }

  // -- pointer interaction ------------------------------------------
  function canvasPoint(event) {
    const canvas = $("studio-canvas");
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) * (canvas.width / rect.width),
      y: (event.clientY - rect.top) * (canvas.height / rect.height),
    };
  }

  function layerAt(point) {
    if (!state.template) return null;
    for (let index = state.template.layers.length - 1; index >= 0; index -= 1) {
      const layer = state.template.layers[index];
      if (
        point.x >= layer.x &&
        point.x <= layer.x + layer.w &&
        point.y >= layer.y &&
        point.y <= layer.y + layer.h
      ) {
        return layer;
      }
    }
    return null;
  }

  function bindCanvas() {
    const canvas = $("studio-canvas");
    canvas.addEventListener("pointerdown", (event) => {
      if (!state.template) return;
      const point = canvasPoint(event);
      let layer = selectedLayer();
      const handle = layer &&
        point.x >= layer.x + layer.w - 30 &&
        point.x <= layer.x + layer.w + 8 &&
        point.y >= layer.y + layer.h - 30 &&
        point.y <= layer.y + layer.h + 8;
      if (!handle) layer = layerAt(point);
      if (!layer) return;
      if (layer.id !== state.selectedLayerId) {
        state.selectedLayerId = layer.id;
        renderLayerList();
        renderLayerInspector();
      }
      state.drag = {
        mode: handle ? "resize" : "move",
        layer,
        startX: point.x,
        startY: point.y,
        origX: layer.x,
        origY: layer.y,
        origW: layer.w,
        origH: layer.h,
        changed: false,
      };
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add("is-dragging");
      event.preventDefault();
    });

    canvas.addEventListener("pointermove", (event) => {
      const drag = state.drag;
      if (!drag) return;
      const point = canvasPoint(event);
      const dx = point.x - drag.startX;
      const dy = point.y - drag.startY;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) return;
      drag.changed = true;
      if (drag.mode === "move") {
        drag.layer.x = Math.round(drag.origX + dx);
        drag.layer.y = Math.round(drag.origY + dy);
      } else {
        drag.layer.w = Math.max(16, Math.round(drag.origW + dx));
        drag.layer.h = Math.max(16, Math.round(drag.origH + dy));
      }
      syncLayerGeometryInputs();
      requestDraw();
      // Deliberately no request here: pointermove is local-only.
    });

    const finish = (event) => {
      const drag = state.drag;
      if (!drag) return;
      state.drag = null;
      canvas.classList.remove("is-dragging");
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (drag.changed) scheduleSave();
    };
    canvas.addEventListener("pointerup", finish);
    canvas.addEventListener("pointercancel", finish);
  }

  // -- preview controls ---------------------------------------------
  function readPreviewControls() {
    state.preview.hour = clampInt($("preview-hour").value, 0, 23, 0);
    state.preview.weekday = clampInt($("preview-weekday").value, 1, 7, 1);
    state.preview.completed_today = $("preview-completed").checked;
    state.preview.league = $("preview-league").value.trim();
    state.preview.event = $("preview-event").value.trim();
    state.preview.streak = clampInt($("preview-streak").value, 0, 1000000, 0);
    $("sample-streak").value = state.preview.streak;
    requestDraw();
  }

  function readSampleControls() {
    state.preview.streak = clampInt($("sample-streak").value, 0, 1000000, 0);
    state.preview.xp = clampInt($("sample-xp").value, 0, 100000000, 0);
    state.preview.rank = clampInt($("sample-rank").value, 0, 100000, 0);
    state.preview.name = $("sample-name").value;
    $("preview-streak").value = state.preview.streak;
    requestDraw();
  }

  function bindPreviewControls() {
    $("auto-select-toggle").addEventListener("change", (event) => {
      state.autoSelect = event.target.checked;
      $("manual-bg-select").disabled = state.autoSelect;
      updateMatchBadge();
      requestDraw();
    });
    $("manual-bg-select").addEventListener("change", (event) => {
      state.manualBgId = event.target.value;
      if (!state.autoSelect) {
        updateMatchBadge();
        requestDraw();
      }
    });
    for (const id of ["preview-hour", "preview-weekday", "preview-completed", "preview-league", "preview-event", "preview-streak"]) {
      $(id).addEventListener("input", readPreviewControls);
      $(id).addEventListener("change", readPreviewControls);
    }
    for (const id of ["sample-streak", "sample-xp", "sample-rank", "sample-name"]) {
      $(id).addEventListener("input", readSampleControls);
    }
  }

  // -- save / sync ---------------------------------------------------
  function scheduleSave() {
    if (!state.template) return;
    state.dirty = true;
    state.revision += 1;
    setStatus("正在同步…", "saving");
    clearPendingSave();
    state.saveTimer = setTimeout(() => {
      state.saveTimer = null;
      void saveNow();
    }, 400);
  }

  async function saveNow() {
    if (!state.template || state.saving || !state.dirty) return state.saving || null;
    const template = state.template;
    const snapshot = JSON.parse(JSON.stringify(template));
    const revision = state.revision;
    setStatus("正在同步…", "saving");
    state.saving = (async () => {
      try {
        const saved = await api(`/templates/${encodeURIComponent(snapshot.id)}`, {
          method: "PUT",
          body: snapshot,
        });
        if (state.template && state.template.id === snapshot.id) {
          state.template.updated_at = saved.updated_at;
        }
        if (state.revision === revision) {
          state.dirty = false;
          setStatus(`已同步到 data/widgets/${snapshot.id}`, "saved");
          const summary = state.templates.find((item) => item.id === snapshot.id);
          if (summary) {
            summary.name = snapshot.name;
            summary.updated_at = saved.updated_at;
            summary.background_count = snapshot.backgrounds.length;
            summary.layer_count = snapshot.layers.length;
            renderTemplateSelect();
          }
        }
      } catch (error) {
        if (error.status !== 401) {
          setStatus(`同步失败：${error.message}`, "error");
          toast(`同步失败：${error.message}`, "error");
        }
      } finally {
        state.saving = null;
        if (state.dirty && state.revision !== revision && !state.saveTimer) {
          state.saveTimer = setTimeout(() => {
            state.saveTimer = null;
            void saveNow();
          }, 400);
        }
      }
    })();
    return state.saving;
  }

  async function flushSave() {
    clearPendingSave();
    for (let attempt = 0; attempt < 4; attempt += 1) {
      if (state.saving) {
        await state.saving;
        continue;
      }
      if (!state.dirty) break;
      await saveNow();
    }
  }

  function installUnloadFlush() {
    window.addEventListener("pagehide", () => {
      if (!state.template || !state.dirty || !state.token) return;
      try {
        fetch(`${API}/templates/${encodeURIComponent(state.template.id)}`, {
          method: "PUT",
          headers: {
            Authorization: `Bearer ${state.token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify(state.template),
          keepalive: true,
          cache: "no-store",
        });
      } catch {
        /* best effort on unload */
      }
    });
  }

  // -- uploads -------------------------------------------------------
  async function uploadBackgroundFile(file) {
    if (!state.template) return;
    await flushSave();
    const stem = file.name.replace(/\.[^.]+$/, "");
    const base = `bg-${slugify(stem) || "upload"}`;
    const bgId = uniqueId(base, state.template.backgrounds.map((bg) => bg.id));
    const form = new FormData();
    form.append("file", file);
    form.append("bg_id", bgId);
    form.append("name", stem || bgId);
    setStatus("正在上传底图…", "saving");
    const result = await api(`/templates/${encodeURIComponent(state.template.id)}/assets/background`, {
      method: "POST",
      form,
    });
    clearPendingSave();
    state.dirty = false;
    state.revision += 1;
    state.template = result.template;
    state.selectedBgId = bgId;
    state.manualBgId = bgId;
    renderAll();
    setStatus(`已同步到 data/widgets/${state.template.id}`, "saved");
  }

  async function uploadFlameFile(file) {
    if (!state.template) return;
    await flushSave();
    const form = new FormData();
    form.append("file", file);
    setStatus("正在上传火焰…", "saving");
    const result = await api(`/templates/${encodeURIComponent(state.template.id)}/assets/flame`, {
      method: "POST",
      form,
    });
    clearPendingSave();
    state.dirty = false;
    state.revision += 1;
    state.template = result.template;
    const flame = state.template.layers.find((layer) => layer.role === "flame");
    if (flame) state.selectedLayerId = flame.id;
    renderAll();
    setStatus(`已同步到 data/widgets/${state.template.id}`, "saved");
  }

  function bindUploads() {
    $("add-bg-upload").addEventListener("click", () => $("bg-file-input").click());
    $("bg-file-input").addEventListener("change", async (event) => {
      const files = [...event.target.files];
      event.target.value = "";
      for (const file of files) {
        try {
          await uploadBackgroundFile(file);
          toast(`已添加底图 ${file.name}`, "ok");
        } catch (error) {
          if (error.status !== 401) toast(`上传失败：${error.message}`, "error");
        }
      }
    });
    $("flame-input").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      event.target.value = "";
      if (!file) return;
      try {
        await uploadFlameFile(file);
        toast("火焰已上传", "ok");
      } catch (error) {
        if (error.status !== 401) toast(`上传失败：${error.message}`, "error");
      }
    });
  }

  // -- Ghost library -------------------------------------------------
  async function openLibrary() {
    try {
      if (!state.library) state.library = await api("/library");
      const list = $("library-list");
      list.innerHTML = "";
      for (const item of state.library) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "library-item";
        button.dataset.src = item.src;
        button.dataset.label = item.label;
        button.innerHTML = `
          <img src="${esc(item.url)}" alt="${esc(item.label)}" loading="lazy">
          <strong>${esc(item.label)}</strong>
          <span>${esc(item.src)}</span>`;
        button.addEventListener("click", () => {
          addGhostBackground(item);
          closeModals();
        });
        list.append(button);
      }
      openModal("library-modal");
    } catch (error) {
      if (error.status !== 401) toast(`资源库加载失败：${error.message}`, "error");
    }
  }

  function addGhostBackground(item) {
    if (!state.template) return;
    const base = `bg-${slugify(item.id.replaceAll("/", "-")) || "ghost"}`;
    const id = uniqueId(base, state.template.backgrounds.map((bg) => bg.id));
    const hasFallback = state.template.backgrounds.some((bg) => !Object.keys(bg.when || {}).length);
    const label = item.label.split(" · ")[0] || id;
    state.template.backgrounds.push({
      id,
      name: label,
      src: item.src,
      when: {},
      priority: hasFallback ? 10 : 0,
      fit: "cover",
      offsetX: 0,
      offsetY: 0,
      scale: 1,
    });
    state.selectedBgId = id;
    state.manualBgId = id;
    renderAll();
    scheduleSave();
    toast("已添加 Ghost 资源底图（引用不复制）", "ok");
  }

  // -- template actions ---------------------------------------------
  function renderAll() {
    renderTemplateSelect();
    renderLayerList();
    renderLayerInspector();
    renderBackgroundList();
    renderBackgroundInspector();
    renderManualBgSelect();
    updateMatchBadge();
    requestDraw();
  }

  function openTemplateModal() {
    $("template-name-input").value = "";
    openModal("template-modal");
    setTimeout(() => $("template-name-input").focus(), 30);
  }

  async function createTemplateFromModal() {
    const name = $("template-name-input").value.trim();
    if (!name) {
      toast("请输入模版名称", "error");
      return;
    }
    const button = $("template-modal-confirm");
    button.disabled = true;
    try {
      const template = await api("/templates", { method: "POST", body: { name } });
      closeModals();
      await loadTemplates();
      await openTemplate(template.id);
      toast(`已新建 ${template.name}`, "ok");
    } catch (error) {
      if (error.status !== 401) toast(`新建失败：${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function fetchAssetBlob(src) {
    const response = await fetch(assetUrl(src), { cache: "no-store" });
    if (!response.ok) throw new ApiError(response.status, "资源读取失败");
    return response.blob();
  }

  async function duplicateTemplate() {
    if (!state.template) return;
    await flushSave();
    const source = state.template;
    const button = $("duplicate-template-btn");
    button.disabled = true;
    setStatus("正在复制模版…", "saving");
    let created = null;
    try {
      created = await api("/templates", { method: "POST", body: { name: `${source.name} 副本` } });
      for (const bg of source.backgrounds) {
        if (String(bg.src).startsWith("ghost:")) continue;
        const blob = await fetchAssetBlob(bg.src);
        const form = new FormData();
        form.append("file", blob, bg.src.split("/").pop() || `${bg.id}.png`);
        form.append("bg_id", bg.id);
        form.append("name", bg.name);
        await api(`/templates/${encodeURIComponent(created.id)}/assets/background`, { method: "POST", form });
      }
      for (const layer of source.layers) {
        if (layer.type !== "image" || String(layer.src).startsWith("ghost:")) continue;
        const blob = await fetchAssetBlob(layer.src);
        const form = new FormData();
        form.append("file", blob, layer.src.split("/").pop() || "flame.png");
        await api(`/templates/${encodeURIComponent(created.id)}/assets/flame`, { method: "POST", form });
      }
      const copy = JSON.parse(JSON.stringify(source));
      copy.id = created.id;
      copy.render_token = created.render_token;
      copy.updated_at = new Date().toISOString();
      await api(`/templates/${encodeURIComponent(created.id)}`, { method: "PUT", body: copy });
      await loadTemplates();
      await openTemplate(created.id);
      toast("已复制模版", "ok");
    } catch (error) {
      if (error.status !== 401) toast(`复制失败：${error.message}`, "error");
      if (created) {
        try {
          await api(`/templates/${encodeURIComponent(created.id)}`, { method: "DELETE" });
        } catch {
          /* ignore cleanup failure */
        }
      }
      setStatus(`复制失败：${error.message}`, "error");
    } finally {
      button.disabled = false;
    }
  }

  async function deleteTemplate() {
    if (!state.template) return;
    const id = state.template.id;
    if (!window.confirm(`删除模版 ${id}？目录 data/widgets/${id}/ 会被删除。`)) return;
    try {
      await api(`/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadTemplates();
      if (state.templates.length) {
        await openTemplate(state.templates[0].id);
      } else {
        state.template = null;
        state.selectedLayerId = null;
        state.selectedBgId = null;
        renderAll();
        setStatus("等待新建模版");
        openTemplateModal();
      }
      toast("模版已删除", "ok");
    } catch (error) {
      if (error.status !== 401) toast(`删除失败：${error.message}`, "error");
    }
  }

  function templateChanged() {
    const id = $("template-select").value;
    if (!id || id === state.template?.id) return;
    openTemplate(id).catch((error) => {
      if (error.status !== 401) toast(`切换失败：${error.message}`, "error");
    });
  }

  // -- production URL ------------------------------------------------
  function productionParams(includeManual) {
    const params = new URLSearchParams();
    params.set("token", state.template?.render_token || "");
    params.set("streak", String(state.preview.streak));
    params.set("xp", String(state.preview.xp));
    params.set("rank", String(state.preview.rank));
    params.set("name", state.preview.name || "");
    params.set("hour", String(state.preview.hour));
    params.set("weekday", String(state.preview.weekday));
    params.set("completed", state.preview.completed_today ? "1" : "0");
    if (state.preview.league) params.set("league", state.preview.league);
    if (state.preview.event) params.set("event", state.preview.event);
    if (includeManual && !state.autoSelect && state.manualBgId) params.set("bg", state.manualBgId);
    return params;
  }

  function productionUrl() {
    if (!state.template) return "";
    return `${window.location.origin}/v1/widgets/${encodeURIComponent(state.template.id)}.png?${productionParams(true).toString()}`;
  }

  async function copyText(text, successMessage) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const input = document.createElement("textarea");
        input.value = text;
        input.style.position = "fixed";
        input.style.opacity = "0";
        document.body.append(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      }
      toast(successMessage || "已复制", "ok");
    } catch {
      toast("复制失败，请手动选择 URL", "error");
    }
  }

  async function copyProductionUrl() {
    if (!state.template) return;
    await copyText(productionUrl(), "生产 URL 已复制");
  }

  async function showProductionPreview() {
    if (!state.template) return;
    await flushSave();
    if (state.dirty) {
      toast("生产预览前保存失败，请先修正同步错误。", "error");
      return;
    }
    const url = productionUrl();
    $("preview-error").textContent = "";
    $("production-url").value = url;
    $("preview-open-link").href = url;
    const image = $("production-image");
    image.onerror = () => {
      $("preview-error").textContent = "生产图加载失败，请检查 render_token 与保存状态。";
    };
    image.onload = () => {
      $("preview-error").textContent = "";
    };
    image.src = url;
    openModal("preview-modal");
  }

  // -- modals --------------------------------------------------------
  function openModal(id) {
    $("modal-backdrop").hidden = false;
    for (const modalId of ["template-modal", "library-modal", "preview-modal"]) {
      $(modalId).hidden = modalId !== id;
    }
  }

  function closeModals() {
    $("modal-backdrop").hidden = true;
    for (const modalId of ["template-modal", "library-modal", "preview-modal"]) {
      $(modalId).hidden = true;
    }
  }

  function bindModals() {
    $("modal-backdrop").addEventListener("click", (event) => {
      if (event.target === $("modal-backdrop")) closeModals();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeModals();
    });
    $("template-modal-cancel").addEventListener("click", closeModals);
    $("template-modal-confirm").addEventListener("click", createTemplateFromModal);
    $("template-name-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        void createTemplateFromModal();
      }
    });
    $("library-close").addEventListener("click", closeModals);
    $("preview-close").addEventListener("click", closeModals);
    $("preview-copy-btn").addEventListener("click", () => copyText($("production-url").value, "生产 URL 已复制"));
  }

  // -- wiring --------------------------------------------------------
  function bindTopbar() {
    $("template-select").addEventListener("change", templateChanged);
    $("new-template-btn").addEventListener("click", openTemplateModal);
    $("duplicate-template-btn").addEventListener("click", () => void duplicateTemplate());
    $("delete-template-btn").addEventListener("click", () => void deleteTemplate());
    $("copy-production-url").addEventListener("click", () => void copyProductionUrl());
    $("copy-production-inline").addEventListener("click", () => void copyProductionUrl());
    $("library-open").addEventListener("click", () => void openLibrary());
    $("add-text-layer").addEventListener("click", addTextLayer);
    $("production-preview-btn").addEventListener("click", () => void showProductionPreview());
  }

  function bindAuth() {
    $("token-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const token = $("token-input").value.trim();
      if (!token) {
        $("auth-error").textContent = "请粘贴 Ghost 令牌。";
        return;
      }
      state.token = token;
      try {
        localStorage.setItem(TOKEN_KEY, token);
      } catch {
        /* ignore storage failure */
      }
      $("token-input").value = "";
      $("auth-error").textContent = "";
      await boot();
    });
  }

  function start() {
    bindAuth();
    bindTopbar();
    bindModals();
    bindCanvas();
    bindBackgroundActions();
    bindUploads();
    bindPreviewControls();
    installUnloadFlush();
    readPreviewControls();
    try {
      state.token = localStorage.getItem(TOKEN_KEY) || "";
    } catch {
      state.token = "";
    }
    if (!state.token) {
      $("auth-gate").hidden = false;
      $("studio-shell").hidden = true;
      setStatus("需要 Ghost 令牌");
      setTimeout(() => $("token-input").focus(), 40);
      return;
    }
    void boot();
  }

  document.addEventListener("DOMContentLoaded", start);
})();
