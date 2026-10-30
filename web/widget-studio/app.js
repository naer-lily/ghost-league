(() => {
  "use strict";

  const TOKEN_KEY = "gl.token.v1";
  const LAST_TEMPLATE_KEY = "gl.widget-studio.last-template.v1";
  const API = "/v1/widget-studio";
  const CANVAS_W = 1536;
  const CANVAS_H = 914;
  const MIN_VISIBLE = 40;
  const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
  const KIND_LABELS = { text: "文字", streak: "连胜数字", flame: "火焰" };

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
    userId: "",
    templates: [],
    template: null,
    selectedBgId: null,
    selectedTextId: null,
    selection: { kind: "text" },
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
    saveError: "",
    drag: null,
    raf: 0,
    imageCache: new Map(),
    persistedBgIds: new Set(),
    toastTimer: null,
    previewObjectUrl: null,
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

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function defaultLayout() {
    return {
      texts: [{ id: "text-1", text: "连续学习", x: 760, y: 540 }],
      streak: { x: 760, y: 300 },
      flame: { x: 660, y: 280 },
    };
  }

  // -- explicit save state -------------------------------------------
  function setSaveState() {
    const button = $("save-template-btn");
    const canSave = Boolean(state.template && state.dirty && !state.saving);
    button.disabled = !canSave;
    button.classList.toggle("is-dirty", canSave);
    if (!state.template) {
      setStatus("未加载");
      return;
    }
    if (state.saving) {
      setStatus("保存中…", "saving");
    } else if (state.saveError) {
      setStatus(`保存失败：${state.saveError}`, "error");
    } else if (state.dirty) {
      setStatus("未保存", "dirty");
    } else {
      setStatus(`已保存 · data/widgets/${state.template.id}`, "saved");
    }
  }

  function markDirty() {
    if (!state.template) return;
    state.dirty = true;
    state.saveError = "";
    state.revision += 1;
    setSaveState();
  }

  function confirmDiscard() {
    if (!state.dirty) return true;
    return window.confirm("有未保存的改动，继续会丢弃这些改动。确定继续？");
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

  async function fetchCurrentUser() {
    const headers = state.token ? { Authorization: `Bearer ${state.token}` } : {};
    const response = await fetch("/v1/me/profile", {
      headers,
      cache: "no-store",
    });
    if (!response.ok) {
      if (response.status === 401) {
        requireLogin("令牌无效或已过期，请重新粘贴 Ghost 令牌。");
      }
      throw new ApiError(response.status, "无法读取当前用户");
    }
    const profile = await response.json();
    const userId = String(profile?.user_id || "");
    if (!userId) throw new ApiError(500, "当前用户缺少 user_id");
    state.userId = userId;
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

  // -- explicit save -------------------------------------------------
  async function saveNow() {
    if (!state.template || state.saving || !state.dirty) return;
    const snapshot = clone(state.template);
    const revision = state.revision;
    state.saveError = "";
    state.saving = (async () => {
      try {
        const saved = await api(`/templates/${encodeURIComponent(snapshot.id)}`, {
          method: "PUT",
          body: snapshot,
        });
        if (state.template && state.template.id === snapshot.id) {
          state.template.updated_at = saved.updated_at;
        }
        if (state.template && state.template.id === snapshot.id) {
          state.persistedBgIds = new Set(snapshot.backgrounds.map((bg) => bg.id));
          renderBackgroundList();
        }
        if (state.revision === revision) {
          state.dirty = false;
        }
        const summary = state.templates.find((item) => item.id === snapshot.id);
        if (summary) {
          summary.name = snapshot.name;
          summary.updated_at = saved.updated_at;
          summary.background_count = snapshot.backgrounds.length;
          summary.text_count = snapshot.backgrounds.reduce(
            (total, bg) => total + (bg.layout?.texts?.length || 0),
            0
          );
          renderTemplateSelect();
        }
        if (state.revision === revision) toast("已保存", "ok");
      } catch (error) {
        state.saveError = error.message;
        state.dirty = true;
        if (error.status !== 401) toast(`保存失败：${error.message}`, "error");
      } finally {
        state.saving = null;
        setSaveState();
      }
    })();
    setSaveState();
    await state.saving;
  }

  // -- boot ----------------------------------------------------------
  async function boot() {
    $("auth-gate").hidden = true;
    $("studio-shell").hidden = false;
    setStatus("正在加载…", "saving");
    try {
      await fetchCurrentUser();
      const templates = await api("/templates");
      state.templates = Array.isArray(templates) ? templates : [];
      renderTemplateSelect();
      if (!state.templates.length) {
        state.template = null;
        state.selectedBgId = null;
        state.selectedTextId = null;
        state.dirty = false;
        renderAll();
        setSaveState();
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

  function selectBackgroundInternal(id) {
    const template = state.template;
    if (!template) return;
    const background = template.backgrounds.find((bg) => bg.id === id) || template.backgrounds[0];
    state.selectedBgId = background ? background.id : null;
    state.selectedTextId = background?.layout?.texts?.[0]?.id || null;
    state.selection = { kind: "text" };
    renderBackgroundList();
    renderBackgroundInspector();
    renderLayoutPanel();
    renderManualBgSelect();
    updateMatchBadge();
    requestDraw();
  }

  async function openTemplate(id) {
    const template = await api(`/templates/${encodeURIComponent(id)}`);
    state.template = template;
    state.imageCache.clear();
    state.persistedBgIds = new Set(template.backgrounds.map((bg) => bg.id));
    state.dirty = false;
    state.saving = null;
    state.saveError = "";
    state.revision = 0;
    state.drag = null;
    const fallback = template.backgrounds.find((bg) => !Object.keys(bg.when || {}).length);
    state.manualBgId = (fallback || template.backgrounds[0])?.id || null;
    let targetBg = state.manualBgId;
    if (state.autoSelect) {
      const selected = selectBackgroundForPreview();
      if (selected?.bg) targetBg = selected.bg.id;
    }
    storeLastTemplate(template.id);
    selectBackgroundInternal(targetBg);
    renderTemplateSelect();
    updateProductionDisplay();
    setSaveState();
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
      return;
    }
    select.disabled = false;
    $("duplicate-template-btn").disabled = false;
    $("delete-template-btn").disabled = false;
    for (const template of state.templates) {
      const option = document.createElement("option");
      option.value = template.id;
      option.textContent = `${template.name} (${template.id})`;
      select.append(option);
    }
    if (state.template) select.value = state.template.id;
  }

  // -- layout helpers ------------------------------------------------
  function selectedBg() {
    if (!state.template) return null;
    return state.template.backgrounds.find((bg) => bg.id === state.selectedBgId) || null;
  }

  function layoutOf(background) {
    return background?.layout || null;
  }

  function selectedText() {
    const background = selectedBg();
    if (!background) return null;
    return background.layout.texts.find((item) => item.id === state.selectedTextId) || null;
  }

  function styleFor(kind) {
    const styles = state.template?.styles;
    if (!styles) return null;
    if (kind === "text") return styles.label;
    if (kind === "streak") return styles.streak;
    return styles.flame;
  }

  function positionFor(kind) {
    const background = selectedBg();
    if (!background) return null;
    if (kind === "text") return selectedText();
    return layoutOf(background)?.[kind] || null;
  }

  function positionBox(kind) {
    const style = styleFor(kind);
    const position = positionFor(kind);
    if (!style || !position) return null;
    return {
      x: num(position.x),
      y: num(position.y),
      width: Math.max(1, num(style.width, 1)),
      height: Math.max(1, num(style.height, 1)),
    };
  }

  function canvasSize() {
    return {
      width: num(state.template?.canvas?.width, CANVAS_W),
      height: num(state.template?.canvas?.height, CANVAS_H),
    };
  }

  function clampPosition(kind, x, y) {
    const box = positionBox(kind);
    const canvas = canvasSize();
    const width = box?.width || 1;
    const height = box?.height || 1;
    return {
      x: Math.round(Math.max(MIN_VISIBLE - width, Math.min(canvas.width - MIN_VISIBLE, x))),
      y: Math.round(Math.max(MIN_VISIBLE - height, Math.min(canvas.height - MIN_VISIBLE, y))),
    };
  }

  function setPosition(kind, x, y) {
    const target = positionFor(kind);
    if (!target) return;
    const clamped = clampPosition(kind, x, y);
    target.x = clamped.x;
    target.y = clamped.y;
  }

  // -- text variants -------------------------------------------------
  function textSummary(value) {
    const cleaned = String(value || "").replace(/\s+/g, " ").trim();
    return cleaned ? cleaned.slice(0, 22) : "（空文字）";
  }

  function renderLayoutPanel() {
    const inspector = $("layout-inspector");
    const kind = $("layout-kind");
    const background = selectedBg();
    if (!background) {
      kind.textContent = "未选择";
      inspector.innerHTML = '<p class="empty">在左侧选择一张底图后编辑文字变体与摆位。</p>';
      return;
    }
    const texts = layoutOf(background).texts;
    if (!texts.some((item) => item.id === state.selectedTextId)) {
      state.selectedTextId = texts[0]?.id || null;
    }
    const text = selectedText();
    const streak = background.layout.streak;
    const flame = background.layout.flame;
    kind.textContent = `${KIND_LABELS[state.selection.kind] || "文字"} · ${background.id}`;
    const style = state.template.styles.label;
    const items = texts
      .map(
        (item) => `
        <li class="text-item${item.id === state.selectedTextId ? " is-selected" : ""}" data-text-id="${esc(item.id)}">
          <button type="button" class="text-select" data-act="select">
            <strong>${esc(textSummary(item.text))}</strong>
            <small>x ${esc(round(item.x))} · y ${esc(round(item.y))}</small>
          </button>
          ${texts.length > 1 ? '<button type="button" class="text-delete" data-act="delete" title="删除文字变体" aria-label="删除文字变体">×</button>' : ""}
        </li>`
      )
      .join("");
    inspector.innerHTML = `
      <div class="section-row">
        <h3>文字变体</h3>
        <button id="add-text-variant" class="btn btn-small" type="button">新增</button>
      </div>
      <ul id="text-variant-list" class="text-list" aria-label="文字变体列表">${items}</ul>
      ${text ? `
      <label class="field"><span>文字内容（只改文字，不改样式）</span>
        <textarea id="text-content" maxlength="500">${esc(text.text)}</textarea>
      </label>
      <div class="field-grid">
        <label class="field"><span>文字 X</span><input id="text-x" type="number" step="1" value="${esc(round(text.x))}"></label>
        <label class="field"><span>文字 Y</span><input id="text-y" type="number" step="1" value="${esc(round(text.y))}"></label>
      </div>` : '<p class="empty">该底图还没有文字变体。</p>'}
      <div class="divider"></div>
      <h3>连胜数字位置</h3>
      <div class="field-grid">
        <label class="field"><span>数字 X</span><input id="streak-x" type="number" step="1" value="${esc(round(streak.x))}"></label>
        <label class="field"><span>数字 Y</span><input id="streak-y" type="number" step="1" value="${esc(round(streak.y))}"></label>
      </div>
      <h3>火焰位置</h3>
      <div class="field-grid">
        <label class="field"><span>火焰 X</span><input id="flame-x" type="number" step="1" value="${esc(round(flame.x))}"></label>
        <label class="field"><span>火焰 Y</span><input id="flame-y" type="number" step="1" value="${esc(round(flame.y))}"></label>
      </div>
      <p class="style-readonly">
        样式全局统一（只读）：字号 ${esc(style.fontSize)} · 字重 ${esc(style.fontWeight)} ·
        颜色 ${esc(style.color)} · 行高 ${esc(style.lineHeight)} · 对齐 ${esc(style.align)} ·
        文字盒 ${esc(style.width)}×${esc(style.height)}
      </p>
      <p class="hint">拖动或方向键只改 x/y：1px，Shift+方向键 10px；拖动时按住 Shift 吸附 8px 网格。</p>`;
    bindLayoutPanel();
  }

  function bindLayoutPanel() {
    $("add-text-variant")?.addEventListener("click", addTextVariant);
    $("text-variant-list")?.addEventListener("click", (event) => {
      const item = event.target.closest(".text-item");
      if (!item) return;
      const action = event.target.closest("[data-act]");
      const textId = item.dataset.textId;
      if (action?.dataset.act === "delete") {
        deleteTextVariant(textId);
      } else {
        selectTextVariant(textId);
      }
    });
    $("text-content")?.addEventListener("input", (event) => {
      const text = selectedText();
      if (!text) return;
      text.text = event.target.value;
      const item = document.querySelector(`.text-item[data-text-id="${CSS.escape(text.id)}"] strong`);
      if (item) item.textContent = textSummary(text.text);
      markDirty();
      requestDraw();
    });
    for (const [kind, id] of [["text", "text-x"], ["text", "text-y"]]) {
      $(id)?.addEventListener("input", (event) => {
        const text = selectedText();
        if (!text) return;
        const key = id.endsWith("x") ? "x" : "y";
        const next = setPosition("text", key === "x" ? num(event.target.value) : text.x, key === "y" ? num(event.target.value) : text.y);
        text[key] = next[key];
        markDirty();
        requestDraw();
      });
    }
    bindPositionInput("streak", "streak-x", "streak-y");
    bindPositionInput("flame", "flame-x", "flame-y");
  }

  function bindPositionInput(kind, xId, yId) {
    for (const id of [xId, yId]) {
      $(id)?.addEventListener("input", (event) => {
        const target = positionFor(kind);
        if (!target) return;
        const next = setPosition(
          kind,
          id === xId ? num(event.target.value) : target.x,
          id === yId ? num(event.target.value) : target.y
        );
        target.x = next.x;
        target.y = next.y;
        markDirty();
        requestDraw();
      });
    }
  }

  function selectTextVariant(id) {
    if (!selectedBg()) return;
    state.selectedTextId = id;
    state.selection = { kind: "text" };
    renderLayoutPanel();
    requestDraw();
  }

  function addTextVariant() {
    const background = selectedBg();
    if (!background) return;
    const texts = background.layout.texts;
    const current = selectedText() || texts[0];
    const ids = new Set(texts.map((item) => item.id));
    let suffix = texts.length + 1;
    let id = `text-${suffix}`;
    while (ids.has(id)) {
      suffix += 1;
      id = `text-${suffix}`;
    }
    texts.push({
      id,
      text: current?.text || "新文字",
      x: round(current?.x ?? 760),
      y: round(current?.y ?? 540),
    });
    state.selectedTextId = id;
    state.selection = { kind: "text" };
    markDirty();
    renderLayoutPanel();
    requestDraw();
    toast("已新增文字变体（未保存）", "ok");
  }

  function deleteTextVariant(id) {
    const background = selectedBg();
    if (!background) return;
    const texts = background.layout.texts;
    if (texts.length <= 1) {
      toast("每张底图至少保留一条文字变体。", "error");
      return;
    }
    const index = texts.findIndex((item) => item.id === id);
    if (index < 0) return;
    texts.splice(index, 1);
    state.selectedTextId = (texts[Math.max(0, index - 1)] || texts[0]).id;
    state.selection = { kind: "text" };
    markDirty();
    renderLayoutPanel();
    requestDraw();
  }

  function syncLayoutInputs() {
    const text = selectedText();
    if (text) {
      const x = $("text-x");
      const y = $("text-y");
      if (x && document.activeElement !== x) x.value = round(text.x);
      if (y && document.activeElement !== y) y.value = round(text.y);
    }
    for (const [kind, xId, yId] of [
      ["streak", "streak-x", "streak-y"],
      ["flame", "flame-x", "flame-y"],
    ]) {
      const target = positionFor(kind);
      if (!target) continue;
      const x = $(xId);
      const y = $(yId);
      if (x && document.activeElement !== x) x.value = round(target.x);
      if (y && document.activeElement !== y) y.value = round(target.y);
    }
  }

  // -- backgrounds ---------------------------------------------------
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
      const thumbSrc = state.persistedBgIds.has(bg.id) ? thumb : assetUrl(bg.src);
      item.innerHTML = `
        <div class="bg-card-head" data-role="select-bg">
          <img class="bg-thumb" src="${esc(thumbSrc)}" alt="${esc(bg.name)} 底图缩略图" loading="lazy">
          <div class="bg-meta">
            <strong>${esc(bg.name)}</strong>
            <span class="bg-summary">${esc(conditionSummary(bg.when))}</span>
            <span class="bg-tags">
              <span class="tag is-priority">P${esc(bg.priority)}</span>
              <span class="tag">文字 ${esc(bg.layout?.texts?.length || 0)}</span>
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
    if (!state.autoSelect) state.manualBgId = id;
    if (id === state.selectedBgId) {
      renderManualBgSelect();
      updateMatchBadge();
      requestDraw();
      return;
    }
    selectBackgroundInternal(id);
  }

  function bgChanged() {
    if (!state.template) return;
    markDirty();
    renderBackgroundList();
    renderManualBgSelect();
    refreshConditionSummary();
    updateMatchBadge();
    requestDraw();
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
      markDirty();
    });
    $("bg-priority").addEventListener("input", (event) => {
      bg.priority = Math.round(num(event.target.value, 0));
      renderBackgroundList();
      markDirty();
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
      markDirty();
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
        markDirty();
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
    const copy = clone(source);
    copy.id = newId;
    copy.name = `${source.name} 副本`;
    const index = template.backgrounds.indexOf(source);
    template.backgrounds.splice(index + 1, 0, copy);
    markDirty();
    selectBackgroundInternal(newId);
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
    const next = (template.backgrounds[Math.max(0, index - 1)] || template.backgrounds[0]).id;
    if (state.manualBgId === id) state.manualBgId = next;
    markDirty();
    selectBackgroundInternal(next);
  }

  function moveBackground(id, direction) {
    const template = state.template;
    if (!template) return;
    const index = template.backgrounds.findIndex((bg) => bg.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= template.backgrounds.length) return;
    const [item] = template.backgrounds.splice(index, 1);
    template.backgrounds.splice(target, 0, item);
    markDirty();
    renderBackgroundList();
    renderBackgroundInspector();
    renderManualBgSelect();
    requestDraw();
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

  // -- preview selection --------------------------------------------
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

  function syncSelectionFromPreview() {
    if (!state.template || !state.autoSelect) return;
    const selected = selectBackgroundForPreview();
    if (selected?.bg && selected.bg.id !== state.selectedBgId) {
      selectBackgroundInternal(selected.bg.id);
    }
  }

  function updateMatchBadge() {
    const badge = $("bg-match-badge");
    const selected = selectBackgroundForPreview();
    const current = selectedBg();
    if (!selected || !selected.bg) {
      badge.textContent = "没有可用底图";
      return;
    }
    if (!state.autoSelect) {
      badge.textContent = `手动 · ${selected.bg.id}`;
    } else if (current && current.id !== selected.bg.id) {
      badge.textContent = `编辑中 · ${current.id} · 自动命中 ${selected.bg.id}`;
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

  function drawTextBox(ctx, style, text, x, y) {
    const width = Math.max(1, num(style.width, 1));
    const height = Math.max(1, num(style.height, 1));
    const size = Math.max(1, num(style.fontSize, 48));
    const weight = style.fontWeight || 400;
    const font = `${weight} ${size}px "Noto Sans SC", "Noto Sans CJK SC", system-ui, sans-serif`;
    ctx.save();
    ctx.font = font;
    ctx.textBaseline = "top";
    ctx.textAlign = "left";
    const lines = wrapCanvasText(ctx, replacePlaceholders(text), width);
    const lineHeight = size * (style.lineHeight || 1.2);
    const maxLines = Math.max(0, Math.floor(height / lineHeight));
    const visible = lines.slice(0, maxLines);
    ctx.beginPath();
    ctx.rect(x, y, width, height);
    ctx.clip();
    if (style.shadow) {
      ctx.shadowColor = style.shadow.color || "rgba(0,0,0,0.35)";
      ctx.shadowBlur = Math.max(0, style.shadow.blur || 0);
      ctx.shadowOffsetX = style.shadow.offsetX || 0;
      ctx.shadowOffsetY = style.shadow.offsetY || 0;
    }
    ctx.fillStyle = style.color || "#17324d";
    visible.forEach((line, index) => {
      if (!line.text) return;
      let left = x;
      if (style.align === "center") left += (width - line.width) / 2;
      else if (style.align === "right") left += width - line.width;
      ctx.fillText(line.text, left, y + index * lineHeight);
    });
    ctx.restore();
  }

  function drawFlame(ctx, style, position) {
    const width = Math.max(1, num(style.width, 1));
    const height = Math.max(1, num(style.height, 1));
    const entry = imageEntry(assetUrl("flame.png"));
    if (entry.image) {
      const image = entry.image;
      const ratio = Math.min(width / image.width, height / image.height);
      const drawWidth = image.width * ratio;
      const drawHeight = image.height * ratio;
      ctx.save();
      ctx.globalAlpha = Math.max(0, Math.min(1, style.opacity ?? 1));
      ctx.drawImage(
        image,
        position.x + (width - drawWidth) / 2,
        position.y + (height - drawHeight) / 2,
        drawWidth,
        drawHeight
      );
      ctx.restore();
      return;
    }
    ctx.save();
    ctx.strokeStyle = "rgba(255, 176, 32, 0.9)";
    ctx.setLineDash([8, 5]);
    ctx.lineWidth = 2;
    ctx.strokeRect(position.x + 1, position.y + 1, width - 2, height - 2);
    ctx.setLineDash([]);
    ctx.fillStyle = "rgba(255, 176, 32, 0.85)";
    ctx.font = '600 20px "Noto Sans SC", system-ui, sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("火焰", position.x + width / 2, position.y + height / 2);
    ctx.restore();
  }

  function drawSelection(ctx) {
    const box = positionBox(state.selection.kind);
    if (!box) return;
    ctx.save();
    ctx.strokeStyle = "#53d6bd";
    ctx.lineWidth = 4;
    ctx.setLineDash([12, 7]);
    ctx.strokeRect(box.x, box.y, box.width, box.height);
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
    const background = selectedBg();
    ctx.save();
    roundRectPath(ctx, width, height, rounded);
    ctx.clip();
    ctx.fillStyle = "#f2eadb";
    ctx.fillRect(0, 0, width, height);
    if (background) {
      const entry = imageEntry(assetUrl(background.src));
      if (entry.image) {
        const image = entry.image;
        const scale = Math.max(0.01, background.scale || 1);
        const cover = Math.max(width / image.width, height / image.height);
        const contain = Math.min(width / image.width, height / image.height);
        const ratio = (background.fit === "contain" ? contain : cover) * scale;
        const drawWidth = image.width * ratio;
        const drawHeight = image.height * ratio;
        const x = (width - drawWidth) / 2 + (background.offsetX || 0);
        const y = (height - drawHeight) / 2 + (background.offsetY || 0);
        ctx.drawImage(image, x, y, drawWidth, drawHeight);
      }
      const text = selectedText();
      if (text) drawTextBox(ctx, template.styles.label, text.text, text.x, text.y);
      drawTextBox(ctx, template.styles.streak, "{streak}", background.layout.streak.x, background.layout.streak.y);
      drawFlame(ctx, template.styles.flame, background.layout.flame);
    }
    ctx.restore();
    drawSelection(ctx);
    updateMatchBadge();
    updateProductionDisplay();
  }

  function updateProductionDisplay() {
    const value = state.template ? productionUrl() : "";
    for (const id of ["production-url-inline", "widget-fixed-url"]) {
      const input = $(id);
      if (input && input.value !== value) input.value = value;
    }
    const userId = $("widget-user-id");
    if (userId) userId.textContent = state.userId || "未登录";
    const templateId = $("widget-template-id");
    if (templateId) templateId.textContent = state.template?.id || "未选择";
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

  function elementAt(point) {
    for (const kind of ["flame", "streak", "text"]) {
      const box = positionBox(kind);
      if (!box) continue;
      if (
        point.x >= box.x &&
        point.x <= box.x + box.width &&
        point.y >= box.y &&
        point.y <= box.y + box.height
      ) {
        return kind;
      }
    }
    return null;
  }

  function bindCanvas() {
    const canvas = $("studio-canvas");
    canvas.addEventListener("pointerdown", (event) => {
      if (!state.template || !selectedBg()) return;
      const point = canvasPoint(event);
      const kind = elementAt(point);
      if (!kind) return;
      state.selection = { kind };
      if (kind === "text" && selectedText()) state.selectedTextId = selectedText().id;
      const box = positionBox(kind);
      state.drag = {
        kind,
        startX: point.x,
        startY: point.y,
        origX: box.x,
        origY: box.y,
        changed: false,
      };
      renderLayoutPanel();
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
      let x = drag.origX + dx;
      let y = drag.origY + dy;
      if (event.shiftKey) {
        x = Math.round(x / 8) * 8;
        y = Math.round(y / 8) * 8;
      }
      setPosition(drag.kind, x, y);
      if (!drag.changed) {
        drag.changed = true;
        markDirty();
      }
      syncLayoutInputs();
      requestDraw();
      // Deliberately no PUT/API call here: pointermove is local-only.
    });

    const finish = (event) => {
      const drag = state.drag;
      if (!drag) return;
      state.drag = null;
      canvas.classList.remove("is-dragging");
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      if (drag.changed) setSaveState();
    };
    canvas.addEventListener("pointerup", finish);
    canvas.addEventListener("pointercancel", finish);
  }

  function bindKeyboard() {
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveNow();
        return;
      }
      const target = event.target;
      if (target && target.closest && target.closest("input, textarea, select")) return;
      const deltas = {
        ArrowLeft: [-1, 0],
        ArrowRight: [1, 0],
        ArrowUp: [0, -1],
        ArrowDown: [0, 1],
      };
      const delta = deltas[event.key];
      if (!delta) return;
      const step = event.shiftKey ? 10 : 1;
      const targetPosition = positionFor(state.selection.kind);
      if (!targetPosition) return;
      event.preventDefault();
      setPosition(
        state.selection.kind,
        targetPosition.x + delta[0] * step,
        targetPosition.y + delta[1] * step
      );
      markDirty();
      syncLayoutInputs();
      requestDraw();
    });
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
    syncSelectionFromPreview();
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
      if (state.autoSelect) {
        syncSelectionFromPreview();
      } else if (state.manualBgId) {
        selectBackground(state.manualBgId);
      }
      updateMatchBadge();
      requestDraw();
    });
    $("manual-bg-select").addEventListener("change", (event) => {
      state.manualBgId = event.target.value;
      if (!state.autoSelect) {
        selectBackground(state.manualBgId);
      }
      updateMatchBadge();
      requestDraw();
    });
    for (const id of ["preview-hour", "preview-weekday", "preview-completed", "preview-league", "preview-event", "preview-streak"]) {
      $(id).addEventListener("input", readPreviewControls);
      $(id).addEventListener("change", readPreviewControls);
    }
    for (const id of ["sample-streak", "sample-xp", "sample-rank", "sample-name"]) {
      $(id).addEventListener("input", readSampleControls);
    }
  }

  // -- uploads -------------------------------------------------------
  async function uploadBackgroundFile(file) {
    if (!state.template) return;
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
    const hasFallback = state.template.backgrounds.some((bg) => !Object.keys(bg.when || {}).length);
    state.template.backgrounds.push({
      id: bgId,
      name: (stem || bgId).trim() || bgId,
      src: result.src,
      when: {},
      priority: hasFallback ? 10 : 0,
      fit: "cover",
      offsetX: 0,
      offsetY: 0,
      scale: 1,
      layout: defaultLayout(),
    });
    state.manualBgId = bgId;
    state.imageCache.clear();
    markDirty();
    selectBackgroundInternal(bgId);
    toast(`已上传底图 ${file.name}（未保存）`, "ok");
  }

  async function uploadFlameFile(file) {
    if (!state.template) return;
    const form = new FormData();
    form.append("file", file);
    setStatus("正在上传火焰…", "saving");
    await api(`/templates/${encodeURIComponent(state.template.id)}/assets/flame`, {
      method: "POST",
      form,
    });
    state.imageCache.delete(assetUrl("flame.png"));
    markDirty();
    requestDraw();
    toast("火焰已上传（未保存）", "ok");
  }

  function bindUploads() {
    $("add-bg-upload").addEventListener("click", () => $("bg-file-input").click());
    $("bg-file-input").addEventListener("change", async (event) => {
      const files = [...event.target.files];
      event.target.value = "";
      for (const file of files) {
        try {
          await uploadBackgroundFile(file);
        } catch (error) {
          if (error.status !== 401) {
            toast(`上传失败：${error.message}`, "error");
            setSaveState();
          }
        }
      }
    });
    $("flame-input").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      event.target.value = "";
      if (!file) return;
      try {
        await uploadFlameFile(file);
      } catch (error) {
        if (error.status !== 401) {
          toast(`上传失败：${error.message}`, "error");
          setSaveState();
        }
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
      layout: defaultLayout(),
    });
    state.manualBgId = id;
    markDirty();
    selectBackgroundInternal(id);
    toast("已添加 Ghost 资源底图（引用不复制，未保存）", "ok");
  }

  // -- template actions ---------------------------------------------
  function renderAll() {
    renderTemplateSelect();
    renderBackgroundList();
    renderBackgroundInspector();
    renderLayoutPanel();
    renderManualBgSelect();
    updateMatchBadge();
    updateProductionDisplay();
    setSaveState();
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
    if (!confirmDiscard()) return;
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
      try {
        const flameBlob = await fetchAssetBlob("flame.png");
        const form = new FormData();
        form.append("file", flameBlob, "flame.png");
        await api(`/templates/${encodeURIComponent(created.id)}/assets/flame`, { method: "POST", form });
      } catch (error) {
        if (error.status !== 404) throw error;
      }
      const copy = clone(source);
      copy.id = created.id;
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
      setSaveState();
    } finally {
      button.disabled = false;
    }
  }

  async function deleteTemplate() {
    if (!state.template) return;
    if (!confirmDiscard()) return;
    const id = state.template.id;
    if (!window.confirm(`删除模版 ${id}？目录 data/widgets/${id}/ 会被删除。`)) return;
    try {
      await api(`/templates/${encodeURIComponent(id)}`, { method: "DELETE" });
      await loadTemplates();
      if (state.templates.length) {
        await openTemplate(state.templates[0].id);
      } else {
        state.template = null;
        state.selectedBgId = null;
        state.selectedTextId = null;
        state.dirty = false;
        renderAll();
        setSaveState();
        openTemplateModal();
      }
      toast("模版已删除", "ok");
    } catch (error) {
      if (error.status !== 401) toast(`删除失败：${error.message}`, "error");
    }
  }

  function templateChanged() {
    const select = $("template-select");
    const id = select.value;
    if (!id || id === state.template?.id) return;
    if (!confirmDiscard()) {
      select.value = state.template?.id || "";
      return;
    }
    openTemplate(id).catch((error) => {
      if (error.status !== 401) toast(`切换失败：${error.message}`, "error");
    });
  }

  // -- fixed widget URL / preview ------------------------------------
  function productionUrl() {
    if (!state.userId || !state.template) return "";
    return (
      `${window.location.origin}/v1/widgets/` +
      `${encodeURIComponent(state.userId)}/${encodeURIComponent(state.template.id)}.png`
    );
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
    await copyText(productionUrl(), "固定 URL 已复制");
  }

  async function loadProductionPreview(url, mode) {
    $("preview-error").textContent = "";
    $("preview-meta").textContent = "正在渲染…";
    $("production-url").value = url;
    $("preview-open-link").href = url;
    const image = $("production-image");
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      if (state.previewObjectUrl) URL.revokeObjectURL(state.previewObjectUrl);
      state.previewObjectUrl = URL.createObjectURL(blob);
      image.src = state.previewObjectUrl;
      const bgId = response.headers.get("X-Widget-Background") || "?";
      const textId = response.headers.get("X-Widget-Text") || "?";
      $("preview-meta").textContent =
        `底图 ${bgId} · 文字 ${textId} · ${mode === "random" ? "随机刷新" : "固定 URL"}`;
    } catch (error) {
      $("preview-meta").textContent = "";
      $("preview-error").textContent = `生产图加载失败：${error.message}`;
    }
  }

  function showProductionPreview(mode = "fixed") {
    if (!state.template) return;
    openModal("preview-modal");
    if (state.dirty) toast("有未保存改动：生产预览显示已保存的版本。", "error");
    void loadProductionPreview(productionUrl(), mode);
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
    $("save-template-btn").addEventListener("click", () => void saveNow());
    $("new-template-btn").addEventListener("click", () => {
      if (confirmDiscard()) openTemplateModal();
    });
    $("duplicate-template-btn").addEventListener("click", () => void duplicateTemplate());
    $("delete-template-btn").addEventListener("click", () => void deleteTemplate());
    $("copy-widget-url").addEventListener("click", () => void copyProductionUrl());
    $("copy-production-inline").addEventListener("click", () => void copyProductionUrl());
    $("library-open").addEventListener("click", () => void openLibrary());
    $("production-preview-btn").addEventListener("click", () => showProductionPreview("fixed"));
    $("random-preview-btn").addEventListener("click", () => showProductionPreview("random"));
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

  function installBeforeUnload() {
    window.addEventListener("beforeunload", (event) => {
      if (!state.dirty) return;
      event.preventDefault();
      event.returnValue = "有未保存的改动，确定离开？";
    });
  }

  function start() {
    bindAuth();
    bindTopbar();
    bindModals();
    bindCanvas();
    bindKeyboard();
    bindBackgroundActions();
    bindUploads();
    bindPreviewControls();
    installBeforeUnload();
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
