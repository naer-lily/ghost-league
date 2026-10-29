"use strict";

(() => {
  const TOKEN_KEY = "gl.token.v1";
  const SOUND_KEY = "gl.sound.v1";
  const HAPTICS_KEY = "gl.haptics.v1";
  const POLL_MS = 30_000;
  const RING_RADIUS = 98;
  const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;
  const SCORE_MS = 620;
  const EASE_OUT = "cubic-bezier(0.22, 1, 0.36, 1)";
  const numberFormat = new Intl.NumberFormat("zh-CN");
  const FEED_EMOJIS = ["盯", "卷", "递茶", "记下了", "肃然起敬", "同行"];
  const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const activeNumberNodes = new Set();
  const numberAnimations = new WeakMap();
  const feedbackTimers = new Map();
  let ringAnimation = null;
  let celebrationTimer = 0;
  let momentHideTimer = 0;
  let confettiFrame = 0;
  let confettiVisible = false;
  let syncTimer = 0;

  const DEFAULT_ICON_THEME = "classic";
  const TIER_THEMES = {
    classic: { label: "经典", directory: "" },
    material: { label: "Material", directory: "material" },
  };

  const TIER_META = {
    Bronze: {
      order: 0, slug: "bronze",
      color: "#d08a5a", second: "#8a4c29", glow: "rgba(208,138,90,.38)",
    },
    Silver: {
      order: 1, slug: "silver",
      color: "#cfd8e6", second: "#7e8aa3", glow: "rgba(207,216,230,.30)",
    },
    Gold: {
      order: 2, slug: "gold",
      color: "#ffd45c", second: "#c8861f", glow: "rgba(255,212,92,.36)",
    },
    Sapphire: {
      order: 3, slug: "sapphire",
      color: "#4e9bff", second: "#2455b8", glow: "rgba(78,155,255,.38)",
    },
    Ruby: {
      order: 4, slug: "ruby",
      color: "#ff5577", second: "#b81f46", glow: "rgba(255,85,119,.38)",
    },
    Emerald: {
      order: 5, slug: "emerald",
      color: "#4be5ad", second: "#168c68", glow: "rgba(75,229,173,.36)",
    },
    Amethyst: {
      order: 6, slug: "amethyst",
      color: "#bf73ff", second: "#7430bf", glow: "rgba(191,115,255,.38)",
    },
    Pearl: {
      order: 7, slug: "pearl",
      color: "#ffe9f6", second: "#c795bd", glow: "rgba(255,233,246,.30)",
    },
    Obsidian: {
      order: 8, slug: "obsidian",
      color: "#7b6bff", second: "#261a5f", glow: "rgba(123,107,255,.42)",
    },
    Diamond: {
      order: 9, slug: "diamond",
      color: "#8ff4ff", second: "#2f8da6", glow: "rgba(143,244,255,.40)",
    },
  };
  const TIER_ORDER = Object.keys(TIER_META).sort(
    (left, right) => TIER_META[left].order - TIER_META[right].order,
  );

  const TIER_LABELS = {
    Bronze: "青铜",
    Silver: "白银",
    Gold: "黄金",
    Sapphire: "蓝宝石",
    Ruby: "红宝石",
    Emerald: "翡翠",
    Amethyst: "紫水晶",
    Pearl: "珍珠",
    Obsidian: "黑曜石",
    Diamond: "钻石",
  };

  const el = {};
  const state = {
    token: storageGet(TOKEN_KEY),
    profile: null,
    status: null,
    league: null,
    standings: null,
    friendsStandings: null,
    leagueTab: "group",
    userDetail: null,
    detailUserId: null,
    detailReturnPage: "league",
    meDetail: null,
    people: null,
    peopleLoaded: false,
    history: null,
    historyLoaded: false,
    embers: null,
    embersLoaded: false,
    collection: null,
    collectionLoaded: false,
    feed: null,
    feedLoaded: false,
    feedBusy: false,
    checkins: null,
    repairCandidates: [],
    repairBusy: false,
    page: "home",
    sound: storageGet(SOUND_KEY) !== "0",
    haptics: storageGet(HAPTICS_KEY) !== "0",
    soundReady: false,
    audioContext: null,
    pollTimer: null,
    polling: false,
    loginBusy: false,
    avatarFile: null,
    avatarPreviewUrl: null,
    uploadBusy: false,
    shareBusy: false,
    booted: false,
    offlineToastShown: false,
    lastTier: null,
    tierRailTier: null,
    tierRailNeedsCenter: true,
  };

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }

  function storageGet(key) {
    try { return window.localStorage.getItem(key); } catch (_) { return null; }
  }
  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (_) { /* private mode */ }
  }
  function storageRemove(key) {
    try { window.localStorage.removeItem(key); } catch (_) { /* private mode */ }
  }

  async function copyText(value) {
    const text = String(value || "");
    if (!text) throw new Error("nothing to copy");
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (!ok) throw new Error("copy failed");
  }

  function renderIntegrationToken() {
    if (!el["integration-token-input"]) return;
    el["integration-token-input"].value = state.token || "";
    el["integration-token-input"].type = "password";
    el["integration-token-reveal"].textContent = "显示";
    el["integration-token-reveal"].setAttribute("aria-label", "显示个人访问令牌");
  }

  function cacheIds() {
    [
      "boot-loader", "login-view", "login-form", "token-input", "toggle-token",
      "login-button", "login-error", "app-shell", "offline-banner", "header-group",
      "pull-refresh", "sync-status", "refresh-button",
      "install-button", "sound-button", "header-avatar-button", "header-avatar-fallback",
      "header-avatar-image", "tier-card", "tier-badge", "tier-gem", "home-avatar",
      "home-name", "home-group", "streak-number", "streak-copy", "streak-delta", "ring-card",
      "ring-progress", "today-progress", "xp-delta",
      "today-seconds", "checkin-label", "ring-goal", "ring-status-text", "next-checkin", "week-rank",
      "group-size", "week-seconds", "rank-progress", "rank-card", "rank-change", "rank-helper", "home-group-pill",
      "home-ember-button", "home-ember-balance", "home-full-standings",
      "home-feed-list", "home-feed-empty", "home-feed-all",
      "feed-list", "feed-empty", "feed-loading", "feed-back-button",
      "repair-box", "repair-date", "repair-button", "repair-hint",
      "ember-balance", "ember-cap", "ember-hint", "ember-earned", "ember-week-xp",
      "ember-cap-stat", "ember-cap-rule", "ember-ledger", "ember-ledger-empty",
      "ember-ledger-loading", "ember-ledger-count",
      "collection-card", "collection-equipped", "collection-titles",
      "collection-items", "collection-empty",
      "home-standings", "home-standings-empty", "league-subtitle", "league-group-name",
      "league-snapshot", "league-count", "league-standings", "league-standings-empty",
      "league-tier-icon", "league-tier-name", "league-group-meta", "league-days-left",
      "league-tier-slots", "tier-rail-summary",
      "moment-overlay", "moment-kicker", "moment-title", "moment-copy", "live-status",
      "profile-avatar", "avatar-input", "choose-avatar-button", "upload-avatar-button",
      "profile-form", "display-name-input", "activity-label-input",
      "icon-theme-options", "save-name-button", "name-save-status",
      "sound-toggle-row", "haptics-toggle-row", "profile-user-id", "profile-group",
      "profile-joined", "logout-button", "history-list", "history-empty", "history-loading",
      "confetti-canvas", "toast", "history-error", "share-card-button",
      "league-tab-group", "league-tab-friends",
      "me-week-xp", "me-tier", "me-streak", "me-today-xp",
      "me-following-count", "me-followers-count", "nearby-people-row",
      "user-back-button", "user-loading", "user-error", "user-content",
      "user-detail-avatar", "user-detail-name", "user-detail-handle",
      "user-detail-joined", "user-detail-activity", "user-detail-title",
      "user-follow-button",
      "user-following-count", "user-followers-count", "user-week-minutes",
      "user-detail-tier", "user-detail-tier-icon", "user-week-total",
      "user-detail-group", "user-stat-rank", "user-stat-streak", "user-stat-checkin",
      "user-stat-tier",
      "people-back-button", "people-list", "people-empty", "people-loading",
      "people-error", "integration-docs-row", "integration-back-button",
      "integration-token-input", "integration-token-reveal",
      "integration-token-copy", "rotate-token-button",
    ].forEach((id) => {
      el[id] = document.getElementById(id);
    });
  }

  function number(value) {
    return numberFormat.format(Math.max(0, Math.round(Number(value) || 0)));
  }

  function initialOf(name) {
    const match = String(name || "?").match(/[A-Za-z0-9\u3400-\u9fff]/u);
    return match ? match[0].toUpperCase() : "?";
  }

  function shortTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function tierInfo(tier) {
    return TIER_META[tier] || TIER_META.Bronze;
  }

  function tierLabel(tier) {
    return TIER_LABELS[tier] || TIER_LABELS.Bronze;
  }

  function tierKey(tier) {
    return tierInfo(tier).slug;
  }

  function normalizeIconTheme(theme) {
    return Object.prototype.hasOwnProperty.call(TIER_THEMES, theme)
      ? theme
      : DEFAULT_ICON_THEME;
  }

  function profileIconTheme(profile = state.profile) {
    return normalizeIconTheme(profile?.icon_theme);
  }

  function detailIconTheme(detail = state.userDetail) {
    return normalizeIconTheme(detail?.icon_theme);
  }

  function tierIconUrl(slug, theme = DEFAULT_ICON_THEME) {
    const selected = TIER_THEMES[normalizeIconTheme(theme)];
    return `/assets/tiers/${selected.directory ? `${selected.directory}/` : ""}${slug}.png`;
  }

  function applyIconTheme(theme) {
    document.documentElement.dataset.iconTheme = normalizeIconTheme(theme);
  }

  function selectIconTheme(theme) {
    const selected = normalizeIconTheme(theme);
    applyIconTheme(selected);
    document.querySelectorAll('input[name="icon_theme"]').forEach((input) => {
      const option = input.closest(".theme-option");
      const active = input.value === selected;
      input.checked = active;
      if (option) {
        option.classList.toggle("is-selected", active);
        const status = option.querySelector(".theme-option-state");
        if (status) status.textContent = active ? "已选择" : "选择";
      }
    });
  }

  function selectedIconTheme() {
    const checked = document.querySelector('input[name="icon_theme"]:checked');
    return normalizeIconTheme(checked?.value);
  }

  function renderThemePicker() {
    const theme = profileIconTheme();
    selectIconTheme(theme);
    document.querySelectorAll(".theme-preview[data-slug]").forEach((image) => {
      const imageTheme = normalizeIconTheme(image.dataset.theme);
      image.src = tierIconUrl(image.dataset.slug, imageTheme);
    });
  }

  function groupLabel(group) {
    if (!group) return "等待数据";
    if (typeof group === "object") {
      return `${tierLabel(group.tier)} · ${groupCode(group)}`;
    }
    const match = String(group).match(/^([A-Za-z]+)-(.+)$/);
    if (!match) return String(group);
    return `${TIER_LABELS[match[1]] || match[1]} · ${match[2]}`;
  }

  function groupCode(group) {
    if (!group) return "—";
    if (typeof group === "object") {
      return `G${String(group.no ?? 0).padStart(2, "0")}`;
    }
    const match = String(group).match(/^([A-Za-z]+)-(.+)$/);
    return match ? match[2] : String(group);
  }

  function isCheckedIn(status = state.status) {
    return Boolean(status?.checkin);
  }

  function currentStreak(status = state.status) {
    return Math.max(0, Number(status?.streak?.current) || 0);
  }

  function requiredXp(status = state.status) {
    return Math.max(1, Number(status?.required_xp) || 100);
  }

  function localDateIso(value) {
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
  }

  function shiftIsoDate(iso, days) {
    const match = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return "";
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }

  function formatDayLabel(iso) {
    const match = String(iso || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return String(iso || "—");
    return `${Number(match[2])}月${Number(match[3])}日`;
  }

  function remainingWeekDays(weekStart) {
    const match = String(weekStart || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return "—";
    const monday = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    const shanghaiNow = new Date(Date.now() + 8 * 60 * 60 * 1000);
    const today = Date.UTC(
      shanghaiNow.getUTCFullYear(),
      shanghaiNow.getUTCMonth(),
      shanghaiNow.getUTCDate(),
    );
    const dayIndex = Math.floor((today - monday) / 86_400_000);
    return String(Math.max(0, 6 - dayIndex));
  }

  function snapshotLabel(payload) {
    const time = shortTime(payload?.updated_at || state.status?.updated_at);
    return time === "—" ? "本周" : `更新 ${time}`;
  }

  function activityLabel() {
    const value = String(state.profile?.activity_label || "练习").trim();
    return value || "练习";
  }

  function shareActivityLabel() {
    const chars = Array.from(activityLabel());
    return chars.length > 10 ? `${chars.slice(0, 10).join("")}…` : chars.join("");
  }

  const SHARE_FONT = '"PingFang SC","Hiragino Sans GB","Microsoft YaHei",system-ui,-apple-system,sans-serif';
  const SHARE_WIDTH = 1080;
  const SHARE_HEIGHT = 1440;

  function hexToRgba(hex, alpha) {
    let value = String(hex || "#ffffff").replace("#", "");
    if (value.length === 3) value = value.split("").map((char) => char + char).join("");
    const numberValue = Number.parseInt(value, 16);
    if (Number.isNaN(numberValue)) return `rgba(255,255,255,${alpha})`;
    return `rgba(${(numberValue >> 16) & 255},${(numberValue >> 8) & 255},${numberValue & 255},${alpha})`;
  }

  function roundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function fitFont(ctx, text, weight, maxSize, minSize, maxWidth) {
    let size = maxSize;
    while (size > minSize) {
      ctx.font = `${weight} ${size}px ${SHARE_FONT}`;
      if (ctx.measureText(text).width <= maxWidth) break;
      size -= 2;
    }
    return `${weight} ${size}px ${SHARE_FONT}`;
  }

  function shareWeekRange() {
    const iso = state.standings?.week_start || state.league?.week_start;
    if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
    const start = new Date(`${iso}T00:00:00Z`);
    if (Number.isNaN(start.getTime())) return "";
    const end = new Date(start.getTime() + 6 * 86_400_000);
    const fmt = (date) => `${date.getUTCFullYear()}.${String(date.getUTCMonth() + 1).padStart(2, "0")}.${String(date.getUTCDate()).padStart(2, "0")}`;
    return `${fmt(start)} – ${fmt(end).slice(5)}`;
  }

  function loadShareAvatar(url) {
    return new Promise((resolve) => {
      if (!url) { resolve(null); return; }
      const image = new Image();
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        resolve(value);
      };
      image.onload = () => finish(image);
      image.onerror = () => finish(null);
      window.setTimeout(() => finish(null), 2600);
      image.src = avatarSrc(url);
    });
  }

  function canvasToBlob(canvas) {
    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("canvas export failed"));
      }, "image/png");
    });
  }

  function drawShareAvatar(ctx, image, centerX, centerY, radius, tierColor, tierSecond, name) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + 10, 0, Math.PI * 2);
    ctx.strokeStyle = hexToRgba(tierColor, 0.85);
    ctx.lineWidth = 8;
    ctx.shadowColor = hexToRgba(tierColor, 0.55);
    ctx.shadowBlur = 45;
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
    ctx.clip();
    if (image && image.width && image.height) {
      const scale = Math.max((radius * 2) / image.width, (radius * 2) / image.height);
      const width = image.width * scale;
      const height = image.height * scale;
      ctx.drawImage(image, centerX - width / 2, centerY - height / 2, width, height);
    } else {
      const gradient = ctx.createLinearGradient(
        centerX - radius, centerY - radius, centerX + radius, centerY + radius,
      );
      gradient.addColorStop(0, tierColor);
      gradient.addColorStop(1, tierSecond);
      ctx.fillStyle = gradient;
      ctx.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);
      ctx.fillStyle = "rgba(255,255,255,.92)";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = `900 ${radius * 0.85}px ${SHARE_FONT}`;
      ctx.fillText(initialOf(name), centerX, centerY + radius * 0.04);
    }
    ctx.restore();
  }

  function drawShareMetric(ctx, x, y, width, height, label, value, sub, accent) {
    ctx.save();
    roundedRect(ctx, x, y, width, height, 28);
    ctx.fillStyle = "rgba(255,255,255,.055)";
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,.11)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.fillStyle = "rgba(223,230,255,.58)";
    ctx.font = `600 22px ${SHARE_FONT}`;
    ctx.textAlign = "left";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + 30, y + 34);
    ctx.fillStyle = "#ffffff";
    ctx.font = `900 46px ${SHARE_FONT}`;
    ctx.fillText(value, x + 30, y + 91);
    if (accent) {
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(x + width - 34, y + 34, 9, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = "rgba(223,230,255,.55)";
    ctx.font = `500 21px ${SHARE_FONT}`;
    ctx.fillText(sub, x + 30, y + 132);
    ctx.restore();
  }

  async function buildShareCard() {
    const profile = state.profile;
    const status = state.status;
    if (!profile || !status) throw new Error("profile is not loaded");
    const tier = status.tier || profile.tier || "Bronze";
    const info = tierInfo(tier);
    const name = status.display_name || profile.display_name || "You";
    const canvas = document.createElement("canvas");
    canvas.width = SHARE_WIDTH;
    canvas.height = SHARE_HEIGHT;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas is unavailable");

    const background = ctx.createLinearGradient(0, 0, SHARE_WIDTH, SHARE_HEIGHT);
    background.addColorStop(0, "#10142b");
    background.addColorStop(0.55, "#0b1020");
    background.addColorStop(1, "#070a14");
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, SHARE_WIDTH, SHARE_HEIGHT);

    const glow = ctx.createRadialGradient(540, 180, 40, 540, 200, 760);
    glow.addColorStop(0, hexToRgba(info.color, 0.42));
    glow.addColorStop(0.45, hexToRgba(info.color, 0.1));
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, SHARE_WIDTH, SHARE_HEIGHT);

    const lowerGlow = ctx.createRadialGradient(920, 1260, 20, 920, 1260, 520);
    lowerGlow.addColorStop(0, "rgba(255,77,141,.16)");
    lowerGlow.addColorStop(1, "rgba(255,77,141,0)");
    ctx.fillStyle = lowerGlow;
    ctx.fillRect(0, 0, SHARE_WIDTH, SHARE_HEIGHT);

    ctx.strokeStyle = "rgba(255,255,255,.032)";
    ctx.lineWidth = 1;
    for (let x = 0; x <= SHARE_WIDTH; x += 90) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, SHARE_HEIGHT);
      ctx.stroke();
    }
    for (let y = 0; y <= SHARE_HEIGHT; y += 90) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(SHARE_WIDTH, y);
      ctx.stroke();
    }

    ctx.save();
    roundedRect(ctx, 28, 28, SHARE_WIDTH - 56, SHARE_HEIGHT - 56, 44);
    ctx.strokeStyle = "rgba(255,255,255,.12)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();

    const markGradient = ctx.createLinearGradient(84, 84, 168, 168);
    markGradient.addColorStop(0, "#6c4cff");
    markGradient.addColorStop(1, "#ff4d8d");
    roundedRect(ctx, 84, 84, 78, 78, 20);
    ctx.fillStyle = markGradient;
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `900 29px ${SHARE_FONT}`;
    ctx.fillText("联", 123, 124);
    ctx.textAlign = "left";
    ctx.fillStyle = "#ffffff";
    ctx.font = `800 43px ${SHARE_FONT}`;
    ctx.fillText("联赛", 184, 124);
    ctx.fillStyle = "rgba(220,228,255,.58)";
    ctx.font = `500 20px ${SHARE_FONT}`;
    ctx.fillText(`我的每周${shareActivityLabel()}联赛`, 184, 162);
    const weekRange = shareWeekRange();
    if (weekRange) {
      ctx.textAlign = "right";
      ctx.fillStyle = "rgba(220,228,255,.72)";
      ctx.font = `600 21px ${SHARE_FONT}`;
      ctx.fillText(weekRange, 996, 124);
    }

    const avatar = await loadShareAvatar(profile.avatar_url);
    drawShareAvatar(ctx, avatar, 540, 374, 125, info.color, info.second, name);

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#ffffff";
    ctx.font = fitFont(ctx, name, 800, 64, 40, 800);
    ctx.fillText(name, 540, 566);

    const badgeText = tierLabel(tier);
    ctx.font = `800 28px ${SHARE_FONT}`;
    const badgeWidth = ctx.measureText(badgeText).width + 88;
    const badgeX = 540 - badgeWidth / 2;
    const badgeGradient = ctx.createLinearGradient(badgeX, 615, badgeX + badgeWidth, 663);
    badgeGradient.addColorStop(0, info.color);
    badgeGradient.addColorStop(1, info.second);
    roundedRect(ctx, badgeX, 615, badgeWidth, 48, 24);
    ctx.fillStyle = badgeGradient;
    ctx.fill();
    ctx.fillStyle = ["Silver", "Gold", "Pearl", "Diamond"].includes(tier) ? "#17132a" : "#ffffff";
    ctx.fillText(badgeText, 540, 640);

    ctx.fillStyle = "rgba(220,228,255,.58)";
    ctx.font = `600 23px ${SHARE_FONT}`;
    ctx.fillText(`本周${shareActivityLabel()}`, 540, 742);

    const duration = { value: number(status.xp || 0), unit: "XP" };
    ctx.font = fitFont(ctx, duration.value, 950, 196, 120, 620);
    const valueWidth = ctx.measureText(duration.value).width;
    ctx.font = `800 42px ${SHARE_FONT}`;
    const unitWidth = ctx.measureText(duration.unit).width;
    const startX = (SHARE_WIDTH - (valueWidth + 16 + unitWidth)) / 2;
    ctx.textAlign = "left";
    ctx.fillStyle = "#ffffff";
    ctx.shadowColor = hexToRgba(info.color, 0.45);
    ctx.shadowBlur = 30;
    ctx.font = fitFont(ctx, duration.value, 950, 196, 120, 620);
    ctx.fillText(duration.value, startX, 878);
    ctx.shadowBlur = 0;
    ctx.fillStyle = "rgba(232,238,255,.8)";
    ctx.font = `800 42px ${SHARE_FONT}`;
    ctx.fillText(duration.unit, startX + valueWidth + 16, 878);

    const rank = status.rank || 0;
    const groupSize = status.group_size || 15;
    const streakDays = currentStreak(status);
    const longestStreak = Math.max(0, Number(status.streak?.longest) || 0);
    drawShareMetric(
      ctx, 72, 990, 448, 168,
      "小组排名", `第 ${rank} 名 / ${groupSize}`, "我的位置", info.color,
    );
    drawShareMetric(
      ctx, 560, 990, 448, 168,
      "当前连胜", `${streakDays} 天连胜`,
      streakDays > 0 ? `最长 ${longestStreak} 天` : "今天开始新的连胜",
      "#ffcc5c",
    );

    const today = Math.max(0, Number(status.today_xp) || 0);
    const checked = isCheckedIn(status);
    const remaining = Math.max(0, requiredXp(status) - today);
    const checkinText = checked ? "今日已打卡" : `还差 ${remaining} XP 打卡`;
    roundedRect(ctx, 72, 1202, 936, 104, 28);
    ctx.fillStyle = checked ? "rgba(92,224,190,.13)" : "rgba(255,255,255,.05)";
    ctx.fill();
    ctx.strokeStyle = checked ? "rgba(92,224,190,.3)" : "rgba(255,255,255,.1)";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.textAlign = "left";
    ctx.fillStyle = checked ? "#5ce0be" : "rgba(236,241,255,.85)";
    ctx.font = `800 30px ${SHARE_FONT}`;
    ctx.fillText(checkinText, 108, 1254);
    const ringRatio = Math.min(1, today / requiredXp(status));
    roundedRect(ctx, 690, 1241, 272, 18, 9);
    ctx.fillStyle = "rgba(255,255,255,.1)";
    ctx.fill();
    roundedRect(ctx, 690, 1241, Math.max(8, 272 * ringRatio), 18, 9);
    ctx.fillStyle = checked ? "#5ce0be" : info.color;
    ctx.fill();

    ctx.strokeStyle = "rgba(255,255,255,.1)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(84, 1338);
    ctx.lineTo(996, 1338);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.fillStyle = "rgba(220,228,255,.62)";
    ctx.font = `600 23px ${SHARE_FONT}`;
    ctx.fillText(`我的每周${shareActivityLabel()}联赛`, 540, 1380);

    return canvasToBlob(canvas);
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.style.display = "none";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1800);
  }

  function shareFilename() {
    const raw = String(state.profile?.user_id || "me").replace(/[^A-Za-z0-9._-]/g, "_").slice(0, 48) || "me";
    const date = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Shanghai",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()).replaceAll("/", "-");
    return `league-${raw}-${date}.png`;
  }

  async function shareCard() {
    if (state.shareBusy) return;
    if (!state.profile || !state.status) {
      showToast("战绩还在加载，请稍后再试。");
      return;
    }
    state.shareBusy = true;
    const button = el["share-card-button"];
    setBusy(button, true);
    playClick();
    try {
      const blob = await buildShareCard();
      const filename = shareFilename();
      const file = typeof File === "function"
        ? new File([blob], filename, { type: "image/png" })
        : null;
      let shared = false;
      let canShareFiles = false;
      if (file && navigator.share && navigator.canShare) {
        try {
          canShareFiles = navigator.canShare({ files: [file] });
        } catch (_) {
          canShareFiles = false;
        }
      }
      if (file && navigator.share && canShareFiles) {
        try {
          await navigator.share({
            files: [file],
            title: `我的本周${activityLabel()}战绩`,
            text: `我的每周${activityLabel()}联赛本周战绩`,
          });
          shared = true;
          showToast("战绩卡已分享。");
          vibrate([18]);
        } catch (error) {
          if (error && error.name === "AbortError") {
            showToast("已取消分享，正在保存图片。");
          } else {
            showToast("系统分享不可用，正在保存图片。");
          }
        }
      } else if (file && navigator.share) {
        showToast("当前设备不支持文件分享，正在保存图片。");
      } else {
        showToast("已生成战绩卡，正在保存图片。");
      }
      if (!shared) {
        downloadBlob(blob, filename);
      }
    } catch (error) {
      showToast("战绩卡生成失败，请重试。");
      sound.error();
    } finally {
      state.shareBusy = false;
      setBusy(button, false);
    }
  }

  function avatarSrc(url) {
    if (!url) return "";
    const version = encodeURIComponent(state.status?.updated_at || "");
    const separator = url.includes("?") ? "&" : "?";
    return `${url}${separator}v=${version}`;
  }

  const FRAME_ART_SOURCES = Object.freeze({
    frame_ember: "/assets/frames/frame_ember.png",
    frame_clown: "/assets/frames/frame_clown.png",
  });
  const FRAME_NAME_TO_ID = Object.freeze({
    余烬: "frame_ember",
    小丑帽: "frame_clown",
  });

  function resolveFrameId(frame) {
    const raw = String(frame || "").trim();
    if (!raw) return "";
    if (FRAME_ART_SOURCES[raw]) return raw;
    if (FRAME_NAME_TO_ID[raw]) return FRAME_NAME_TO_ID[raw];
    const items = Array.isArray(state.collection?.items) ? state.collection.items : [];
    const match = items.find(
      (entry) => entry?.slot === "frame" && String(entry.name || "").trim() === raw,
    );
    return match ? String(match.id || "") : "";
  }

  function paintAvatarFrame(container, frameId) {
    const resolvedFrameId = resolveFrameId(frameId);
    const source = FRAME_ART_SOURCES[resolvedFrameId] || "";
    let overlay = container.querySelector("img.avatar-frame-art");
    if (!source) {
      if (overlay) overlay.remove();
      container.classList.remove("has-frame-art");
      delete container.dataset.frame;
      return;
    }
    if (!overlay) {
      overlay = document.createElement("img");
      overlay.className = "avatar-frame-art";
      overlay.alt = "";
      overlay.setAttribute("aria-hidden", "true");
      overlay.decoding = "async";
      overlay.draggable = false;
      container.append(overlay);
    }
    container.dataset.frame = resolvedFrameId;
    if (overlay.getAttribute("src") !== source) {
      overlay.setAttribute("src", source);
    }
    container.classList.add("has-frame-art");
  }

  function paintAvatar(container, url, name, frameId) {
    if (!container) return;
    paintAvatarFrame(container, frameId);
    const fallback = container.querySelector(".avatar-fallback");
    const image = container.querySelector("img:not(.avatar-frame-art)");
    if (fallback) fallback.textContent = initialOf(name);
    if (!image) return;
    if (!url) {
      image.hidden = true;
      image.removeAttribute("src");
      if (fallback) fallback.hidden = false;
      return;
    }
    image.onerror = () => {
      image.hidden = true;
      if (fallback) fallback.hidden = false;
    };
    image.onload = () => {
      image.hidden = false;
      if (fallback) fallback.hidden = true;
    };
    image.src = avatarSrc(url);
  }

  function showToast(message) {
    if (!el.toast) return;
    el.toast.textContent = message;
    el.toast.hidden = false;
    requestAnimationFrame(() => el.toast.classList.add("is-visible"));
    window.clearTimeout(showToast.timer);
    window.clearTimeout(showToast.hideTimer);
    showToast.timer = window.setTimeout(() => {
      el.toast.classList.remove("is-visible");
      showToast.hideTimer = window.setTimeout(() => {
        el.toast.hidden = true;
      }, reducedMotionQuery.matches ? 0 : 220);
    }, 2800);
  }

  function announceStatus(message) {
    if (!el["live-status"]) return;
    window.clearTimeout(announceStatus.timer);
    el["live-status"].textContent = "";
    announceStatus.timer = window.setTimeout(() => {
      if (el["live-status"]) el["live-status"].textContent = message;
    }, 30);
  }

  function setFeedbackTimer(key, callback, delay) {
    const previous = feedbackTimers.get(key);
    if (previous) window.clearTimeout(previous);
    const timer = window.setTimeout(() => {
      feedbackTimers.delete(key);
      callback();
    }, delay);
    feedbackTimers.set(key, timer);
  }

  function pulseClass(node, className, delay = 1200) {
    if (!node) return;
    node.classList.remove(className);
    if (!reducedMotionQuery.matches) {
      // Restart the one-shot cue without touching layout beyond a forced style flush.
      void node.offsetWidth;
    }
    node.classList.add(className);
    const key = `class:${node.id || node.className}:${className}`;
    setFeedbackTimer(key, () => node.classList.remove(className), delay);
  }

  function showDelta(node, text, tone, delay = 2400) {
    if (!node) return;
    node.textContent = text;
    node.classList.remove("is-up", "is-down", "is-neutral");
    if (tone) node.classList.add(tone);
    node.hidden = false;
    pulseClass(node, "is-visible", delay);
    setFeedbackTimer(`delta:${node.id}`, () => {
      node.classList.remove("is-visible", "is-up", "is-down", "is-neutral");
      node.hidden = true;
    }, delay);
  }

  function setSyncStatus(label, state = "ok") {
    if (!el["sync-status"]) return;
    window.clearTimeout(syncTimer);
    el["sync-status"].textContent = label;
    el["sync-status"].dataset.state = state;
    el["sync-status"].hidden = false;
    syncTimer = window.setTimeout(() => {
      if (!el["sync-status"]) return;
      el["sync-status"].hidden = true;
    }, 3200);
  }

  function hideMoment() {
    window.clearTimeout(celebrationTimer);
    window.clearTimeout(momentHideTimer);
    if (!el["moment-overlay"]) return;
    el["moment-overlay"].classList.remove("is-visible");
    el["moment-overlay"].dataset.kind = "";
    const hide = () => {
      if (el["moment-overlay"]) el["moment-overlay"].hidden = true;
    };
    if (reducedMotionQuery.matches) hide();
    else momentHideTimer = window.setTimeout(hide, 260);
  }

  function showMoment(kicker, title, copy, kind = "milestone") {
    if (!el["moment-overlay"]) return;
    window.clearTimeout(celebrationTimer);
    window.clearTimeout(momentHideTimer);
    el["moment-kicker"].textContent = kicker;
    el["moment-title"].textContent = title;
    el["moment-copy"].textContent = copy;
    el["moment-overlay"].dataset.kind = kind;
    el["moment-overlay"].hidden = false;
    requestAnimationFrame(() => el["moment-overlay"].classList.add("is-visible"));
    celebrationTimer = window.setTimeout(hideMoment, 3000);
    announceStatus(`${title}。${copy}`);
  }

  function stopConfetti() {
    confettiVisible = false;
    if (confettiFrame) cancelAnimationFrame(confettiFrame);
    confettiFrame = 0;
    const canvas = el["confetti-canvas"];
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  function cancelTransientFeedback() {
    feedbackTimers.forEach((timer) => window.clearTimeout(timer));
    feedbackTimers.clear();
    ["xp-delta", "rank-change", "streak-delta"].forEach((id) => {
      const node = el[id];
      if (!node) return;
      node.hidden = true;
      node.classList.remove("is-visible", "is-up", "is-down", "is-neutral");
    });
    ["ring-card", "rank-card", "streak-card"].forEach((id) => {
      const node = id === "streak-card"
        ? document.querySelector(".streak-card")
        : el[id];
      if (!node) return;
      node.classList.remove("is-awarding", "is-rank-up", "is-rank-down", "is-flaring");
    });
    hideMoment();
    stopConfetti();
  }

  function setLoginError(message) {
    el["login-error"].textContent = message || "";
    el["login-error"].hidden = !message;
  }

  function setBusy(button, busy) {
    if (!button) return;
    const spinner = button.querySelector(".button-spinner");
    button.disabled = busy;
    if (spinner) spinner.hidden = !busy;
  }

  function unlockAudio() {
    if (!state.sound) return;
    try {
      if (!state.audioContext) {
        const AudioCtor = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtor) return;
        state.audioContext = new AudioCtor();
        state.soundReady = true;
      }
      if (state.audioContext.state === "suspended") state.audioContext.resume().catch(() => {});
    } catch (_) { /* audio is optional */ }
  }

  function tone(frequency, start, duration, gainValue = 0.09, type = "sine") {
    if (!state.sound || !state.audioContext) return;
    const ctx = state.audioContext;
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = type;
    oscillator.frequency.setValueAtTime(frequency, ctx.currentTime + start);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime + start);
    gain.gain.exponentialRampToValueAtTime(gainValue, ctx.currentTime + start + 0.012);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + duration);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start(ctx.currentTime + start);
    oscillator.stop(ctx.currentTime + start + duration + 0.03);
  }

  const sound = {
    click() { unlockAudio(); tone(540, 0, 0.055, 0.035, "triangle"); },
    error() { unlockAudio(); tone(180, 0, 0.11, 0.07, "sawtooth"); },
    checkin() {
      unlockAudio();
      tone(523.25, 0, 0.12, 0.1);
      tone(659.25, 0.1, 0.13, 0.1);
      tone(783.99, 0.22, 0.22, 0.11);
      vibrate([24, 30, 55]);
    },
    first() {
      unlockAudio();
      [523.25, 659.25, 783.99, 1046.5].forEach((freq, index) => {
        tone(freq, index * 0.09, 0.18, 0.1, "triangle");
      });
      vibrate([18, 24, 18, 24, 70]);
    },
    promotion() {
      unlockAudio();
      tone(392, 0, 0.12, 0.09);
      tone(523.25, 0.11, 0.14, 0.1);
      tone(659.25, 0.24, 0.26, 0.12);
      vibrate([20, 25, 20, 25, 60]);
    },
  };

  function vibrate(pattern) {
    if (!state.haptics || !navigator.vibrate) return;
    try { navigator.vibrate(pattern); } catch (_) { /* unsupported */ }
  }

  function playClick() {
    if (!state.sound) return;
    sound.click();
  }

  async function api(path, options = {}) {
    if (!state.token) throw new ApiError("请先登录", 401);
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${state.token}`);
    let body = options.body;
    if (options.json !== undefined) {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(options.json);
    }
    let response;
    try {
      response = await fetch(path, {
        method: options.method || "GET",
        headers,
        body,
        cache: "no-store",
        credentials: "same-origin",
      });
    } catch (error) {
      throw new ApiError("网络不可用，请稍后重试", 0);
    }
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json().catch(() => null);
    }
    if (!response.ok) {
      if (response.status === 401 && !options.skipAuthRedirect) {
        signOut("登录已失效，请重新输入令牌。");
      }
      let detail = payload && (payload.detail || payload.message);
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg || "请求不合法").join("；");
      } else if (detail && typeof detail === "object") {
        detail = detail.message || detail.code || "请求不合法";
      }
      throw new ApiError(detail || `请求失败（${response.status}）`, response.status);
    }
    return payload;
  }

  function applyTier(tier, theme = profileIconTheme()) {
    const info = tierInfo(tier);
    applyIconTheme(theme);
    document.documentElement.style.setProperty("--tier", info.color);
    document.documentElement.style.setProperty("--tier-2", info.second);
    document.documentElement.style.setProperty("--tier-glow", info.glow);
    if (!el["tier-card"]) return;
    el["tier-card"].className = `card tier-card tier-${tierKey(tier)}`;
    el["tier-badge"].textContent = tierLabel(tier);
    if (el["tier-gem"]) {
      el["tier-gem"].src = tierIconUrl(info.slug, theme);
      el["tier-gem"].alt = "";
    }
  }

  function settleNumber(node) {
    if (!node) return;
    const target = Number(node.dataset.value || 0);
    const active = numberAnimations.get(node);
    if (active) cancelAnimationFrame(active.frame);
    numberAnimations.delete(node);
    activeNumberNodes.delete(node);
    node.dataset.display = String(target);
    node.textContent = number(target);
  }

  function animateNumber(node, target) {
    if (!node) return;
    const end = Math.max(0, Math.round(Number(target) || 0));
    const active = numberAnimations.get(node);
    if (active) cancelAnimationFrame(active.frame);
    if (reducedMotionQuery.matches) {
      node.dataset.value = String(end);
      settleNumber(node);
      return;
    }
    const start = Number(node.dataset.display ?? 0);
    if (!Number.isFinite(start) || start === end) {
      node.dataset.value = String(end);
      settleNumber(node);
      return;
    }
    const started = performance.now();
    node.dataset.value = String(end);
    activeNumberNodes.add(node);
    const step = (now) => {
      const progress = Math.min(1, (now - started) / SCORE_MS);
      const eased = 1 - Math.pow(1 - progress, 3);
      const value = start + (end - start) * eased;
      node.dataset.display = String(value);
      node.textContent = number(value);
      if (progress < 1) {
        const frame = requestAnimationFrame(step);
        numberAnimations.set(node, { frame });
      } else {
        numberAnimations.delete(node);
        activeNumberNodes.delete(node);
        node.dataset.display = String(end);
        node.textContent = number(end);
      }
    };
    const frame = requestAnimationFrame(step);
    numberAnimations.set(node, { frame });
  }

  function setRingProgress(ratio) {
    const node = el["ring-progress"];
    if (!node) return;
    const safeRatio = Math.min(1, Math.max(0, Number(ratio) || 0));
    const targetOffset = RING_CIRCUMFERENCE * (1 - safeRatio);
    const currentOffset = Number.parseFloat(window.getComputedStyle(node).strokeDashoffset);
    node.style.strokeDasharray = String(RING_CIRCUMFERENCE);
    if (ringAnimation) {
      ringAnimation.cancel();
      ringAnimation = null;
    }
    if (reducedMotionQuery.matches || !Number.isFinite(currentOffset)) {
      node.style.strokeDashoffset = String(targetOffset);
      return;
    }
    ringAnimation = node.animate(
      [
        { strokeDashoffset: String(currentOffset) },
        { strokeDashoffset: String(targetOffset) },
      ],
      { duration: SCORE_MS, easing: EASE_OUT, fill: "both" },
    );
    ringAnimation.onfinish = () => {
      node.style.strokeDashoffset = String(targetOffset);
      if (ringAnimation) ringAnimation.cancel();
      ringAnimation = null;
    };
  }

  function settleMotionState() {
    activeNumberNodes.forEach((node) => settleNumber(node));
    if (ringAnimation) {
      try { ringAnimation.finish(); } catch (_) { ringAnimation = null; }
    }
    stopConfetti();
  }

  function renderProfile() {
    const profile = state.profile;
    const status = state.status;
    if (!profile) return;
    const tier = status?.tier || profile.tier || "Bronze";
    const theme = profileIconTheme(profile);
    applyTier(tier, theme);
    renderThemePicker();
    const name = status?.display_name || profile.display_name || "You";
    const groupText = status?.group
      ? groupLabel(status.group)
      : "等待数据";
    el["home-name"].textContent = name;
    el["home-group"].textContent = groupText;
    el["header-group"].textContent = groupText;
    paintAvatar(
      el["home-avatar"],
      profile.avatar_url,
      name,
      state.collection?.equipped?.frame_id,
    );
    paintAvatar(
      el["profile-avatar"],
      profile.avatar_url,
      name,
      state.collection?.equipped?.frame_id,
    );
    paintAvatar(
      el["header-avatar-button"],
      profile.avatar_url,
      name,
      state.collection?.equipped?.frame_id,
    );
    el["profile-user-id"].textContent = profile.user_id;
    el["profile-group"].textContent = groupText;
    el["profile-joined"].textContent = profile.joined_week ? `第 ${profile.joined_week} 轮` : "—";
    if (document.activeElement !== el["display-name-input"]) {
      el["display-name-input"].value = profile.display_name || "";
    }
    if (document.activeElement !== el["activity-label-input"]) {
      el["activity-label-input"].value = activityLabel();
    }
    const meta = document.querySelector('meta[name="description"]');
    if (meta) {
      meta.setAttribute(
        "content",
        `把每天的${activityLabel()}变成连胜、打卡和小组排名。`,
      );
    }
  }

  function renderHome() {
    const status = state.status;
    if (!status) return;
    const goal = requiredXp(status);
    const todayXp = Math.max(0, Number(status.today_xp) || 0);
    const ratio = Math.min(1, todayXp / goal);
    const checked = isCheckedIn(status);
    const streakDays = currentStreak(status);
    if (el["ring-progress"]) el["ring-progress"].style.stroke = tierInfo(status.tier).color;
    setRingProgress(ratio);
    animateNumber(el["today-seconds"], todayXp);
    el["checkin-label"].textContent = checked ? "今日已打卡" : "还没打卡";
    el["checkin-label"].classList.toggle("is-done", checked);
    if (el["ring-goal"]) el["ring-goal"].textContent = `今日目标 ${goal} XP`;
    el["ring-status-text"].textContent = checked
      ? "今天的目标已完成，保持火焰。"
      : `今天${activityLabel()}满 ${goal} XP 即可打卡`;
    el["next-checkin"].textContent = "每天 00:00 开始新一天";
    if (el["ring-card"]) {
      el["ring-card"].style.setProperty("--daily-progress", `${ratio * 100}%`);
    }
    if (el["today-progress"]) {
      el["today-progress"].setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
    }
    animateNumber(el["streak-number"], streakDays);
    if (checked) {
      el["streak-copy"].textContent = "今天已打卡，火焰继续燃烧。";
    } else if (streakDays > 0) {
      el["streak-copy"].textContent = `今天还没打卡，别让 ${streakDays} 天连胜断掉。`;
    } else {
      el["streak-copy"].textContent = `今天${activityLabel()}满 ${goal} XP，点亮火焰。`;
    }
    if (status.group) {
      animateNumber(el["week-rank"], status.rank || 0);
      el["group-size"].textContent = `/${status.group_size || 15}`;
    } else {
      el["week-rank"].textContent = "—";
      el["group-size"].textContent = "";
    }
    animateNumber(el["week-seconds"], status.xp || 0);
    const members = state.standings?.standings || [];
    const leader = Number(members[0]?.xp) || Number(status.xp) || 0;
    const progress = leader > 0 ? Math.min(100, ((Number(status.xp) || 0) / leader) * 100) : 0;
    el["rank-progress"].style.width = `${progress}%`;
    const progressTrack = el["rank-progress"]?.parentElement;
    if (progressTrack) progressTrack.setAttribute("aria-valuenow", String(Math.round(progress)));
    el["rank-helper"].textContent = !status.group
      ? "等待本周参赛数据。"
      : status.rank === 1
        ? "你在小组第一，保持住。"
        : `继续${activityLabel()}，名次会往上走。`;
    renderDailyActions();
    renderEmberBadge();
  }

  function feedItems(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.items)) return payload.items;
    return [];
  }

  function renderFeedItem(item) {
    const author = item.author || {};
    const row = document.createElement("li");
    row.className = "feed-item";
    if (state.profile && author.id === state.profile.user_id) row.classList.add("is-me");
    row.dataset.eventId = String(item.id);

    const top = document.createElement("div");
    top.className = "feed-top";
    const avatar = document.createElement("span");
    avatar.className = "avatar feed-avatar";
    const fallback = document.createElement("span");
    fallback.className = "avatar-fallback";
    fallback.textContent = initialOf(author.name);
    const image = document.createElement("img");
    image.alt = "";
    image.hidden = true;
    avatar.append(fallback, image);
    const isMe = Boolean(state.profile && author.id === state.profile.user_id);
    paintAvatar(
      avatar,
      isMe ? state.profile?.avatar_url : author.avatar_url,
      author.name,
    );

    const copy = document.createElement("div");
    copy.className = "feed-copy";
    const authorLine = document.createElement("div");
    authorLine.className = "feed-author-line";
    const name = document.createElement("span");
    name.className = "feed-author";
    name.textContent = author.name || author.id || "—";
    authorLine.append(name);
    if (author.title) {
      const title = document.createElement("span");
      title.className = "title-chip";
      title.textContent = String(author.title);
      title.title = `称号：${author.title}`;
      authorLine.append(title);
    }
    if (isMe) {
      const meMark = document.createElement("span");
      meMark.className = "me-mark";
      meMark.textContent = "我";
      authorLine.append(meMark);
    }

    const body = document.createElement("p");
    body.className = "feed-body";
    body.textContent = String(item.body || "");

    const meta = document.createElement("div");
    meta.className = "feed-meta";
    const reactions = document.createElement("div");
    reactions.className = "feed-reactions";
    (item.reactions || []).forEach((reaction) => {
      const chip = document.createElement("span");
      chip.className = "feed-reaction";
      if (reaction.mine) chip.classList.add("is-mine");
      const emoji = document.createElement("span");
      emoji.className = "feed-reaction-emoji";
      emoji.textContent = String(reaction.emoji || "");
      chip.append(emoji);
      if (Number(reaction.count) > 1) {
        const count = document.createElement("span");
        count.className = "feed-reaction-count";
        count.textContent = String(reaction.count);
        chip.append(count);
      }
      chip.title = reaction.mine ? "你回应过" : `回应 ${reaction.emoji}`;
      reactions.append(chip);
    });
    const tags = document.createElement("div");
    tags.className = "feed-tags";
    (item.tags || []).forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "feed-tag";
      chip.textContent = Number(tag.count) > 1
        ? `${tag.tag} ${tag.count}`
        : String(tag.tag || "");
      tags.append(chip);
    });
    meta.append(reactions);
    if (tags.childElementCount) meta.append(tags);
    copy.append(authorLine, body, meta);

    const actions = document.createElement("div");
    actions.className = "feed-actions";
    const picker = document.createElement("div");
    picker.className = "feed-react-picker";
    picker.setAttribute("role", "group");
    picker.setAttribute("aria-label", `回应 ${author.name || "这条动态"}`);
    FEED_EMOJIS.forEach((emoji) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "feed-react-button";
      button.textContent = emoji;
      button.dataset.feedReact = "true";
      button.dataset.feedEventId = String(item.id);
      button.dataset.feedEmoji = emoji;
      button.setAttribute("aria-label", `回应 ${emoji}`);
      button.disabled = state.feedBusy;
      picker.append(button);
    });
    actions.append(picker);

    top.append(avatar, copy);
    row.append(top, actions);
    return row;
  }

  function renderFeedList(container, empty, items, emptyText, showEmpty = true) {
    if (!container) return;
    container.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      if (empty) {
        empty.hidden = !showEmpty;
        empty.textContent = emptyText;
      }
      return;
    }
    if (empty) empty.hidden = true;
    const fragment = document.createDocumentFragment();
    items.forEach((item) => fragment.append(renderFeedItem(item)));
    container.append(fragment);
  }

  function renderFeed() {
    const items = Array.isArray(state.feed) ? state.feed : [];
    const loaded = state.feedLoaded;
    renderFeedList(
      el["home-feed-list"],
      el["home-feed-empty"],
      loaded ? items.slice(0, 5) : [],
      "组里还没人动",
      loaded,
    );
    if (el["feed-loading"]) el["feed-loading"].hidden = loaded;
    renderFeedList(
      el["feed-list"],
      el["feed-empty"],
      loaded ? items : [],
      "组里还没人动",
      loaded,
    );
  }

  async function loadFeed() {
    try {
      const payload = await api("/v1/league/feed?limit=20");
      state.feed = feedItems(payload);
      state.feedLoaded = true;
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast(error.message || "动态加载失败。");
      }
    }
    renderFeed();
  }

  async function reactToFeed(eventId, emoji) {
    if (state.feedBusy || !state.token || !eventId) return;
    state.feedBusy = true;
    playClick();
    renderFeed();
    try {
      await api(`/v1/league/feed/${encodeURIComponent(eventId)}/reactions`, {
        method: "POST",
        json: { emoji },
      });
      state.feedLoaded = false;
      await loadFeed();
      showToast(`已回应 ${emoji}`);
      vibrate([12]);
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast(error.message || "回应失败。");
        sound.error();
      }
    } finally {
      state.feedBusy = false;
      renderFeed();
    }
  }

  function standingMeta(member) {
    const streak = Math.max(0, Number(member.streak) || 0);
    const bits = [member.checkin ? "今日已打卡" : "今日未打卡"];
    if (streak > 0) bits.push(`连续 ${streak} 天`);
    return bits.join(" · ");
  }

  function appendZoneDivider(fragment, label, variant) {
    const divider = document.createElement("li");
    divider.className = `zone-divider ${variant}`;
    divider.setAttribute("role", "presentation");
    divider.setAttribute("aria-hidden", "true");
    const line = document.createElement("span");
    line.className = "zone-divider-line";
    const text = document.createElement("span");
    text.className = "zone-divider-text";
    text.textContent = label;
    divider.append(line, text);
    fragment.append(divider);
  }

  function renderStandingsList(container, members, emptyElement, emptyText = "", options = {}) {
    if (!container) return;
    const previousRanks = container._rankMap instanceof Map ? container._rankMap : new Map();
    const firstRender = container.dataset.rendered !== "true";
    container.replaceChildren();
    if (!Array.isArray(members) || members.length === 0) {
      if (emptyElement) {
        emptyElement.hidden = false;
        if (emptyText) emptyElement.textContent = emptyText;
      }
      container._rankMap = new Map();
      container.dataset.rendered = "true";
      return;
    }
    if (emptyElement) emptyElement.hidden = true;
    const fragment = document.createDocumentFragment();
    const memberCount = members.length;
    const currentRanks = new Map();
    let demotionDividerAdded = false;
    members.forEach((member, index) => {
      const rankValue = Number(member.rank ?? index + 1);
      const memberKey = String(member.user_id || member.name || member.display_name || index);
      const previousRank = previousRanks.get(memberKey);
      const isPromotion = Boolean(options.zones) && rankValue <= 3;
      const demotionStart = Math.max(4, memberCount - 2);
      const isDemotion = Boolean(options.zones) && memberCount >= 6 && rankValue >= demotionStart;
      currentRanks.set(memberKey, rankValue);
      if (isDemotion && !demotionDividerAdded) {
        appendZoneDivider(fragment, "降级线", "is-demotion");
        demotionDividerAdded = true;
      }
      const row = document.createElement("li");
      row.className = "standing-row";
      row.dataset.userId = memberKey;
      if (member.is_me) row.classList.add("is-me");
      const frameId = resolveFrameId(member.frame_id || member.frame);
      if (frameId) {
        row.classList.add("has-frame");
        row.dataset.frame = frameId;
      }
      if (isPromotion) row.classList.add("is-promotion");
      if (isDemotion) row.classList.add("is-demotion");
      if (firstRender) row.classList.add("is-entering");
      const movement = Number.isFinite(previousRank) ? previousRank - rankValue : 0;
      if (!firstRender && movement > 0) row.classList.add("rank-moved-up");
      if (!firstRender && movement < 0) row.classList.add("rank-moved-down");
      row.style.setProperty("--i", String(Math.min(index, 12)));
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      const movementLabel = movement > 0
        ? `，上升 ${movement} 名`
        : movement < 0
          ? `，下降 ${Math.abs(movement)} 名`
          : "";
      row.setAttribute(
        "aria-label",
        `查看 ${member.name || member.display_name || member.user_id}，第 ${rankValue} 名${movementLabel}`,
      );
      const open = () => openUserDetail(member.user_id);
      row.addEventListener("click", open);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
      const rank = document.createElement("span");
      rank.className = "standing-rank";
      if (rankValue >= 1 && rankValue <= 3) {
        rank.classList.add("rank-medal", `rank-${rankValue}`);
        const medalLabel = ["金牌", "银牌", "铜牌"][rankValue - 1];
        rank.setAttribute("aria-label", `${medalLabel}，第 ${rankValue} 名`);
      }
      rank.textContent = String(rankValue);
      const avatar = document.createElement("span");
      avatar.className = "avatar standing-avatar";
      const fallback = document.createElement("span");
      fallback.className = "avatar-fallback";
      fallback.textContent = initialOf(member.name || member.display_name);
      const image = document.createElement("img");
      image.alt = "";
      image.hidden = true;
      avatar.append(fallback, image);
      paintAvatar(avatar, member.avatar_url, member.name || member.display_name, frameId);
      const copy = document.createElement("span");
      copy.className = "standing-copy";
      const nameLine = document.createElement("span");
      nameLine.className = "standing-name-line";
      const name = document.createElement("span");
      name.className = "standing-name";
      name.textContent = member.name || member.display_name || member.user_id;
      name.title = name.textContent;
      nameLine.append(name);
      if (member.title) {
        const titleChip = document.createElement("span");
        titleChip.className = "title-chip";
        titleChip.textContent = String(member.title);
        titleChip.title = `称号：${member.title}`;
        nameLine.append(titleChip);
      }
      if (member.is_me) {
        const meMark = document.createElement("span");
        meMark.className = "me-mark";
        meMark.textContent = "我";
        nameLine.append(meMark);
      }
      let zoneLabel = "";
      if (isPromotion && rankValue === 1) zoneLabel = "晋级区";
      if (isDemotion && rankValue === demotionStart) zoneLabel = "降级区";
      if (zoneLabel) {
        const zone = document.createElement("span");
        zone.className = `standing-zone${isDemotion ? " is-demotion" : ""}`;
        zone.textContent = zoneLabel;
        nameLine.append(zone);
      }
      const meta = document.createElement("span");
      meta.className = "standing-meta";
      meta.textContent = standingMeta(member, options);
      copy.append(nameLine);
      if (meta.textContent) copy.append(meta);
      const score = document.createElement("span");
      score.className = "standing-score";
      const strong = document.createElement("strong");
      strong.textContent = number(member.xp);
      const unit = document.createElement("span");
      unit.textContent = "XP";
      score.append(strong, unit);
      row.append(rank, avatar, copy, score);
      fragment.append(row);
      if (isPromotion && rankValue === 3) {
        appendZoneDivider(fragment, "晋级线", "is-promotion");
      }
    });
    container.append(fragment);
    container._rankMap = currentRanks;
    container.dataset.rendered = "true";
  }

  function centerTierRail() {
    const container = el["league-tier-slots"];
    if (!container) return false;
    const current = container.querySelector(".league-tier-slot.is-current");
    if (!current || container.clientWidth <= 0) return false;
    const maxScroll = Math.max(0, container.scrollWidth - container.clientWidth);
    const currentIndex = Array.prototype.indexOf.call(container.children, current);
    let target;
    if (currentIndex <= 0) {
      target = 0;
    } else if (currentIndex === container.children.length - 1) {
      target = maxScroll;
    } else {
      const containerBox = container.getBoundingClientRect();
      const currentBox = current.getBoundingClientRect();
      const offset =
        (currentBox.left + currentBox.width / 2) -
        (containerBox.left + containerBox.width / 2);
      target = Math.max(0, Math.min(maxScroll, container.scrollLeft + offset));
    }
    if (typeof container.scrollTo === "function") {
      container.scrollTo({ left: target, behavior: "auto" });
    } else {
      container.scrollLeft = target;
    }
    state.tierRailNeedsCenter = false;
    return true;
  }

  function setupTierRailScroll() {
    const container = el["league-tier-slots"];
    if (!container) return;
    container.addEventListener("wheel", (event) => {
      if (container.scrollWidth <= container.clientWidth) return;
      if (Math.abs(event.deltaX) >= Math.abs(event.deltaY)) return;
      const maxScroll = container.scrollWidth - container.clientWidth;
      const atStart = container.scrollLeft <= 0 && event.deltaY < 0;
      const atEnd = container.scrollLeft >= maxScroll - 1 && event.deltaY > 0;
      if (atStart || atEnd) return;
      const delta = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
      event.preventDefault();
      container.scrollLeft = Math.max(
        0,
        Math.min(maxScroll, container.scrollLeft + delta),
      );
    }, { passive: false });
  }

  function updateTierRailSummary(currentTier) {
    const currentIndex = Math.max(0, TIER_ORDER.indexOf(currentTier));
    document.documentElement.style.setProperty(
      "--rail-progress",
      `${(currentIndex / (TIER_ORDER.length - 1)) * 100}%`,
    );
    if (el["tier-rail-summary"]) {
      el["tier-rail-summary"].textContent = `已解锁 ${currentIndex + 1} / ${TIER_ORDER.length}`;
    }
  }

  function renderTierSlots(currentTier, theme = profileIconTheme()) {
    const container = el["league-tier-slots"];
    if (!container) return;
    const safeTier = TIER_ORDER.includes(currentTier) ? currentTier : TIER_ORDER[0];
    const safeTheme = normalizeIconTheme(theme);
    const currentIndex = Math.max(0, TIER_ORDER.indexOf(safeTier));
    updateTierRailSummary(safeTier);
    const renderKey = `${safeTier}|${safeTheme}`;
    if (container.dataset.renderKey === renderKey && container.children.length === TIER_ORDER.length) {
      return;
    }
    const previousTier = state.tierRailTier;
    const previousScroll = container.scrollLeft;
    const previousMaxScroll = Math.max(0, container.scrollWidth - container.clientWidth);
    const scrollRatio = previousMaxScroll > 0 ? previousScroll / previousMaxScroll : 0;
    const railHidden = container.clientWidth <= 0;
    const shouldCenter = previousTier !== safeTier || state.tierRailNeedsCenter;
    container.replaceChildren();
    container.setAttribute("aria-label", "段位进度，左右滑动查看");
    TIER_ORDER.forEach((slotTier) => {
      const info = tierInfo(slotTier);
      const isCurrent = info.order === currentIndex;
      const isReached = info.order < currentIndex;
      const isFogged = info.order > currentIndex;
      const slot = document.createElement("div");
      slot.className = "league-tier-slot";
      slot.dataset.tier = info.slug;
      slot.setAttribute("role", "listitem");
      if (isCurrent) {
        slot.classList.add("is-current");
        slot.setAttribute("aria-current", "step");
      }
      if (isReached) slot.classList.add("is-reached");
      if (isFogged) slot.classList.add("is-fogged");
      if (isFogged) {
        slot.title = "未解锁";
        slot.setAttribute("aria-label", "未解锁段位");
        slot.setAttribute("aria-disabled", "true");
      } else {
        const prefix = isCurrent ? "当前段位" : "已达成段位";
        slot.title = `${prefix}：${tierLabel(slotTier)}`;
        slot.setAttribute("aria-label", `${prefix}：${tierLabel(slotTier)}`);
      }
      const image = document.createElement("img");
      image.className = "league-tier-slot-icon";
      image.src = tierIconUrl(info.slug, safeTheme);
      image.alt = "";
      image.width = 1024;
      image.height = 1024;
      image.loading = "lazy";
      image.decoding = "async";
      if (isFogged) image.setAttribute("aria-hidden", "true");
      const label = document.createElement("span");
      label.className = "league-tier-slot-label";
      label.textContent = isFogged ? "未解锁" : tierLabel(slotTier);
      slot.append(image, label);
      container.append(slot);
    });
    container.dataset.renderKey = renderKey;
    state.tierRailTier = safeTier;
    window.requestAnimationFrame(() => {
      if (shouldCenter || railHidden) {
        state.tierRailNeedsCenter = true;
        centerTierRail();
        return;
      }
      const maxScroll = Math.max(0, container.scrollWidth - container.clientWidth);
      container.scrollLeft = scrollRatio * maxScroll;
    });
  }

  function renderLeagueHero() {
    const payload = state.standings || {};
    const group = payload.group || state.status?.group || null;
    const tier = group?.tier || state.status?.tier || "Bronze";
    const info = tierInfo(tier);
    const theme = profileIconTheme();
    if (el["league-tier-icon"]) {
      el["league-tier-icon"].src = tierIconUrl(info.slug, theme);
      el["league-tier-icon"].alt = `${tierLabel(tier)}段位图标`;
    }
    if (el["league-tier-name"]) el["league-tier-name"].textContent = tierLabel(tier);
    if (el["league-group-meta"]) {
      el["league-group-meta"].textContent = group
        ? `小组${tierLabel(tier)} · ${groupCode(group)}`
        : "等待数据";
    }
    if (el["league-days-left"]) {
      const weekStart = payload.week_start || state.league?.week_start;
      el["league-days-left"].textContent = `本周剩余 ${remainingWeekDays(weekStart)} 天`;
    }
    renderTierSlots(tier);
  }

  function homeBoardMembers(members) {
    if (!Array.isArray(members)) return [];
    if (members.length <= 6) return members;
    const top = members.slice(0, 5);
    const me = members.find((member) => member.is_me);
    if (me && !top.some((member) => member.user_id === me.user_id)) top.push(me);
    return top;
  }

  function renderLeagueTab() {
    const friends = state.leagueTab === "friends";
    el["league-tab-group"].classList.toggle("is-active", !friends);
    el["league-tab-friends"].classList.toggle("is-active", friends);
    el["league-tab-group"].setAttribute("aria-selected", String(!friends));
    el["league-tab-friends"].setAttribute("aria-selected", String(friends));
  }

  function renderStandings() {
    const payload = state.standings;
    if (!payload) return;
    const groupMembers = payload.standings || [];
    const hasGroup = Boolean(payload.group);
    const waiting = "等待数据";
    renderLeagueHero();
    renderStandingsList(
      el["home-standings"],
      homeBoardMembers(groupMembers),
      el["home-standings-empty"],
      hasGroup ? "" : waiting,
      {},
    );
    el["home-group-pill"].textContent = hasGroup
      ? `${payload.group_size || groupMembers.length} 人`
      : waiting;
    renderLeagueTab();
    if (state.leagueTab === "friends") {
      const friends = state.friendsStandings?.members || [];
      renderStandingsList(
        el["league-standings"],
        friends,
        el["league-standings-empty"],
        state.friendsStandings
          ? "还没有关注的人，去附近的人看看"
          : "正在载入好友榜…",
        { zones: false },
      );
      el["league-count"].textContent = `${friends.length} 人`;
      el["league-group-name"].textContent = "好友榜";
      el["league-subtitle"].textContent = "跨段位查看你关注的人";
      el["league-snapshot"].textContent = "本周";
      return;
    }
    renderStandingsList(
      el["league-standings"],
      groupMembers,
      el["league-standings-empty"],
      hasGroup ? "暂时没有榜单数据。" : waiting,
      { zones: true },
    );
    el["league-count"].textContent = hasGroup
      ? `${payload.group_size || groupMembers.length} 人`
      : waiting;
    el["league-group-name"].textContent = hasGroup
      ? groupLabel(payload.group)
      : waiting;
    el["league-subtitle"].textContent = hasGroup
      ? "只显示你所在的小组"
      : "等待本周参赛名单";
    el["league-snapshot"].textContent = hasGroup
      ? snapshotLabel(payload)
      : waiting;
  }

  async function loadFriendsStandings() {
    if (!state.token) return;
    try {
      state.friendsStandings = await api("/v1/me/friends/standings");
      renderStandings();
    } catch (error) {
      state.friendsStandings = { members: [] };
      renderStandings();
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast("好友榜加载失败。");
      }
    }
  }

  function safeExternalUrl(value) {
    if (!value) return null;
    try {
      const parsed = new URL(String(value));
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
    } catch (_) {
      return null;
    }
  }

  function appendExternalLink(container, url, label) {
    const safe = safeExternalUrl(url);
    if (!safe) return;
    const link = document.createElement("a");
    link.className = "wakatime-link";
    link.href = safe;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    container.append(link);
  }

  function socialProfileUrl(kind, username) {
    const origin = "https:" + "//";
    const paths = {
      twitter: "twitter.com/",
      github: "github.com/",
      linkedin: "linkedin.com/in/",
    };
    if (!paths[kind] || !username) return null;
    return origin + paths[kind] + encodeURIComponent(String(username));
  }

  function collectionEntryField(entry) {
    if (!entry?.slot) return "title_id";
    if (entry.slot === "frame") return "frame_id";
    if (entry.slot === "backdrop") return "backdrop_id";
    return "badge_accent_id";
  }

  function collectionSlotLabel(slot) {
    return { frame: "边框", backdrop: "背景", badge_accent: "冠军环" }[slot] || "物品";
  }

  function renderCollectionOption(entry) {
    const field = collectionEntryField(entry);
    const item = document.createElement("div");
    item.className = "collection-option";
    if (entry.equipped) item.classList.add("is-equipped");
    const copy = document.createElement("div");
    copy.className = "collection-copy";
    const name = document.createElement("strong");
    name.textContent = String(entry.name || entry.id);
    const condition = document.createElement("span");
    condition.textContent = entry.description ? String(entry.description) : "";
    copy.append(name, condition);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary-button compact";
    button.dataset.equipField = field;
    button.dataset.equipId = String(entry.id);
    button.textContent = entry.equipped ? "已装备" : "装备";
    button.disabled = Boolean(entry.equipped);
    button.setAttribute("aria-pressed", String(Boolean(entry.equipped)));
    item.append(copy, button);
    return item;
  }

  function renderCollectionGroup(container, entries) {
    if (!container) return;
    container.replaceChildren();
    entries.forEach((entry) => container.append(renderCollectionOption(entry)));
  }

  function renderCollection() {
    const collection = state.collection;
    if (!collection) return;
    const titles = Array.isArray(collection.titles) ? collection.titles : [];
    const items = Array.isArray(collection.items) ? collection.items : [];
    renderCollectionGroup(el["collection-titles"], titles);
    renderCollectionGroup(el["collection-items"], items);
    if (el["collection-empty"]) {
      el["collection-empty"].hidden = titles.length + items.length > 0;
    }
    const equipped = collection.equipped || {};
    const names = [];
    const title = titles.find((entry) => entry.id === equipped.title_id);
    if (title) names.push(`称号 ${title.name}`);
    items.forEach((entry) => {
      if ([
        equipped.frame_id,
        equipped.backdrop_id,
        equipped.badge_accent_id,
      ].includes(entry.id)) {
        names.push(`${collectionSlotLabel(entry.slot)} ${entry.name}`);
      }
    });
    if (el["collection-equipped"]) {
      el["collection-equipped"].textContent = names.length ? names.join(" · ") : "未装备";
    }
  }

  async function equipCollection(field, id) {
    if (!field || !id || !state.token) return;
    try {
      await api("/v1/me/loadout", {
        method: "PATCH",
        json: { [field]: id },
      });
      state.collection = await api("/v1/me/collection");
      state.collectionLoaded = true;
      renderCollection();
      showToast("装备已更新。");
      playClick();
      await refreshCore();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast(error.message || "装备失败，请确认已解锁。");
        sound.error();
      }
    }
  }

  function renderMeOverview() {
    const status = state.status;
    const detail = state.meDetail;
    if (!status) return;
    el["me-week-xp"].textContent = `${number(status.xp)} XP`;
    el["me-tier"].textContent = groupLabel(status.group);
    el["me-streak"].textContent = `${number(currentStreak(status))} 天`;
    el["me-today-xp"].textContent = `${number(status.today_xp)} XP`;
    el["me-following-count"].textContent = detail
      ? number(detail.following_count)
      : "—";
    el["me-followers-count"].textContent = detail
      ? number(detail.followers_count)
      : "—";
  }

  function renderUserDetail() {
    const detail = state.userDetail;
    if (!detail) return;
    el["user-loading"].hidden = true;
    el["user-error"].hidden = true;
    el["user-content"].hidden = false;
    const name = detail.display_name || detail.user_id;
    paintAvatar(
      el["user-detail-avatar"],
      detail.avatar_url,
      name,
      detail.frame_id || detail.frame,
    );
    const isMe = Boolean(detail.is_me) || detail.user_id === state.profile?.user_id;
    el["user-detail-name"].textContent = name;
    el["user-detail-handle"].textContent = `@${detail.user_id}`;
    el["user-detail-joined"].textContent = detail.week_start
      ? `本周联赛 · ${detail.week_start}`
      : "本周联赛";
    const activity = String(detail.activity_label || "").trim();
    el["user-detail-activity"].hidden = !activity;
    el["user-detail-activity"].textContent = activity;
    if (el["user-detail-title"]) {
      el["user-detail-title"].hidden = !detail.equipped_title;
      el["user-detail-title"].textContent = detail.equipped_title
        ? `称号 ${detail.equipped_title}`
        : "";
    }
    const followButton = el["user-follow-button"];
    followButton.hidden = isMe;
    followButton.textContent = detail.is_following ? "已关注" : "关注";
    followButton.classList.toggle("is-following", Boolean(detail.is_following));
    el["user-following-count"].textContent = number(detail.following_count);
    el["user-followers-count"].textContent = number(detail.followers_count);
    const theme = detailIconTheme(detail);
    const weekXp = Number(detail.xp) || 0;
    el["user-week-minutes"].textContent = number(weekXp);
    el["user-week-total"].textContent = `${number(weekXp)} XP`;
    if (el["user-detail-tier-icon"]) {
      el["user-detail-tier-icon"].src = tierIconUrl(tierKey(detail.tier), theme);
      el["user-detail-tier-icon"].alt = `${tierLabel(detail.tier)}段位图标`;
    }
    el["user-detail-tier"].textContent = tierLabel(detail.tier);
    el["user-detail-group"].textContent = isMe && state.status?.group
      ? groupLabel(state.status.group)
      : detail.group_id
        ? `小组 #${detail.group_id}`
        : "—";
    el["user-stat-rank"].textContent = detail.rank
      ? `第 ${detail.rank} 名 / ${detail.group_size || 15}`
      : "—";
    el["user-stat-streak"].textContent = `${number(detail.streak)} 天`;
    el["user-stat-checkin"].textContent = detail.checkin ? "今日已打卡" : "今日未打卡";
    el["user-stat-tier"].textContent = tierLabel(detail.tier);
  }

  async function loadUserDetail(userId) {
    el["user-loading"].hidden = false;
    el["user-error"].hidden = true;
    el["user-content"].hidden = true;
    try {
      state.userDetail = await api(`/v1/users/${encodeURIComponent(userId)}`);
      renderUserDetail();
    } catch (error) {
      state.userDetail = null;
      el["user-loading"].hidden = true;
      el["user-content"].hidden = true;
      el["user-error"].hidden = false;
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast("用户加载失败。");
      }
    }
  }

  async function openUserDetail(userId) {
    const target = String(userId || "").trim();
    if (!target) return;
    if (state.page !== "user") state.detailReturnPage = state.page;
    state.detailUserId = target;
    state.userDetail = null;
    showPage("user");
    await loadUserDetail(target);
  }

  function updateUserAfterFollow(targetId, isFollowing, counts = {}) {
    if (state.userDetail && state.userDetail.user_id === targetId) {
      state.userDetail.is_following = isFollowing;
      if (Number.isFinite(Number(counts.followers_count))) {
        state.userDetail.followers_count = Number(counts.followers_count);
      } else {
        state.userDetail.followers_count = Math.max(
          0,
          Number(state.userDetail.followers_count || 0) + (isFollowing ? 1 : -1),
        );
      }
      renderUserDetail();
    }
    if (state.meDetail) {
      if (Number.isFinite(Number(counts.my_following_count))) {
        state.meDetail.following_count = Number(counts.my_following_count);
      } else {
        state.meDetail.following_count = Math.max(
          0,
          Number(state.meDetail.following_count || 0) + (isFollowing ? 1 : -1),
        );
      }
      renderMeOverview();
    }
    if (Array.isArray(state.people)) {
      const person = state.people.find((item) => item.user_id === targetId);
      if (person) person.is_following = isFollowing;
      renderPeople();
    }
    state.friendsStandings = null;
  }

  async function setFollowState(targetId, shouldFollow) {
    try {
      let payload = {};
      if (shouldFollow) {
        payload = await api(`/v1/me/follows/${encodeURIComponent(targetId)}`, { method: "POST" });
      } else {
        await api(`/v1/me/follows/${encodeURIComponent(targetId)}`, { method: "DELETE" });
      }
      updateUserAfterFollow(targetId, shouldFollow, payload || {});
      showToast(shouldFollow ? "已关注。" : "已取消关注。");
      playClick();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast(error.message || "关注操作失败。");
        sound.error();
      }
    }
  }

  function renderPeople() {
    const list = el["people-list"];
    if (!list) return;
    list.replaceChildren();
    const people = Array.isArray(state.people) ? state.people : [];
    el["people-loading"].hidden = true;
    el["people-error"].hidden = true;
    el["people-empty"].hidden = people.length !== 0;
    people.forEach((person) => {
      const row = document.createElement("li");
      row.className = "person-row";
      const main = document.createElement("button");
      main.className = "person-main";
      main.type = "button";
      main.addEventListener("click", () => openUserDetail(person.user_id));
      const avatar = document.createElement("span");
      avatar.className = "avatar person-avatar";
      const fallback = document.createElement("span");
      fallback.className = "avatar-fallback";
      fallback.textContent = initialOf(person.display_name);
      const image = document.createElement("img");
      image.alt = "";
      image.hidden = true;
      avatar.append(fallback, image);
      paintAvatar(avatar, person.avatar_url, person.display_name);
      const copy = document.createElement("span");
      copy.className = "person-copy";
      const name = document.createElement("strong");
      name.textContent = person.display_name || person.user_id;
      const meta = document.createElement("span");
      const bits = [];
      if (person.activity_label) bits.push(person.activity_label);
      if (person.group_id) bits.push(groupLabel(person.group_id));
      else if (person.tier) bits.push(tierLabel(person.tier));
      bits.push(`${number(person.xp)} XP`);
      meta.textContent = bits.join(" · ");
      copy.append(name, meta);
      main.append(avatar, copy);
      const followButton = document.createElement("button");
      followButton.type = "button";
      followButton.className = `follow-button${person.is_following ? " is-following" : ""}`;
      followButton.textContent = person.is_following ? "已关注" : "关注";
      followButton.addEventListener("click", async (event) => {
        event.stopPropagation();
        followButton.disabled = true;
        await setFollowState(person.user_id, !person.is_following);
        followButton.disabled = false;
      });
      row.append(main, followButton);
      list.append(row);
    });
  }

  async function loadPeople() {
    el["people-loading"].hidden = false;
    el["people-empty"].hidden = true;
    el["people-error"].hidden = true;
    try {
      const people = await api("/v1/discover/people");
      state.people = Array.isArray(people) ? people : [];
      state.peopleLoaded = true;
      renderPeople();
    } catch (error) {
      state.people = [];
      el["people-loading"].hidden = true;
      el["people-empty"].hidden = true;
      el["people-error"].hidden = false;
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast("附近的人加载失败。");
      }
    }
  }

  function renderSound() {
    document.body.classList.toggle("sound-muted", !state.sound);
    el["sound-button"].setAttribute("aria-pressed", String(state.sound));
    el["sound-button"].setAttribute("aria-label", state.sound ? "关闭声音" : "开启声音");
    el["sound-toggle-row"].setAttribute("aria-checked", String(state.sound));
    el["haptics-toggle-row"].setAttribute("aria-checked", String(state.haptics));
  }

  function renderHistory() {
    if (!el["history-list"]) return;
    el["history-list"].replaceChildren();
    const history = state.history || [];
    el["history-empty"].hidden = history.length !== 0;
    el["history-loading"].hidden = true;
    el["history-error"].hidden = true;
    history.forEach((week) => {
      const card = document.createElement("article");
      card.className = "history-card";
      const head = document.createElement("div");
      head.className = "history-card-head";
      const weekLabel = document.createElement("span");
      weekLabel.className = "history-week";
      weekLabel.textContent = week.week_start
        ? `${week.week_start} 当周`
        : "已结算周";
      const tier = document.createElement("span");
      tier.className = "pill";
      tier.textContent = tierLabel(week.tier);
      head.append(weekLabel, tier);
      const title = document.createElement("h3");
      title.textContent = `第 ${week.rank || "—"} 名 · ${tierLabel(week.tier)}`;
      const meta = document.createElement("p");
      meta.textContent = `${number(week.xp)} XP · ${
        week.promoted ? "晋级" : week.demoted ? "降级" : "留在本段"
      }${week.group_id ? ` · 小组 #${week.group_id}` : ""}`;
      card.append(head, title, meta);
      const badges = document.createElement("div");
      badges.className = "history-badges";
      if (week.promoted) {
        const badge = document.createElement("span");
        badge.className = "history-badge up";
        badge.textContent = "晋级";
        badges.append(badge);
      }
      if (week.demoted) {
        const badge = document.createElement("span");
        badge.className = "history-badge down";
        badge.textContent = "降级";
        badges.append(badge);
      }
      if (Number(week.repaired_days) > 0) {
        const badge = document.createElement("span");
        badge.className = "history-badge up";
        badge.textContent = `补签 ${number(week.repaired_days)} 天`;
        badges.append(badge);
      }
      if (Number(week.clean_checkins) > 0) {
        const badge = document.createElement("span");
        badge.className = "history-badge up";
        badge.textContent = `干净打卡 ${number(week.clean_checkins)} 天`;
        badges.append(badge);
      }
      if (badges.childElementCount) card.append(badges);
      el["history-list"].append(card);
    });
  }

  function emberReasonLabel(reason) {
    const labels = {
      weekly_xp: "本周 XP 奖励",
      repair: "补签消耗",
      season_reset: "赛季重置",
      adjustment: "调整",
    };
    return labels[reason] || reason || "变动";
  }

  function emberTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "Asia/Shanghai",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  }

  function renderEmberBadge() {
    if (!el["home-ember-balance"]) return;
    const balance = state.embers?.balance ?? state.status?.embers?.balance ?? 0;
    el["home-ember-balance"].textContent = number(balance);
  }

  function renderEmbers() {
    const embers = state.embers;
    if (!embers) {
      renderEmberBadge();
      return;
    }
    const balance = Number(embers.balance) || 0;
    const cap = Number(embers.cap) || 3;
    el["ember-balance"].textContent = number(balance);
    el["ember-cap"].textContent = `/ ${number(cap)}`;
    el["ember-earned"].textContent = number(embers.earned_this_week);
    el["ember-week-xp"].textContent = `${number(embers.week_xp)} XP`;
    el["ember-cap-stat"].textContent = number(cap);
    el["ember-cap-rule"].textContent = `最多持有 ${number(cap)} 枚。`;
    el["ember-hint"].textContent = balance < cap
      ? `每 2,000 XP 获得 1 枚，每周最多 2 枚；当前还能持有 ${number(cap - balance)} 枚。`
      : `已达到持有上限 ${number(cap)} 枚，补签会先消耗余额。`;
    const ledger = Array.isArray(embers.ledger) ? embers.ledger : [];
    el["ember-ledger"].replaceChildren();
    el["ember-ledger-count"].textContent = `${ledger.length} 条`;
    el["ember-ledger-empty"].hidden = ledger.length !== 0;
    el["ember-ledger-loading"].hidden = true;
    ledger.forEach((item) => {
      const row = document.createElement("li");
      row.className = "ember-ledger-row";
      const delta = Number(item.delta) || 0;
      const copy = document.createElement("span");
      copy.className = "ember-ledger-copy";
      const reason = document.createElement("strong");
      reason.textContent = emberReasonLabel(item.reason);
      const meta = document.createElement("span");
      meta.textContent = `${emberTime(item.created_at)} · 余额 ${number(item.balance_after)}`;
      copy.append(reason, meta);
      const amount = document.createElement("span");
      amount.className = `ember-ledger-delta ${delta >= 0 ? "is-up" : "is-down"}`;
      amount.textContent = `${delta >= 0 ? "+" : ""}${number(delta)}`;
      row.append(copy, amount);
      el["ember-ledger"].append(row);
    });
    renderEmberBadge();
  }

  async function loadEmbers() {
    if (!state.token) return;
    if (el["ember-ledger-loading"]) el["ember-ledger-loading"].hidden = false;
    if (el["ember-ledger-empty"]) el["ember-ledger-empty"].hidden = true;
    try {
      state.embers = await api("/v1/me/embers");
      state.embersLoaded = true;
      renderEmbers();
      renderDailyActions();
    } catch (error) {
      if (el["ember-ledger-loading"]) el["ember-ledger-loading"].hidden = true;
      if (el["ember-ledger-empty"]) el["ember-ledger-empty"].hidden = false;
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast("余烬加载失败。");
      }
    }
  }

  function renderDailyActions() {
    if (!el["repair-box"]) return;
    const candidates = Array.isArray(state.repairCandidates) ? state.repairCandidates : [];
    const balance = Number(state.embers?.balance ?? state.status?.embers?.balance ?? 0);
    const previous = el["repair-date"].value;
    el["repair-date"].replaceChildren();
    candidates.forEach((day) => {
      const option = document.createElement("option");
      option.value = day.date;
      option.textContent = `${formatDayLabel(day.date)} · ${number(day.xp)} XP`;
      el["repair-date"].append(option);
    });
    if (previous && candidates.some((day) => day.date === previous)) {
      el["repair-date"].value = previous;
    }
    const disabled = candidates.length === 0 || balance < 1 || state.repairBusy;
    el["repair-button"].disabled = disabled;
    el["repair-box"].classList.toggle("is-empty", candidates.length === 0);
    if (state.repairBusy) {
      el["repair-hint"].textContent = "正在补签，请稍候…";
    } else if (!candidates.length) {
      el["repair-hint"].textContent = "最近没有可补日期，只有未满 100 XP 的最近七天记录可补。";
    } else if (balance < 1) {
      el["repair-hint"].textContent = "余烬不足，先累积本周 XP 获得余烬。";
    } else {
      el["repair-hint"].textContent = `可补 ${number(candidates.length)} 天，补签 1 天消耗 1 枚余烬。`;
    }
  }

  function repairIdempotencyKey(date) {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `repair-${date}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  async function refreshAfterRepair() {
    const [status, standings, embers, collection] = await Promise.all([
      api("/v1/me/status"),
      api("/v1/league/standings"),
      api("/v1/me/embers"),
      api("/v1/me/collection"),
    ]);
    state.status = status;
    state.standings = standings;
    state.embers = embers;
    state.embersLoaded = true;
    state.collection = collection;
    state.collectionLoaded = true;
    renderAll();
    await loadRepairOptions();
  }

  async function repairSelectedDay() {
    if (state.repairBusy) return;
    const date = el["repair-date"].value;
    if (!date) return;
    const balance = Number(state.embers?.balance ?? state.status?.embers?.balance ?? 0);
    if (balance < 1) {
      showToast("余烬不足，先累积本周 XP 获得余烬。");
      return;
    }
    if (!window.confirm(`消耗 1 枚余烬补签 ${formatDayLabel(date)}？`)) return;
    state.repairBusy = true;
    setBusy(el["repair-button"], true);
    renderDailyActions();
    try {
      const payload = await api("/v1/me/repair", {
        method: "POST",
        json: { date, idempotency_key: repairIdempotencyKey(date) },
      });
      showToast(payload.duplicate
        ? "这一天已经补签过了。"
        : `补签成功，剩余 ${number(payload.balance)} 枚余烬。`);
      playClick();
      await refreshAfterRepair();
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        const detail = error instanceof ApiError ? error.message : "补签失败，请稍后重试。";
        showToast(detail || "补签失败，请稍后重试。");
        setSyncStatus("补签失败", "error");
        sound.error();
      }
    } finally {
      state.repairBusy = false;
      setBusy(el["repair-button"], false);
      renderDailyActions();
    }
  }

  function renderAll() {
    renderProfile();
    renderHome();
    renderFeed();
    renderStandings();
    renderMeOverview();
    renderCollection();
    renderEmbers();
    renderSound();
  }

  function applyProgressFeedback(previous, current) {
    if (!previous || !current) return;
    const todayBefore = Number(previous.today_xp) || 0;
    const todayAfter = Number(current.today_xp) || 0;
    const todayDelta = todayAfter - todayBefore;
    const weekDelta = (Number(current.xp) || 0) - (Number(previous.xp) || 0);
    const previousRank = Number(previous.rank) || 0;
    const currentRank = Number(current.rank) || 0;
    const rankDelta = previousRank && currentRank ? previousRank - currentRank : 0;
    const streakBefore = currentStreak(previous);
    const streakAfter = currentStreak(current);
    const streakDelta = streakAfter - streakBefore;
    const previousTier = TIER_META[previous.tier]?.order ?? -1;
    const currentTier = TIER_META[current.tier]?.order ?? -1;
    const tierUp = currentTier > previousTier;
    const checkinMoment = !isCheckedIn(previous) && isCheckedIn(current);
    const firstPlaceMoment = previousRank > 1 && currentRank === 1;
    const hasVisibleChange = todayDelta !== 0 || weekDelta !== 0 || rankDelta !== 0
      || streakDelta !== 0 || tierUp || checkinMoment;

    if (!hasVisibleChange) return;
    cancelTransientFeedback();

    if (todayDelta > 0) {
      showDelta(el["xp-delta"], `+${number(todayDelta)} XP`, "is-up");
      pulseClass(el["ring-card"], "is-awarding", 1250);
    }
    if (rankDelta !== 0) {
      const text = `${rankDelta > 0 ? "↑" : "↓"} ${Math.abs(rankDelta)}`;
      showDelta(el["rank-change"], text, rankDelta > 0 ? "is-up" : "is-down");
      pulseClass(
        el["rank-card"],
        rankDelta > 0 ? "is-rank-up" : "is-rank-down",
        1400,
      );
      announceStatus(rankDelta > 0
        ? `小组名次上升 ${rankDelta} 名，现在第 ${currentRank} 名。`
        : `小组名次下降 ${Math.abs(rankDelta)} 名，现在第 ${currentRank} 名。`);
    }
    if (streakDelta > 0) {
      showDelta(el["streak-delta"], `+${number(streakDelta)} 天`, "is-up");
      pulseClass(document.querySelector(".streak-card"), "is-flaring", 1400);
    }

    if (tierUp) {
      showMoment("段位晋级", `晋级到${tierLabel(current.tier)}`, "新的段位已经点亮，去段位滑轨看看下一步。", "tier");
      runConfetti(1.05);
      sound.promotion();
      showToast(`晋级到${tierLabel(current.tier)}！`);
      return;
    }
    if (checkinMoment) {
      showMoment("今日打卡", "火焰续上了", `连续 ${streakAfter} 天，今天的进度已经锁定。`, "checkin");
      runConfetti(0.72);
      sound.checkin();
      showToast("今日打卡完成，火焰续上了。");
      return;
    }
    if (firstPlaceMoment) {
      showMoment("小组登顶", "现在小组第一", "这一轮的领先属于你，继续保持。", "first");
      runConfetti(0.85);
      sound.first();
      showToast("小组第一！这一轮属于你。");
    }
  }

  async function loadDashboard({ first = false } = {}) {
    const [profile, status, league, standings, embers, collection, feedPayload] = await Promise.all([
      api("/v1/me/profile"),
      api("/v1/me/status"),
      api("/v1/me/league"),
      api("/v1/league/standings"),
      api("/v1/me/embers"),
      api("/v1/me/collection"),
      api("/v1/league/feed?limit=20").catch(() => null),
    ]);
    const previousStatus = state.status;
    state.profile = profile;
    state.status = status;
    state.league = league;
    state.standings = standings;
    state.embers = embers;
    state.embersLoaded = true;
    state.collection = collection;
    state.collectionLoaded = true;
    state.feed = feedItems(feedPayload);
    state.feedLoaded = feedPayload !== null;
    renderAll();
    try {
      state.meDetail = await api(`/v1/users/${encodeURIComponent(profile.user_id)}`);
    } catch (error) {
      state.meDetail = null;
      if (!(error instanceof ApiError && error.status === 401)) {
        // The profile page still works if the optional overview cannot load.
      }
    }
    renderMeOverview();
    await loadRepairOptions();
    if (!first) applyProgressFeedback(previousStatus, status);
    setSyncStatus(first ? "已进入联赛" : "已更新");
  }

  async function loadRepairOptions() {
    const status = state.status;
    if (!status?.week_start) return;
    const previousWeek = shiftIsoDate(status.week_start, -7);
    try {
      const [current, previous] = await Promise.all([
        api(`/v1/me/checkins?week_start=${encodeURIComponent(status.week_start)}`),
        api(`/v1/me/checkins?week_start=${encodeURIComponent(previousWeek)}`),
      ]);
      const days = [
        ...(Array.isArray(previous?.days) ? previous.days : []),
        ...(Array.isArray(current?.days) ? current.days : []),
      ];
      const today = localDateIso(status.updated_at || new Date().toISOString());
      const earliest = shiftIsoDate(today, -7);
      const seen = new Set();
      state.checkins = { current, previous };
      state.repairCandidates = days
        .filter((day) => {
          const date = String(day?.date || "");
          const xpValue = Number(day?.xp) || 0;
          if (!date || date >= today || date < earliest) return false;
          if (day.checked_in) return false;
          if (xpValue <= 0 || xpValue >= requiredXp(status)) return false;
          if (seen.has(date)) return false;
          seen.add(date);
          return true;
        })
        .sort((left, right) => String(right.date).localeCompare(String(left.date)));
    } catch (error) {
      state.checkins = null;
      state.repairCandidates = [];
      if (!(error instanceof ApiError && error.status === 401)) {
        // Repair is optional; the rest of the dashboard remains usable.
      }
    }
    renderDailyActions();
  }

  async function refreshCore({ announce = false } = {}) {
    if (!state.token || state.polling) return false;
    state.polling = true;
    try {
      const [status, standings, embers, collection, feedPayload] = await Promise.all([
        api("/v1/me/status"),
        api("/v1/league/standings"),
        api("/v1/me/embers"),
        api("/v1/me/collection"),
        api("/v1/league/feed?limit=20").catch(() => null),
      ]);
      const previousStatus = state.status;
      state.status = status;
      state.standings = standings;
      state.embers = embers;
      state.embersLoaded = true;
      state.collection = collection;
      state.collectionLoaded = true;
      if (feedPayload !== null) {
        state.feed = feedItems(feedPayload);
        state.feedLoaded = true;
      }
      if (state.profile) {
        state.profile.display_name = status.display_name;
        state.profile.icon_theme = normalizeIconTheme(status.icon_theme);
      }
      renderAll();
      applyProgressFeedback(previousStatus, status);
      state.offlineToastShown = false;
      setSyncStatus("已更新");
      if (announce) {
        showToast("已刷新");
        announceStatus("联赛数据已刷新。");
      }
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return false;
      setSyncStatus("刷新失败", "error");
      if (!state.offlineToastShown) {
        state.offlineToastShown = true;
        showToast("网络不太稳，稍后再试。");
      }
      if (announce) announceStatus("刷新失败，正在显示上一次的数据。");
      return false;
    } finally {
      state.polling = false;
    }
  }

  function startPolling() {
    stopPolling();
    state.pollTimer = window.setInterval(() => {
      if (document.visibilityState === "visible") refreshCore();
    }, POLL_MS);
  }

  function stopPolling() {
    if (state.pollTimer) window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }

  function showPage(page) {
    if (!["home", "league", "feed", "embers", "history", "me", "user", "people", "integration"].includes(page)) page = "home";
    state.page = page;
    document.querySelectorAll(".page").forEach((section) => {
      section.hidden = section.dataset.page !== page;
    });
    document.querySelectorAll(".nav-button").forEach((button) => {
      const active = button.dataset.page === page;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (window.location.hash !== `#${page}`) {
      window.history.replaceState(null, "", `#${page}`);
    }
    window.scrollTo({ top: 0, behavior: reducedMotionQuery.matches ? "auto" : "smooth" });
    if (page === "league" && state.tierRailNeedsCenter) {
      window.requestAnimationFrame(() => {
        centerTierRail();
      });
    }
    if (page === "feed") {
      renderFeed();
      if (!state.feedLoaded) loadFeed();
    }
    if (page === "embers") {
      renderEmbers();
      if (!state.embersLoaded) loadEmbers();
    }
    if (page === "history" && !state.historyLoaded) loadHistory();
    if (page === "integration") renderIntegrationToken();
  }

  async function loadHistory() {
    if (state.historyLoaded) return;
    el["history-loading"].hidden = false;
    el["history-empty"].hidden = true;
    el["history-error"].hidden = true;
    try {
      const payload = await api("/v1/league/history");
      state.history = Array.isArray(payload.results) ? payload.results : [];
      state.historyLoaded = true;
      renderHistory();
    } catch (error) {
      el["history-loading"].hidden = true;
      el["history-empty"].hidden = true;
      el["history-error"].hidden = false;
      if (!(error instanceof ApiError && error.status === 401)) {
        showToast("历史加载失败。");
      }
    }
  }

  function showLogin(message = "") {
    el["boot-loader"].hidden = true;
    el["app-shell"].hidden = true;
    el["login-view"].hidden = false;
    setLoginError(message);
    setBusy(el["login-button"], false);
    stopPolling();
    if (el["token-input"]) el["token-input"].value = "";
    state.profile = null;
    state.status = null;
    state.league = null;
    state.standings = null;
    state.friendsStandings = null;
    state.leagueTab = "group";
    state.userDetail = null;
    state.detailUserId = null;
    state.meDetail = null;
    state.people = null;
    state.peopleLoaded = false;
    state.history = null;
    state.historyLoaded = false;
    state.embers = null;
    state.embersLoaded = false;
    state.collection = null;
    state.collectionLoaded = false;
    state.feed = null;
    state.feedLoaded = false;
    state.feedBusy = false;
    state.checkins = null;
    state.repairCandidates = [];
    state.repairBusy = false;
    state.tierRailTier = null;
    state.tierRailNeedsCenter = true;
    state.avatarFile = null;
    state.shareBusy = false;
    if (el["share-card-button"]) setBusy(el["share-card-button"], false);
    if (state.avatarPreviewUrl) {
      URL.revokeObjectURL(state.avatarPreviewUrl);
      state.avatarPreviewUrl = null;
    }
    if (el["home-feed-list"]) el["home-feed-list"].replaceChildren();
    if (el["home-feed-empty"]) el["home-feed-empty"].hidden = true;
    if (el["feed-list"]) el["feed-list"].replaceChildren();
    if (el["feed-empty"]) el["feed-empty"].hidden = true;
    if (el["feed-loading"]) el["feed-loading"].hidden = true;
    if (el["history-list"]) el["history-list"].replaceChildren();
    if (el["history-empty"]) el["history-empty"].hidden = true;
    if (el["history-loading"]) el["history-loading"].hidden = true;
    if (el["history-error"]) el["history-error"].hidden = true;
    if (el["ember-ledger"]) el["ember-ledger"].replaceChildren();
    if (el["ember-ledger-empty"]) el["ember-ledger-empty"].hidden = true;
    if (el["ember-ledger-loading"]) el["ember-ledger-loading"].hidden = true;
    renderDailyActions();
    renderEmberBadge();
    if (el["home-standings"]) {
      el["home-standings"].replaceChildren();
      delete el["home-standings"].dataset.rendered;
      el["home-standings"]._rankMap = new Map();
    }
    if (el["league-standings"]) {
      el["league-standings"].replaceChildren();
      delete el["league-standings"].dataset.rendered;
      el["league-standings"]._rankMap = new Map();
    }
    cancelTransientFeedback();
    if (el["people-list"]) el["people-list"].replaceChildren();
    if (el["people-empty"]) el["people-empty"].hidden = true;
    if (el["people-loading"]) el["people-loading"].hidden = true;
    if (el["people-error"]) el["people-error"].hidden = true;
    if (el["user-content"]) el["user-content"].hidden = true;
    if (el["user-error"]) el["user-error"].hidden = true;
    if (el["user-loading"]) el["user-loading"].hidden = true;
    renderIntegrationToken();
  }

  function showApp() {
    el["boot-loader"].hidden = true;
    el["login-view"].hidden = true;
    el["app-shell"].hidden = false;
    if (el["token-input"]) el["token-input"].value = "";
    setLoginError("");
    startPolling();
  }

  function signOut(message = "") {
    storageRemove(TOKEN_KEY);
    state.token = null;
    stopPolling();
    showLogin(message);
  }

  async function loginWithToken(token) {
    const value = String(token || "").trim();
    if (!value) {
      setLoginError("请粘贴你的个人令牌。");
      return;
    }
    state.token = value;
    state.loginBusy = true;
    setLoginError("");
    setBusy(el["login-button"], true);
    try {
      await api("/v1/me/profile", { skipAuthRedirect: true });
      storageSet(TOKEN_KEY, value);
      await loadDashboard({ first: true });
      showApp();
      showPage("home");
      playClick();
    } catch (error) {
      state.token = null;
      setBusy(el["login-button"], false);
      state.loginBusy = false;
      if (error instanceof ApiError && error.status === 401) {
        setLoginError("令牌无效或已过期，请重新输入。");
      } else {
        setLoginError(error.message || "无法连接服务器，请稍后重试。");
      }
      return;
    }
    state.loginBusy = false;
    setBusy(el["login-button"], false);
  }

  async function boot() {
    bindEvents();
    registerServiceWorker();
    renderSound();
    updateOfflineBanner();
    showPage(location.hash.replace("#", "") || "home");
    if (!state.token) {
      showLogin();
      return;
    }
    try {
      await api("/v1/me/profile", { skipAuthRedirect: true });
      await loadDashboard({ first: true });
      showApp();
      showPage(location.hash.replace("#", "") || "home");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        storageRemove(TOKEN_KEY);
        state.token = null;
        showLogin("登录已失效，请重新输入令牌。");
      } else {
        showLogin("无法连接服务器，令牌仍保存在本机。");
      }
    }
  }

  const PULL_TRIGGER = 62;
  let pullTracking = false;
  let pullStartX = 0;
  let pullStartY = 0;
  let pullDistance = 0;

  function hidePullRefresh() {
    const indicator = el["pull-refresh"];
    if (!indicator) return;
    indicator.classList.remove("is-visible", "is-refreshing");
    const label = indicator.querySelector("span");
    if (label) label.textContent = "下拉刷新";
  }

  function setupPullToRefresh() {
    const indicator = el["pull-refresh"];
    if (!indicator) return;
    const inForm = (target) => (
      target instanceof Element
      && Boolean(target.closest("input, textarea, select, [contenteditable='true'], [role='dialog']"))
    );

    document.addEventListener("touchstart", (event) => {
      if (!state.token || el["app-shell"]?.hidden || event.touches.length !== 1) return;
      if (window.scrollY > 0 || inForm(event.target)) return;
      pullStartX = event.touches[0].clientX;
      pullStartY = event.touches[0].clientY;
      pullDistance = 0;
      pullTracking = true;
    }, { passive: true });

    document.addEventListener("touchmove", (event) => {
      if (!pullTracking || event.touches.length !== 1) return;
      const dx = event.touches[0].clientX - pullStartX;
      const dy = event.touches[0].clientY - pullStartY;
      if (Math.abs(dx) > Math.abs(dy) || dy <= 0) {
        if (dy < -8) {
          pullTracking = false;
          hidePullRefresh();
        }
        return;
      }
      if (window.scrollY > 0) {
        pullTracking = false;
        hidePullRefresh();
        return;
      }
      pullDistance = Math.min(92, dy * 0.55);
      if (pullDistance <= 6) return;
      event.preventDefault();
      indicator.classList.add("is-visible");
      indicator.classList.remove("is-refreshing");
      const label = indicator.querySelector("span");
      if (label) label.textContent = pullDistance >= PULL_TRIGGER ? "松开刷新" : "下拉刷新";
    }, { passive: false });

    document.addEventListener("touchend", async () => {
      if (!pullTracking) return;
      const shouldRefresh = pullDistance >= PULL_TRIGGER;
      pullTracking = false;
      if (!shouldRefresh) {
        hidePullRefresh();
        return;
      }
      indicator.classList.add("is-visible", "is-refreshing");
      const label = indicator.querySelector("span");
      if (label) label.textContent = "刷新中";
      const ok = await refreshCore({ announce: true });
      if (!ok && !state.polling) {
        if (label) label.textContent = "刷新失败";
        await new Promise((resolve) => window.setTimeout(resolve, 650));
      }
      hidePullRefresh();
    }, { passive: true });

    document.addEventListener("touchcancel", () => {
      pullTracking = false;
      hidePullRefresh();
    }, { passive: true });
  }

  function bindEvents() {
    setupPullToRefresh();
    setupTierRailScroll();
    el["login-form"].addEventListener("submit", (event) => {
      event.preventDefault();
      if (state.loginBusy) return;
      loginWithToken(el["token-input"].value);
    });
    el["toggle-token"].addEventListener("click", () => {
      const showing = el["token-input"].type === "text";
      el["token-input"].type = showing ? "password" : "text";
      el["toggle-token"].textContent = showing ? "显示" : "隐藏";
      el["toggle-token"].setAttribute("aria-label", showing ? "显示令牌" : "隐藏令牌");
      playClick();
    });
    document.querySelectorAll("button[data-page], button[data-nav]").forEach((button) => {
      button.addEventListener("click", () => {
        const page = button.dataset.page || button.dataset.nav;
        showPage(page);
        playClick();
      });
    });
    if (el["feed-back-button"]) {
      el["feed-back-button"].addEventListener("click", () => {
        showPage("home");
        playClick();
      });
    }
    [el["home-feed-list"], el["feed-list"]].forEach((container) => {
      if (!container) return;
      container.addEventListener("click", (event) => {
        const button = event.target.closest("[data-feed-react]");
        if (!button || button.disabled) return;
        const eventId = Number(button.dataset.feedEventId);
        const emoji = button.dataset.feedEmoji;
        if (!eventId || !emoji) return;
        reactToFeed(eventId, emoji);
      });
    });
    el["league-tab-group"].addEventListener("click", () => {
      state.leagueTab = "group";
      renderStandings();
      playClick();
    });
    el["league-tab-friends"].addEventListener("click", () => {
      state.leagueTab = "friends";
      renderStandings();
      loadFriendsStandings();
      playClick();
    });
    el["repair-button"].addEventListener("click", repairSelectedDay);
    if (el["collection-card"]) {
      el["collection-card"].addEventListener("click", (event) => {
        const button = event.target.closest("[data-equip-field]");
        if (!button || button.disabled) return;
        equipCollection(button.dataset.equipField, button.dataset.equipId);
      });
    }
    el["integration-docs-row"].addEventListener("click", () => {
      showPage("integration");
      playClick();
    });
    el["integration-back-button"].addEventListener("click", () => {
      showPage("me");
      playClick();
    });
    el["integration-token-reveal"].addEventListener("click", () => {
      const showing = el["integration-token-input"].type === "text";
      el["integration-token-input"].type = showing ? "password" : "text";
      el["integration-token-reveal"].textContent = showing ? "显示" : "隐藏";
      el["integration-token-reveal"].setAttribute(
        "aria-label",
        showing ? "显示个人访问令牌" : "隐藏个人访问令牌",
      );
      playClick();
    });
    el["integration-token-copy"].addEventListener("click", async () => {
      try {
        await copyText(state.token);
        showToast("令牌已复制。");
      } catch (_) {
        showToast("复制失败，请手动选择令牌。");
        sound.error();
      }
    });
    el["rotate-token-button"].addEventListener("click", async () => {
      setBusy(el["rotate-token-button"], true);
      try {
        const payload = await api("/v1/me/token/rotate", { method: "POST" });
        state.token = payload.token;
        storageSet(TOKEN_KEY, state.token);
        renderIntegrationToken();
        showToast("已生成新令牌，请同步更新其他客户端。");
        playClick();
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          showToast(error.message || "令牌生成失败，请重试。");
          sound.error();
        }
      } finally {
        setBusy(el["rotate-token-button"], false);
      }
    });
    document.querySelectorAll("[data-copy-code]").forEach((button) => {
      button.addEventListener("click", async () => {
        const code = button.parentElement?.querySelector("code");
        try {
          await copyText(code?.textContent || "");
          button.textContent = "已复制";
          showToast("代码已复制。");
          window.setTimeout(() => { button.textContent = "复制"; }, 1600);
        } catch (_) {
          showToast("复制失败，请手动选择代码。");
          sound.error();
        }
      });
    });
    el["nearby-people-row"].addEventListener("click", () => {
      showPage("people");
      loadPeople();
      playClick();
    });
    el["people-back-button"].addEventListener("click", () => {
      showPage("me");
      playClick();
    });
    el["user-back-button"].addEventListener("click", () => {
      const target = state.detailReturnPage || "league";
      showPage(target);
      if (target === "league" && state.leagueTab === "friends") {
        loadFriendsStandings();
      }
      playClick();
    });
    el["user-follow-button"].addEventListener("click", async () => {
      const detail = state.userDetail;
      if (!detail || detail.is_me) return;
      setBusy(el["user-follow-button"], true);
      await setFollowState(detail.user_id, !detail.is_following);
      setBusy(el["user-follow-button"], false);
    });
    el["sound-button"].addEventListener("click", () => {
      state.sound = !state.sound;
      storageSet(SOUND_KEY, state.sound ? "1" : "0");
      if (state.sound) unlockAudio();
      renderSound();
      if (state.sound) playClick();
    });
    el["sound-toggle-row"].addEventListener("click", () => {
      state.sound = !state.sound;
      storageSet(SOUND_KEY, state.sound ? "1" : "0");
      if (state.sound) unlockAudio();
      renderSound();
      if (state.sound) playClick();
      showToast(state.sound ? "声音已开启" : "声音已静音");
    });
    el["haptics-toggle-row"].addEventListener("click", () => {
      state.haptics = !state.haptics;
      storageSet(HAPTICS_KEY, state.haptics ? "1" : "0");
      renderSound();
      if (state.haptics) vibrate([16]);
      playClick();
      showToast(state.haptics ? "轻触反馈已开启" : "轻触反馈已关闭");
    });
    el["share-card-button"].addEventListener("click", shareCard);
    document.querySelectorAll('input[name="icon_theme"]').forEach((input) => {
      input.addEventListener("change", () => {
        if (input.checked) selectIconTheme(input.value);
      });
    });
    el["profile-form"].addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = el["display-name-input"].value.trim();
      const activity = el["activity-label-input"].value.trim();
      const iconTheme = selectedIconTheme();
      if (!name || name.length > 32) {
        showToast("显示名需要 1–32 个字符。");
        sound.error();
        return;
      }
      if (!activity || Array.from(activity).length > 16) {
        showToast("活动需要 1–16 个字符。");
        sound.error();
        return;
      }
      setBusy(el["save-name-button"], true);
      el["name-save-status"].hidden = false;
      el["name-save-status"].textContent = "保存中…";
      try {
        const previousTheme = profileIconTheme();
        const profile = await api("/v1/me/profile", {
          method: "PATCH",
          json: {
            display_name: name,
            activity_label: activity,
            icon_theme: iconTheme,
          },
        });
        state.profile = profile;
        renderProfile();
        if (normalizeIconTheme(profile.icon_theme) !== previousTheme) {
          renderTierSlots(
            state.status?.tier || profile.tier || "Bronze",
            profileIconTheme(profile),
          );
        }
        await refreshCore();
        el["name-save-status"].textContent = "已保存";
        showToast("资料已更新。");
        playClick();
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          showToast(error.message || "资料保存失败。");
          sound.error();
        }
        el["name-save-status"].hidden = true;
      } finally {
        setBusy(el["save-name-button"], false);
      }
    });
    el["choose-avatar-button"].addEventListener("click", () => el["avatar-input"].click());
    el["avatar-input"].addEventListener("change", () => {
      const file = el["avatar-input"].files?.[0];
      if (!file) return;
      if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
        showToast("请选择 PNG、JPEG 或 WebP 图片。");
        sound.error();
        return;
      }
      if (file.size > 2 * 1024 * 1024) {
        showToast("头像不能超过 2MB。");
        sound.error();
        return;
      }
      if (state.avatarPreviewUrl) URL.revokeObjectURL(state.avatarPreviewUrl);
      state.avatarFile = file;
      state.avatarPreviewUrl = URL.createObjectURL(file);
      const image = el["profile-avatar"].querySelector("img");
      const fallback = el["profile-avatar"].querySelector(".avatar-fallback");
      image.src = state.avatarPreviewUrl;
      image.hidden = false;
      fallback.hidden = true;
      el["upload-avatar-button"].disabled = false;
      playClick();
    });
    el["upload-avatar-button"].addEventListener("click", async () => {
      if (!state.avatarFile || state.uploadBusy) return;
      state.uploadBusy = true;
      el["upload-avatar-button"].disabled = true;
      setBusy(el["upload-avatar-button"], true);
      const form = new FormData();
      form.append("file", state.avatarFile);
      try {
        const payload = await api("/v1/me/avatar", { method: "POST", body: form });
        state.profile.avatar_url = payload.avatar_url;
        state.avatarFile = null;
        await refreshCore();
        showToast("头像已更新。");
        playClick();
        vibrate([16]);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 401)) {
          showToast(error.message || "头像上传失败。");
          sound.error();
        }
      } finally {
        state.uploadBusy = false;
        setBusy(el["upload-avatar-button"], false);
        el["upload-avatar-button"].disabled = !state.avatarFile;
      }
    });
    el["refresh-button"].addEventListener("click", async () => {
      if (state.polling || !state.token) return;
      const button = el["refresh-button"];
      button.disabled = true;
      button.classList.add("is-spinning");
      button.setAttribute("aria-busy", "true");
      playClick();
      try {
        await refreshCore({ announce: true });
      } finally {
        button.disabled = false;
        button.classList.remove("is-spinning");
        button.removeAttribute("aria-busy");
      }
    });
    el["logout-button"].addEventListener("click", () => {
      if (!window.confirm("退出后需要重新输入令牌，确定退出吗？")) return;
      signOut("");
      playClick();
    });
    el["install-button"].addEventListener("click", async () => {
      if (!state.installPrompt) return;
      state.installPrompt.prompt();
      try { await state.installPrompt.userChoice; } catch (_) { /* dismissed */ }
      state.installPrompt = null;
      el["install-button"].hidden = true;
      playClick();
    });
    window.addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      state.installPrompt = event;
      el["install-button"].hidden = false;
    });
    window.addEventListener("appinstalled", () => {
      state.installPrompt = null;
      el["install-button"].hidden = true;
    });
    window.addEventListener("online", () => {
      updateOfflineBanner();
      state.offlineToastShown = false;
      if (state.token) refreshCore();
    });
    window.addEventListener("offline", () => {
      updateOfflineBanner();
      showToast("网络已断开，请检查连接。");
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        document.body.classList.add("is-page-hidden");
        stopPolling();
        settleMotionState();
        hideMoment();
      } else {
        document.body.classList.remove("is-page-hidden");
        if (state.token) {
          startPolling();
          refreshCore();
        }
      }
    });
    document.addEventListener("pointerdown", unlockAudio, { passive: true });
    document.documentElement.classList.toggle("reduced-motion", reducedMotionQuery.matches);
    reducedMotionQuery.addEventListener?.("change", (event) => {
      document.documentElement.classList.toggle("reduced-motion", event.matches);
      if (event.matches) {
        settleMotionState();
        hideMoment();
      }
    });
  }

  function updateOfflineBanner() {
    if (!el["offline-banner"]) return;
    el["offline-banner"].hidden = navigator.onLine;
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    const hadController = Boolean(navigator.serviceWorker.controller);
    let refreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (hadController && !refreshing) {
        refreshing = true;
        window.location.reload();
      }
    });
    const register = () => {
      navigator.serviceWorker.register("/sw.js").then((registration) => {
        registration.update().catch(() => {});
      }).catch(() => {});
    };
    if (document.readyState === "complete") register();
    else window.addEventListener("load", register, { once: true });
  }

  function runConfetti(intensity = 1) {
    if (reducedMotionQuery.matches || document.visibilityState === "hidden") return;
    const canvas = el["confetti-canvas"];
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    stopConfetti();
    confettiVisible = true;
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const width = window.innerWidth;
    const height = window.innerHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const colors = [
      tierInfo(state.status?.tier).color, "#ffd45c", "#ff4d8d", "#5ce0be", "#a994ff", "#ffffff",
    ];
    const count = Math.min(64, Math.max(24, Math.round(56 * intensity)));
    const particles = Array.from({ length: count }, (_, index) => ({
      x: width * (0.28 + Math.random() * 0.44),
      y: height * 0.36,
      vx: (Math.random() - 0.5) * 9,
      vy: -5 - Math.random() * 7,
      gravity: 0.2 + Math.random() * 0.1,
      rotation: Math.random() * Math.PI,
      spin: (Math.random() - 0.5) * 0.28,
      size: 3 + Math.random() * 5,
      color: colors[index % colors.length],
      life: 1,
    }));
    const start = performance.now();
    const duration = 1300;
    const draw = (now) => {
      if (!confettiVisible) return;
      const elapsed = now - start;
      ctx.clearRect(0, 0, width, height);
      particles.forEach((particle) => {
        particle.vy += particle.gravity;
        particle.x += particle.vx;
        particle.y += particle.vy;
        particle.vx *= 0.994;
        particle.rotation += particle.spin;
        particle.life = Math.max(0, 1 - elapsed / duration);
        ctx.save();
        ctx.globalAlpha = particle.life;
        ctx.translate(particle.x, particle.y);
        ctx.rotate(particle.rotation);
        ctx.fillStyle = particle.color;
        ctx.fillRect(-particle.size / 2, -particle.size / 2, particle.size, particle.size * 0.6);
        ctx.restore();
      });
      if (elapsed < duration) {
        confettiFrame = requestAnimationFrame(draw);
      } else {
        confettiVisible = false;
        confettiFrame = 0;
        ctx.clearRect(0, 0, width, height);
      }
    };
    confettiFrame = requestAnimationFrame(draw);
  }

  function init() {
    cacheIds();
    if (!state.token) {
      showLogin();
      bindEvents();
      registerServiceWorker();
      renderSound();
      updateOfflineBanner();
      return;
    }
    boot();
  }

  init();
})();
