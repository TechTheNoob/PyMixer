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
    { value: "linear", label: "Linear", hint: "Even all the way" },
    { value: "gentle", label: "Gentle", hint: "More control at low volume" },
    { value: "strong", label: "Strong", hint: "Lots of control at low volume" },
  ];

  const LIVE_POLL_MS = 150;

  const state = {
    config: null,
    ports: [],
    apps: [],
    appCatalog: { audio: [], running: [], installed: [], current: null },
    connected: false,
    demo: false,
    showController: false,
    virtualControllerEnabled: false,
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
    // Protocols (steam://, spotify:) and shell: URIs / .lnk / paths are launches, not webpages
    if (/^(steam|spotify|shell):/i.test(v)) return false;
    if (/\.lnk$/i.test(v) || /\\/.test(v) || /^[A-Za-z]:[\\\/]/.test(v)) return false;
    if (v.startsWith("mute:") || v.startsWith("launch:")) return false;
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

  function offlineShell() {
    /* Bridge missing: paint an empty shell. Faders stay "—" until pywebviewready. */
    state.demo = false;
    state.showController = false;
    state.virtualControllerEnabled = false;
    state.connected = false;
    state.ports = [];
    state.apps = [];
    state.appCatalog = { audio: [], running: [], installed: [], current: null };
    state.config = {
      SERIAL_PORT: "",
      BAUD_RATE: 115200,
      NUM_KNOBS: 5,
      NUM_BUTTONS: 10,
      ACTIVE_PROFILE: "Default",
      PROFILE_ICONS: { Default: "D" },
      APP_MAPPINGS: {},
      SLIDER_REVERSE: {},
      SLIDER_SENSITIVITY: {},
      SLIDER_CURVE: {},
      PROFILES: { Default: null },
    };
    state.live = { stale: true, connected: false, knobs: {} };
  }
  // Back-compat alias — MUST NOT invent live percentages
  function demoBootstrap() {
    offlineShell();
  }

  async function refresh() {
    try {
      const data = await call("get_state");
      state.config = data.config;
      state.ports = data.ports || [];
      state.apps = data.apps || [];
      state.appCatalog = data.app_catalog || { audio: [], running: [], installed: [], current: null };
      state.connected = !!data.connected;
      if (data.live) state.live = data.live;
      state.demo = !!data.demo;
      state.showController = !!data.show_controller;
      state.virtualControllerEnabled = !!data.virtual_controller_enabled;
    } catch (err) {
      console.warn("get_state failed, waiting for bridge:", err);
      offlineShell();
    }
    render();
  }

  function collectFromDom() {
    const cfg = state.config;
    if (!cfg) return null;
    cfg.SERIAL_PORT = $("port-select").value;
    cfg.BAUD_RATE = parseInt($("baud-input").value, 10) || 115200;
    const _vc = $("chk-virtual-controller");
    if (_vc) cfg.VIRTUAL_CONTROLLER_ENABLED = !!_vc.checked;


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
      if (o.hint) opt.title = o.hint;
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
      const sel = window.PyMixerAppPicker.create({
        special: KNOB_SPECIAL,
        current: value,
        dataAttr: "knob",
        dataKey: key,
        getCatalog: () => state.appCatalog,
        looksLikeUrl: looksLikeUrl,
        onChange: (v) => {
          cfg.APP_MAPPINGS[key] = v;
          renderChannels();
        },
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
      curveRow.innerHTML = `<label for="curve-${key}" title="How volume grows as you turn the knob">Curve</label>`;
      const curveSel = document.createElement("select");
      curveSel.className = "curve-select";
      curveSel.id = "curve-" + key;
      curveSel.dataset.curve = key;
      fillSelect(curveSel, CURVE_OPTIONS, curve);
      const preview = document.createElement("span");
      preview.className = "curve-preview";
      preview.setAttribute("aria-hidden", "true");
      const hint = document.createElement("div");
      hint.className = "curve-hint";
      function curveMeta(name) {
        return CURVE_OPTIONS.find((o) => o.value === name) || CURVE_OPTIONS[0];
      }
      function paintCurvePreview(name) {
        const meta = curveMeta(name);
        const exp = name === "strong" ? 3 : name === "gentle" ? 1.8 : 1;
        const pts = [];
        for (let i = 0; i <= 8; i++) {
          const x = i / 8;
          const y = Math.pow(x, exp);
          pts.push((3 + x * 18).toFixed(1) + "," + (14 - y * 10).toFixed(1));
        }
        preview.innerHTML =
          '<svg width="24" height="16" viewBox="0 0 24 16" preserveAspectRatio="none">' +
          '<polyline fill="none" stroke="currentColor" stroke-width="1.5" points="' +
          pts.join(" ") +
          '"/></svg>';
        preview.title = meta.hint || "";
        curveSel.title = meta.hint
          ? meta.label + " — " + meta.hint + ". Change applies on save without moving the knob."
          : "Response curve";
        hint.textContent = meta.hint || "";
      }
      paintCurvePreview(curve);
      curveSel.addEventListener("change", () => paintCurvePreview(curveSel.value));
      curveRow.appendChild(curveSel);
      curveRow.appendChild(preview);

      optsCol.appendChild(opts);
      optsCol.appendChild(curveRow);
      optsCol.appendChild(hint);
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
    for (let i = 1; i <= n; i++) {
      const key = "B" + i;
      const value = (cfg.APP_MAPPINGS || {})[key] || "";
      const isUrl = looksLikeUrl(value);
      const assigned = !!(value);
      const card = document.createElement("div");
      card.className = "bcard" + (assigned ? " live" : " empty");
      card.tabIndex = 0;
      card.setAttribute("role", "button");
      card.setAttribute(
        "aria-label",
        assigned ? key + " assigned — press Enter to change" : key + " — press Enter to assign"
      );
      card.innerHTML = `
        <div class="btop"><span class="bid">${key}</span><span class="bdot ${assigned ? "on" : ""}"></span></div>
      `;
      const url = document.createElement("input");
      url.className = "burl-input" + (isUrl ? " show" : "");
      url.dataset.url = key;
      url.placeholder = "URL…";
      url.value = isUrl ? value : "";
      // Keep URL independently clickable / typeable
      ["click", "mousedown", "mouseup", "keydown", "keyup"].forEach((ev) => {
        url.addEventListener(ev, (e) => e.stopPropagation());
      });

      const hint = document.createElement("div");
      hint.className = "bhint";
      hint.innerHTML = assigned
        ? '<span class="bhint-text">Change</span><span class="bhint-caret">▾</span>'
        : '<span class="bhint-text">Click to assign</span>';

      const syncCardChrome = (v) => {
        const on = !!v;
        card.classList.toggle("live", on);
        card.classList.toggle("empty", !on);
        card.querySelector(".bdot").classList.toggle("on", on);
        card.setAttribute(
          "aria-label",
          on ? key + " assigned — press Enter to change" : key + " — press Enter to assign"
        );
        hint.innerHTML = on
          ? '<span class="bhint-text">Change</span><span class="bhint-caret">▾</span>'
          : '<span class="bhint-text">Click to assign</span>';
      };

      const sel = window.PyMixerAppPicker.create({
        special: BUTTON_SPECIAL,
        current: isUrl ? "__url__" : value,
        dataAttr: "btn",
        dataKey: key,
        compact: true,
        getCatalog: () => state.appCatalog,
        looksLikeUrl: looksLikeUrl,
        onChange: (v) => {
          const show = v === "__url__";
          url.classList.toggle("show", show);
          if (!show) url.value = "";
          syncCardChrome(v);
        },
      });

      const openPicker = () => {
        if (typeof sel.open === "function") sel.open(card);
      };

      card.addEventListener("click", (e) => {
        if (url.contains(e.target)) return;
        e.preventDefault();
        openPicker();
      });
      card.addEventListener("keydown", (e) => {
        if (e.target === url) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openPicker();
        }
      });

      card.appendChild(sel);
      card.appendChild(hint);
      card.appendChild(url);
      root.appendChild(card);
    }
  }

  function renderConn() {
    const cfg = state.config;
    const pill = $("status-pill");
    const text = $("status-text");
    const cbtn = $("btn-controller");
    const cchk = $("chk-virtual-controller");
    if (cchk) cchk.checked = !!state.virtualControllerEnabled;
    if (cbtn) cbtn.hidden = !state.virtualControllerEnabled;
    if (state.demo) {
      pill.classList.remove("off");
      text.textContent = "Demo";
    } else if (state.connected) {
      pill.classList.remove("off");
      text.textContent = "Connected";
    } else {
      pill.classList.add("off");
      text.textContent = "Disconnected";
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
    if (!api()) {
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
    if (!api()) {
      toast("Not connected to the tray app — cannot save", true);
      return;
    }
    $("btn-save").disabled = true;
    try {
      const result = await call("save_config", cfg);
      if (result && result.ok === false) {
        toast(result.error || "Could not save settings. Try again.", true);
        return;
      }
      state.config = result && result.APP_MAPPINGS ? result : cfg;
      if (result && result.app_catalog) state.appCatalog = result.app_catalog;
      toast("Configuration saved");
      try {
        const status = await call("get_state");
        state.connected = !!status.connected;
        state.ports = status.ports || state.ports;
        if (status.app_catalog) state.appCatalog = status.app_catalog;
        if (status.live) state.live = status.live;
      } catch (_) {}
      renderConn();
    } catch (err) {
      const msg = String(err.message || err);
      // Never show raw filesystem paths in the toast
      if (/WinError|Access is denied|config\.py|\\|\//i.test(msg)) {
        toast("Could not save settings. Close other PyMixer windows and try again.", true);
      } else {
        toast(msg, true);
      }
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
      if (!api()) {
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
      if (!api()) {
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
    // Always read from the Python bridge when available.
    // Never invent placeholder / drifting percentages (that hid real board values).
    if (!api()) {
      state.live = { stale: true, connected: false, knobs: {} };
      const n = (state.config && state.config.NUM_KNOBS) || 5;
      for (let i = 1; i <= n; i++) updateFaderDom("K" + i);
      return;
    }
    try {
      const cfg = collectFromDom() || state.config;
      let live;
      try {
        live = await call("get_live_levels_for", cfg);
      } catch (_) {
        live = await call("get_live_levels");
      }
      state.live = live || { stale: true, knobs: {} };
      const n = (state.config && state.config.NUM_KNOBS) || 5;
      for (let i = 1; i <= n; i++) updateFaderDom("K" + i);
    } catch (_) {
      /* bridge momentarily unavailable — keep last good reading, mark stale next tick */
    }
  }

  function startLivePoll() {
    if (state.liveTimer) clearInterval(state.liveTimer);
    state.liveTimer = setInterval(pollLive, LIVE_POLL_MS);
    pollLive();
  }

  function wire() {
    $("btn-save").addEventListener("click", onSave);

  const vcChk = $("chk-virtual-controller");
  if (vcChk) {
    vcChk.addEventListener("change", () => {
      state.virtualControllerEnabled = !!vcChk.checked;
      const b = $("btn-controller");
      if (b) b.hidden = !vcChk.checked;
    });
  }

    const cbtn = $("btn-controller");
    if (cbtn) {
      cbtn.addEventListener("click", async () => {
        // Ensure toggle is on in the form; user must Save for tray persistence
        const _vc = $("chk-virtual-controller");
        if (_vc && !_vc.checked) {
          _vc.checked = true;
          state.virtualControllerEnabled = true;
          if ($("btn-controller")) $("btn-controller").hidden = false;
        }
        try { await call("show_controller"); } catch (e) { console.warn(e); }
      });
    }
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
          appPickers: document.querySelectorAll(".app-picker").length,
          nativeAppSelects: document.querySelectorAll("select.dd, select.bact-select").length,
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
    wire();
    if (!api()) {
      offlineShell();
      render();
      stamp();
      // Retry briefly — pywebviewready may fire slightly after DOMContentLoaded
      let tries = 0;
      const retry = setInterval(() => {
        tries += 1;
        if (api() || tries > 40) {
          clearInterval(retry);
          if (api()) {
            refresh().then(startLivePoll).then(stamp).catch(stamp);
          }
        }
      }, 100);
      return;
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
    offlineShell,
    pollLive,
    updateFaderDom,
    stamp,
  };
})();
