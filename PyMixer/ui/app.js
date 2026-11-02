/* PyMixer settings UI — talks to Python via window.pywebview.api */
(function () {
  "use strict";

  const KNOB_SPECIAL = [
    { value: "", label: "— none —" },
    { value: "focused_app", label: "Focused Application" },
    { value: "explorer.exe", label: "Master Volume" },
  ];

  const BUTTON_SPECIAL = [
    { value: "", label: "— none —" },
    { value: "toggle_mic_mute", label: "Toggle Microphone Mute" },
    { value: "toggle_master_mute", label: "Toggle Master Mute" },
    { value: "lock_pc", label: "Lock PC" },
    { value: "next_profile", label: "Next Profile" },
    { value: "__url__", label: "Open Webpage…" },
  ];

  const CURVE_OPTIONS = [
    { value: "linear", label: "Linear" },
    { value: "gentle", label: "Gentle" },
    { value: "strong", label: "Strong" },
  ];

  const LIVE_POLL_MS = 120;

  const state = {
    config: null,
    ports: [],
    apps: [],
    connected: false,
    demo: false,
    modalMode: null, // 'add' | 'rename'
    ctxProfile: null,
    live: { stale: true, knobs: {}, connected: false },
    liveTimer: null,
  };

  const $ = (id) => document.getElementById(id);

  function toast(msg, isErr) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.toggle("err", !!isErr);
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 2200);
  }

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  async function call(method, ...args) {
    const a = api();
    if (!a || typeof a[method] !== "function") {
      throw new Error("Bridge not ready");
    }
    return a[method](...args);
  }

  function displayName(value) {
    if (!value) return "Unassigned";
    if (value === "focused_app") return "Focused App";
    if (value === "explorer.exe") return "Master Volume";
    if (value === "toggle_mic_mute") return "Mic Mute";
    if (value === "toggle_master_mute") return "Master Mute";
    if (value === "lock_pc") return "Lock PC";
    if (value === "next_profile") return "Next Profile";
    if (value.startsWith("profile:")) return "Profile: " + value.slice(8);
    if (looksLikeUrl(value)) return "Open Webpage…";
    return value.replace(/\.exe$/i, "");
  }

  function looksLikeUrl(v) {
    if (!v) return false;
    if (/^https?:\/\//i.test(v) || /^www\./i.test(v)) return true;
    if (
      v.includes(".") &&
      !/\.exe$/i.test(v) &&
      !["focused_app", "explorer.exe", "toggle_mic_mute", "toggle_master_mute", "lock_pc", "next_profile"].includes(v) &&
      !v.startsWith("profile:")
    ) {
      return true;
    }
    return false;
  }

  function badgeClass(value) {
    if (!value) return "empty";
    if (value === "focused_app") return "focus";
    if (value === "explorer.exe") return "master";
    if (/discord/i.test(value)) return "dc";
    if (/firefox|chrome|msedge|brave/i.test(value)) return "ff";
    return "master";
  }

  function badgeText(value) {
    if (!value) return "—";
    if (value === "focused_app") return "◉";
    if (value === "explorer.exe") return "♪";
    const base = value.replace(/\.exe$/i, "");
    return (base[0] || "?").toUpperCase();
  }

  function demoBootstrap() {
    state.demo = true;
    state.ports = ["COM5", "COM3", "COM4"];
    state.apps = ["chrome.exe", "firefox.exe", "Discord.exe", "spotify.exe", "Code.exe"];
    state.connected = true;
    state.config = {
      SERIAL_PORT: "COM5",
      BAUD_RATE: 115200,
      NUM_KNOBS: 5,
      NUM_BUTTONS: 10,
      ACTIVE_PROFILE: "Gaming",
      PROFILE_ICONS: { Gaming: "🎮", Work: "💼", Music: "🎵" },
      APP_MAPPINGS: {
        K1: "focused_app",
        K2: "",
        K3: "firefox.exe",
        K4: "Discord.exe",
        K5: "explorer.exe",
        B1: "chrome.exe",
        B2: "spotify.exe",
        B3: "www.youtube.com",
        B4: "",
        B5: "",
        B6: "",
        B7: "",
        B8: "",
        B9: "",
        B10: "",
      },
      SLIDER_REVERSE: { K1: true, K2: true, K3: true, K4: true, K5: true },
      SLIDER_SENSITIVITY: { K1: 1.0, K2: 1.0, K3: 1.0, K4: 1.0, K5: 1.0 },
      SLIDER_CURVE: { K1: "gentle", K2: "linear", K3: "linear", K4: "strong", K5: "linear" },
      PROFILES: {
        Gaming: null,
        Work: null,
        Music: null,
      },
    };
    const payload = {
      APP_MAPPINGS: { ...state.config.APP_MAPPINGS },
      SLIDER_REVERSE: { ...state.config.SLIDER_REVERSE },
      SLIDER_SENSITIVITY: { ...state.config.SLIDER_SENSITIVITY },
      SLIDER_CURVE: { ...state.config.SLIDER_CURVE },
    };
    state.config.PROFILES.Gaming = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Work = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Work.APP_MAPPINGS.K3 = "Code.exe";
    state.config.PROFILES.Work.SLIDER_CURVE.K1 = "linear";
    state.config.PROFILES.Music = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Music.APP_MAPPINGS.K4 = "spotify.exe";
    // Demo live levels so faders move in screenshots
    state.live = {
      stale: false,
      connected: true,
      knobs: {
        K1: { raw: 700, volume: 0.55, pct: 55 },
        K2: { raw: 100, volume: 0.1, pct: 10 },
        K3: { raw: 820, volume: 0.72, pct: 72 },
        K4: { raw: 900, volume: 0.68, pct: 68 },
        K5: { raw: 600, volume: 0.59, pct: 59 },
      },
    };
  }

  async function refresh() {
    try {
      const data = await call("get_state");
      state.config = data.config;
      state.ports = data.ports || [];
      state.apps = data.apps || [];
      state.connected = !!data.connected;
      if (data.live) state.live = data.live;
      state.demo = false;
    } catch (err) {
      console.warn("get_state failed, using demo data:", err);
      demoBootstrap();
    }
    render();
  }

  function collectFromDom() {
    const cfg = state.config;
    if (!cfg) return null;
    cfg.SERIAL_PORT = $("port-select").value;
    cfg.BAUD_RATE = parseInt($("baud-input").value, 10) || 115200;

    const numKnobs = cfg.NUM_KNOBS || 5;
    const numButtons = cfg.NUM_BUTTONS || 10;
    cfg.APP_MAPPINGS = cfg.APP_MAPPINGS || {};
    cfg.SLIDER_REVERSE = cfg.SLIDER_REVERSE || {};
    cfg.SLIDER_SENSITIVITY = cfg.SLIDER_SENSITIVITY || {};
    cfg.SLIDER_CURVE = cfg.SLIDER_CURVE || {};

    for (let i = 1; i <= numKnobs; i++) {
      const key = "K" + i;
      const sel = document.querySelector(`[data-knob="${key}"]`);
      const rev = document.querySelector(`[data-reverse="${key}"]`);
      const sens = document.querySelector(`[data-sens="${key}"]`);
      const curve = document.querySelector(`[data-curve="${key}"]`);
      if (sel) cfg.APP_MAPPINGS[key] = sel.value;
      if (rev) cfg.SLIDER_REVERSE[key] = !!rev.checked;
      if (sens) cfg.SLIDER_SENSITIVITY[key] = parseFloat(sens.value) || 1.0;
      if (curve) cfg.SLIDER_CURVE[key] = curve.value || "linear";
    }
    for (let i = 1; i <= numButtons; i++) {
      const key = "B" + i;
      const sel = document.querySelector(`[data-btn="${key}"]`);
      const url = document.querySelector(`[data-url="${key}"]`);
      if (!sel) continue;
      let v = sel.value;
      if (v === "__url__") {
        v = (url && url.value.trim()) || "https://";
      }
      cfg.APP_MAPPINGS[key] = v;
    }
    return cfg;
  }

  function renderRail() {
    const wrap = $("rail-profiles");
    wrap.innerHTML = "";
    const cfg = state.config;
    const names = Object.keys(cfg.PROFILES || {});
    const icons = cfg.PROFILE_ICONS || {};
    names.forEach((name) => {
      const active = name === cfg.ACTIVE_PROFILE;
      const itemWrap = document.createElement("div");
      itemWrap.className = "rail-wrap" + (active ? " active" : "");
      itemWrap.dataset.profile = name;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rail-item" + (active ? " active" : "");
      btn.title = name + (active ? " (active)" : "");
      btn.setAttribute("aria-label", "Profile " + name);
      btn.setAttribute("aria-current", active ? "true" : "false");
      // Prefer stored icon; otherwise first letter — never a bare app "P" logo treatment
      const icon = icons[name];
      btn.textContent = icon || name.slice(0, 1).toUpperCase();
      btn.addEventListener("click", () => onSwitchProfile(name));
      btn.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        openCtx(e.clientX, e.clientY, name);
      });
      const label = document.createElement("div");
      label.className = "rail-label";
      label.textContent = name;
      label.title = name;
      itemWrap.appendChild(btn);
      itemWrap.appendChild(label);
      wrap.appendChild(itemWrap);
    });
  }

  function optionList(special, apps, current) {
    const seen = new Set();
    const opts = [];
    special.forEach((o) => {
      opts.push(o);
      seen.add(o.value);
    });
    (apps || []).forEach((app) => {
      if (!seen.has(app)) {
        opts.push({ value: app, label: app });
        seen.add(app);
      }
    });
    if (current && !seen.has(current) && current !== "__url__") {
      opts.push({ value: current, label: current });
    }
    return opts;
  }

  function fillSelect(sel, options, current) {
    sel.innerHTML = "";
    options.forEach((o) => {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      sel.appendChild(opt);
    });
    if (current !== undefined && current !== null) {
      if (looksLikeUrl(current) && options.some((o) => o.value === "__url__")) {
        sel.value = "__url__";
      } else {
        sel.value = current;
      }
    }
  }

  function livePctFor(key, mapped) {
    const live = state.live || {};
    if (live.stale || !live.knobs || !live.knobs[key]) {
      return { stale: true, pct: null };
    }
    const entry = live.knobs[key];
    let pct = entry.pct;
    if (pct == null && entry.volume != null) pct = Math.round(Number(entry.volume) * 100);
    if (pct == null) return { stale: true, pct: null };
    pct = Math.max(0, Math.min(100, Math.round(Number(pct))));
    return { stale: false, pct };
  }

  function updateFaderDom(key) {
    const card = document.querySelector(`[data-channel="${key}"]`);
    if (!card) return;
    const mapped = !!(state.config && state.config.APP_MAPPINGS && state.config.APP_MAPPINGS[key]);
    const { stale, pct } = livePctFor(key, mapped);
    const fill = card.querySelector(".fader-fill");
    const knob = card.querySelector(".fader-knob");
    const vol = card.querySelector(".vol");
    const fader = card.querySelector(".fader");
    if (!fill || !knob || !vol || !fader) return;
    if (stale) {
      fader.classList.add("stale");
      vol.classList.add("stale");
      vol.classList.add("dim");
      fill.style.height = "0%";
      fill.style.opacity = "0.35";
      knob.style.bottom = "calc(0% - 7px)";
      knob.style.opacity = "0.35";
      vol.textContent = "—";
      vol.title = "No device / waiting for tray app";
    } else {
      fader.classList.remove("stale");
      vol.classList.remove("stale");
      vol.classList.toggle("dim", !mapped);
      fill.style.height = pct + "%";
      fill.style.opacity = mapped ? "1" : "0.45";
      knob.style.bottom = "calc(" + pct + "% - 7px)";
      knob.style.opacity = mapped ? "1" : "0.6";
      vol.innerHTML = pct + "<span>%</span>";
      vol.title = "Live volume after reverse + curve";
    }
  }

  function renderChannels() {
    const root = $("channels");
    root.innerHTML = "";
    const cfg = state.config;
    const n = cfg.NUM_KNOBS || 5;
    const apps = optionList(KNOB_SPECIAL, state.apps, null);
    for (let i = 1; i <= n; i++) {
      const key = "K" + i;
      const value = (cfg.APP_MAPPINGS || {})[key] || "";
      const rev = !!(cfg.SLIDER_REVERSE || {})[key];
      const sens = (cfg.SLIDER_SENSITIVITY || {})[key] ?? 1.0;
      const curve = (cfg.SLIDER_CURVE || {})[key] || "linear";
      const { stale, pct } = livePctFor(key, !!value);
      const showPct = stale ? 0 : pct;

      const card = document.createElement("div");
      card.className = "channel" + (value ? "" : " off");
      card.dataset.channel = key;
      card.innerHTML = `
        <div class="badge ${badgeClass(value)}">${badgeText(value)}</div>
        <div class="ch-name">${displayName(value)}</div>
        <div class="ch-sub">Knob ${i}</div>
        <div class="fader-wrap">
          <div class="fader ${stale ? "stale" : ""}">
            <div class="fader-fill" style="height:${showPct}%;${value && !stale ? "" : "opacity:0.45"}"></div>
            <div class="fader-knob" style="bottom:calc(${showPct}% - 7px);${value && !stale ? "" : "opacity:0.6"}"></div>
          </div>
        </div>
        <div class="vol ${stale || !value ? "dim" : ""} ${stale ? "stale" : ""}">${stale ? "—" : showPct + "<span>%</span>"}</div>
        <div class="controls"></div>
      `;
      const controls = card.querySelector(".controls");
      const sel = document.createElement("select");
      sel.className = "dd";
      sel.dataset.knob = key;
      fillSelect(sel, apps, value);
      sel.addEventListener("change", () => {
        cfg.APP_MAPPINGS[key] = sel.value;
        renderChannels();
      });

      const optsCol = document.createElement("div");
      optsCol.className = "opts-col";

      const opts = document.createElement("div");
      opts.className = "opts";
      opts.innerHTML = `
        <label class="chk"><input type="checkbox" data-reverse="${key}" ${rev ? "checked" : ""}/> Reverse</label>
        <div class="sens" title="How far the physical slider must move before volume updates (filters jitter)">
          <span class="sens-label">Jitter</span>
          <span class="sens-val">${Number(sens).toFixed(1)}</span>
          <input type="range" min="0.2" max="2" step="0.1" value="${sens}" data-sens="${key}" />
        </div>
      `;
      const range = opts.querySelector("input[type=range]");
      const sensVal = opts.querySelector(".sens-val");
      range.addEventListener("input", () => {
        sensVal.textContent = Number(range.value).toFixed(1);
      });

      const curveRow = document.createElement("div");
      curveRow.className = "curve-row";
      curveRow.innerHTML = `<label for="curve-${key}" title="More travel at the low end">Curve</label>`;
      const curveSel = document.createElement("select");
      curveSel.className = "curve-select";
      curveSel.id = "curve-" + key;
      curveSel.dataset.curve = key;
      curveSel.title = "Response curve — gentle/strong give more travel at low volume";
      fillSelect(curveSel, CURVE_OPTIONS, curve);
      curveRow.appendChild(curveSel);

      optsCol.appendChild(opts);
      optsCol.appendChild(curveRow);
      controls.appendChild(sel);
      controls.appendChild(optsCol);
      root.appendChild(card);
    }
  }

  function renderButtons() {
    const root = $("buttons");
    root.innerHTML = "";
    const cfg = state.config;
    const n = cfg.NUM_BUTTONS || 10;
    const apps = optionList(BUTTON_SPECIAL, state.apps, null);
    for (let i = 1; i <= n; i++) {
      const key = "B" + i;
      const value = (cfg.APP_MAPPINGS || {})[key] || "";
      const isUrl = looksLikeUrl(value);
      const card = document.createElement("div");
      card.className = "bcard" + (value ? " live" : "");
      card.innerHTML = `
        <div class="btop"><span class="bid">${key}</span><span class="bdot ${value ? "on" : ""}"></span></div>
      `;
      const sel = document.createElement("select");
      sel.className = "bact-select";
      sel.dataset.btn = key;
      fillSelect(sel, apps, isUrl ? "__url__" : value);
      const url = document.createElement("input");
      url.className = "burl-input" + (sel.value === "__url__" ? " show" : "");
      url.dataset.url = key;
      url.placeholder = "URL…";
      url.value = isUrl ? value : "";
      sel.addEventListener("change", () => {
        const show = sel.value === "__url__";
        url.classList.toggle("show", show);
        if (!show) url.value = "";
        card.classList.toggle("live", !!sel.value && sel.value !== "");
        card.querySelector(".bdot").classList.toggle("on", !!sel.value);
      });
      card.appendChild(sel);
      card.appendChild(url);
      root.appendChild(card);
    }
  }

  function renderConn() {
    const cfg = state.config;
    const pill = $("status-pill");
    const text = $("status-text");
    if (state.connected) {
      pill.classList.remove("off");
      text.textContent = "Connected";
    } else {
      pill.classList.add("off");
      text.textContent = state.demo ? "Demo" : "Disconnected";
    }
    const portSel = $("port-select");
    const ports = state.ports.length ? state.ports : [cfg.SERIAL_PORT || "COM3"];
    portSel.innerHTML = "";
    const all = Array.from(new Set([cfg.SERIAL_PORT, ...ports].filter(Boolean)));
    all.forEach((p) => {
      const o = document.createElement("option");
      o.value = p;
      o.textContent = p;
      portSel.appendChild(o);
    });
    portSel.value = cfg.SERIAL_PORT;
    $("baud-input").value = cfg.BAUD_RATE || 115200;
    $("preset-tag").textContent = (cfg.ACTIVE_PROFILE || "Default") + " preset";
  }

  function render() {
    if (!state.config) return;
    renderConn();
    renderRail();
    renderChannels();
    renderButtons();
  }

  function snapshotProfilePayload(cfg) {
    return {
      APP_MAPPINGS: { ...cfg.APP_MAPPINGS },
      SLIDER_REVERSE: { ...cfg.SLIDER_REVERSE },
      SLIDER_SENSITIVITY: { ...cfg.SLIDER_SENSITIVITY },
      SLIDER_CURVE: { ...(cfg.SLIDER_CURVE || {}) },
    };
  }

  async function onSwitchProfile(name) {
    if (!state.config || name === state.config.ACTIVE_PROFILE) return;
    collectFromDom();
    if (state.demo) {
      const cur = state.config.ACTIVE_PROFILE;
      state.config.PROFILES[cur] = snapshotProfilePayload(state.config);
      const next = state.config.PROFILES[name];
      state.config.ACTIVE_PROFILE = name;
      state.config.APP_MAPPINGS = { ...next.APP_MAPPINGS };
      state.config.SLIDER_REVERSE = { ...next.SLIDER_REVERSE };
      state.config.SLIDER_SENSITIVITY = { ...next.SLIDER_SENSITIVITY };
      state.config.SLIDER_CURVE = { ...(next.SLIDER_CURVE || {}) };
      render();
      return;
    }
    try {
      const cfg = collectFromDom();
      const updated = await call("switch_profile", name, cfg);
      state.config = updated;
      render();
    } catch (err) {
      toast(String(err.message || err), true);
    }
  }

  async function onSave() {
    const cfg = collectFromDom();
    if (!cfg) return;
    if (state.demo) {
      toast("Demo mode — not saved");
      return;
    }
    $("btn-save").disabled = true;
    try {
      await call("save_config", cfg);
      state.config = cfg;
      toast("Configuration saved");
      const status = await call("get_state");
      state.connected = !!status.connected;
      state.ports = status.ports || state.ports;
      if (status.live) state.live = status.live;
      renderConn();
    } catch (err) {
      toast(String(err.message || err), true);
    } finally {
      $("btn-save").disabled = false;
    }
  }

  function openModal(mode, seed) {
    state.modalMode = mode;
    $("modal-title").textContent = mode === "add" ? "Add profile" : "Rename profile";
    $("modal-input").value = seed || "";
    $("modal-delete").style.display = mode === "rename" ? "inline-block" : "none";
    $("modal").classList.add("show");
    setTimeout(() => $("modal-input").focus(), 50);
  }

  function closeModal() {
    $("modal").classList.remove("show");
    state.modalMode = null;
  }

  async function onModalOk() {
    const name = $("modal-input").value.trim();
    if (!name) {
      toast("Name required", true);
      return;
    }
    collectFromDom();
    try {
      if (state.demo) {
        if (state.modalMode === "add") {
          if (state.config.PROFILES[name]) throw new Error("Already exists");
          state.config.PROFILES[name] = snapshotProfilePayload(state.config);
          state.config.PROFILE_ICONS[name] = name.slice(0, 1).toUpperCase();
          state.config.ACTIVE_PROFILE = name;
        } else if (state.modalMode === "rename") {
          const old = state.ctxProfile;
          state.config.PROFILES[name] = state.config.PROFILES[old];
          delete state.config.PROFILES[old];
          state.config.PROFILE_ICONS[name] = state.config.PROFILE_ICONS[old] || name[0];
          delete state.config.PROFILE_ICONS[old];
          if (state.config.ACTIVE_PROFILE === old) state.config.ACTIVE_PROFILE = name;
        }
        closeModal();
        render();
        return;
      }
      let updated;
      if (state.modalMode === "add") {
        updated = await call("add_profile", name, collectFromDom());
      } else {
        updated = await call("rename_profile", state.ctxProfile, name, collectFromDom());
      }
      state.config = updated;
      closeModal();
      render();
    } catch (err) {
      toast(String(err.message || err), true);
    }
  }

  async function onModalDelete() {
    const name = state.ctxProfile;
    if (!name) return;
    try {
      if (state.demo) {
        if (Object.keys(state.config.PROFILES).length <= 1) throw new Error("Cannot delete last profile");
        delete state.config.PROFILES[name];
        delete state.config.PROFILE_ICONS[name];
        if (state.config.ACTIVE_PROFILE === name) {
          state.config.ACTIVE_PROFILE = Object.keys(state.config.PROFILES)[0];
          const p = state.config.PROFILES[state.config.ACTIVE_PROFILE];
          state.config.APP_MAPPINGS = { ...p.APP_MAPPINGS };
          state.config.SLIDER_REVERSE = { ...p.SLIDER_REVERSE };
          state.config.SLIDER_SENSITIVITY = { ...p.SLIDER_SENSITIVITY };
          state.config.SLIDER_CURVE = { ...(p.SLIDER_CURVE || {}) };
        }
        closeModal();
        render();
        return;
      }
      const updated = await call("delete_profile", name, collectFromDom());
      state.config = updated;
      closeModal();
      render();
    } catch (err) {
      toast(String(err.message || err), true);
    }
  }

  function openCtx(x, y, name) {
    state.ctxProfile = name;
    const el = $("rail-ctx");
    el.style.left = x + "px";
    el.style.top = y + "px";
    el.classList.add("show");
  }

  function closeCtx() {
    $("rail-ctx").classList.remove("show");
  }

  async function pollLive() {
    if (state.demo) {
      // Mild demo drift so screenshots look alive
      const knobs = state.live.knobs || {};
      Object.keys(knobs).forEach((k, idx) => {
        const base = [55, 10, 72, 68, 59][idx] || 40;
        const wobble = Math.round(Math.sin(Date.now() / 800 + idx) * 3);
        const pct = Math.max(0, Math.min(100, base + wobble));
        knobs[k] = { raw: Math.round(pct * 10.23), volume: pct / 100, pct };
      });
      state.live.stale = false;
      const n = (state.config && state.config.NUM_KNOBS) || 5;
      for (let i = 1; i <= n; i++) updateFaderDom("K" + i);
      return;
    }
    try {
      const live = await call("get_live_levels");
      state.live = live || { stale: true, knobs: {} };
      const n = (state.config && state.config.NUM_KNOBS) || 5;
      for (let i = 1; i <= n; i++) updateFaderDom("K" + i);
    } catch (_) {
      /* bridge not ready */
    }
  }

  function startLivePoll() {
    if (state.liveTimer) clearInterval(state.liveTimer);
    state.liveTimer = setInterval(pollLive, LIVE_POLL_MS);
    pollLive();
  }

  function wire() {
    $("btn-save").addEventListener("click", onSave);
    $("rail-add").addEventListener("click", () => openModal("add", ""));
    $("modal-cancel").addEventListener("click", closeModal);
    $("modal-ok").addEventListener("click", onModalOk);
    $("modal-delete").addEventListener("click", onModalDelete);
    $("modal-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") onModalOk();
      if (e.key === "Escape") closeModal();
    });
    $("ctx-rename").addEventListener("click", () => {
      closeCtx();
      openModal("rename", state.ctxProfile);
    });
    $("ctx-delete").addEventListener("click", () => {
      closeCtx();
      openModal("rename", state.ctxProfile);
      onModalDelete();
    });
    document.addEventListener("click", (e) => {
      if (!$("rail-ctx").contains(e.target)) closeCtx();
    });
  }

  function onReady() {
    wire();
    refresh().then(startLivePoll);
  }

  function stamp() {
    try {
      const cfg = state.config || {};
      document.documentElement.setAttribute(
        "data-pymixer",
        JSON.stringify({
          demo: !!state.demo,
          profile: cfg.ACTIVE_PROFILE || null,
          channels: document.querySelectorAll(".channel").length,
          buttons: document.querySelectorAll(".bcard").length,
          profiles: Object.keys(cfg.PROFILES || {}),
          status: (document.getElementById("status-text") || {}).textContent || "",
          hasFakeChrome: !!document.querySelector(".winbtns, .titlebar .close-btn, #btn-close"),
          hasHomeLogo: !!document.querySelector("#rail-home, .rail-item.home, .header .logo"),
          hasProfilesHeading: !!document.querySelector(".rail-heading"),
          addLabel: ((document.querySelector(".rail-foot .rail-label") || {}).textContent || ""),
          urlVisibleCount: document.querySelectorAll("input.burl-input.show").length,
          curves: Array.from(document.querySelectorAll("[data-curve]")).map((el) => el.value),
        })
      );
    } catch (e) {
      document.documentElement.setAttribute("data-pymixer", JSON.stringify({ err: String(e) }));
    }
  }

  window.addEventListener("pywebviewready", onReady);
  function bootFallback() {
    if (state.config) {
      stamp();
      return;
    }
    if (!api()) {
      demoBootstrap();
      wire();
      render();
      startLivePoll();
      stamp();
    }
    refresh().then(() => {
      startLivePoll();
      stamp();
    }).catch(stamp);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFallback);
  } else {
    bootFallback();
  }

  window.__pymixer = {
    refresh,
    render,
    state,
    collectFromDom,
    demoBootstrap,
    pollLive,
    updateFaderDom,
    stamp,
  };
})();
