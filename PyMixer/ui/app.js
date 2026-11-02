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

  const state = {
    config: null,
    ports: [],
    apps: [],
    connected: false,
    demo: false,
    modalMode: null, // 'add' | 'rename'
    ctxProfile: null,
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
      PROFILES: {
        Gaming: null,
        Work: null,
        Music: null,
      },
    };
    // Fill profile payloads from active mappings for demo
    const payload = {
      APP_MAPPINGS: { ...state.config.APP_MAPPINGS },
      SLIDER_REVERSE: { ...state.config.SLIDER_REVERSE },
      SLIDER_SENSITIVITY: { ...state.config.SLIDER_SENSITIVITY },
    };
    state.config.PROFILES.Gaming = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Work = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Work.APP_MAPPINGS.K3 = "Code.exe";
    state.config.PROFILES.Music = JSON.parse(JSON.stringify(payload));
    state.config.PROFILES.Music.APP_MAPPINGS.K4 = "spotify.exe";
  }

  async function refresh() {
    try {
      const data = await call("get_state");
      state.config = data.config;
      state.ports = data.ports || [];
      state.apps = data.apps || [];
      state.connected = !!data.connected;
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

    for (let i = 1; i <= numKnobs; i++) {
      const key = "K" + i;
      const sel = document.querySelector(`[data-knob="${key}"]`);
      const rev = document.querySelector(`[data-reverse="${key}"]`);
      const sens = document.querySelector(`[data-sens="${key}"]`);
      if (sel) cfg.APP_MAPPINGS[key] = sel.value;
      if (rev) cfg.SLIDER_REVERSE[key] = !!rev.checked;
      if (sens) cfg.SLIDER_SENSITIVITY[key] = parseFloat(sens.value) || 1.0;
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
      const itemWrap = document.createElement("div");
      itemWrap.className = "rail-wrap" + (name === cfg.ACTIVE_PROFILE ? " active" : "");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rail-item" + (name === cfg.ACTIVE_PROFILE ? " active" : "");
      btn.title = name;
      btn.textContent = icons[name] || name.slice(0, 1).toUpperCase();
      btn.addEventListener("click", () => onSwitchProfile(name));
      btn.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        openCtx(e.clientX, e.clientY, name);
      });
      const label = document.createElement("div");
      label.className = "rail-label";
      label.textContent = name;
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
      const pct = value ? 72 : 10;

      const card = document.createElement("div");
      card.className = "channel" + (value ? "" : " off");
      card.innerHTML = `
        <div class="badge ${badgeClass(value)}">${badgeText(value)}</div>
        <div class="ch-name">${displayName(value)}</div>
        <div class="ch-sub">Knob ${i}</div>
        <div class="fader-wrap">
          <div class="fader">
            <div class="fader-fill" style="height:${pct}%;${value ? "" : "opacity:0.45"}"></div>
            <div class="fader-knob" style="bottom:calc(${pct}% - 7px);${value ? "" : "opacity:0.6"}"></div>
          </div>
        </div>
        <div class="vol ${value ? "" : "dim"}">${value ? pct + "<span>%</span>" : "—"}</div>
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
      const opts = document.createElement("div");
      opts.className = "opts";
      opts.innerHTML = `
        <label class="chk"><input type="checkbox" data-reverse="${key}" ${rev ? "checked" : ""}/> Reverse</label>
        <div class="sens">
          <span class="sens-val">${Number(sens).toFixed(1)}</span>
          <input type="range" min="0.2" max="2" step="0.1" value="${sens}" data-sens="${key}" />
        </div>
      `;
      const range = opts.querySelector("input[type=range]");
      const sensVal = opts.querySelector(".sens-val");
      range.addEventListener("input", () => {
        sensVal.textContent = Number(range.value).toFixed(1);
      });
      controls.appendChild(sel);
      controls.appendChild(opts);
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
      url.className = "burl-input";
      url.dataset.url = key;
      url.placeholder = "URL…";
      url.value = isUrl ? value : "";
      url.disabled = sel.value !== "__url__";
      sel.addEventListener("change", () => {
        url.disabled = sel.value !== "__url__";
        if (sel.value !== "__url__") url.value = "";
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

  async function onSwitchProfile(name) {
    if (!state.config || name === state.config.ACTIVE_PROFILE) return;
    collectFromDom();
    if (state.demo) {
      // stash current into active, then switch
      const cur = state.config.ACTIVE_PROFILE;
      state.config.PROFILES[cur] = {
        APP_MAPPINGS: { ...state.config.APP_MAPPINGS },
        SLIDER_REVERSE: { ...state.config.SLIDER_REVERSE },
        SLIDER_SENSITIVITY: { ...state.config.SLIDER_SENSITIVITY },
      };
      const next = state.config.PROFILES[name];
      state.config.ACTIVE_PROFILE = name;
      state.config.APP_MAPPINGS = { ...next.APP_MAPPINGS };
      state.config.SLIDER_REVERSE = { ...next.SLIDER_REVERSE };
      state.config.SLIDER_SENSITIVITY = { ...next.SLIDER_SENSITIVITY };
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
          state.config.PROFILES[name] = {
            APP_MAPPINGS: { ...state.config.APP_MAPPINGS },
            SLIDER_REVERSE: { ...state.config.SLIDER_REVERSE },
            SLIDER_SENSITIVITY: { ...state.config.SLIDER_SENSITIVITY },
          };
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
      // focus delete path
      onModalDelete();
    });
    document.addEventListener("click", (e) => {
      if (!$("rail-ctx").contains(e.target)) closeCtx();
    });
    $("btn-close").addEventListener("click", async () => {
      try {
        await call("close_window");
      } catch (_) {
        /* ignore */
      }
    });
  }

  function onReady() {
    wire();
    refresh();
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
        })
      );
    } catch (e) {
      document.documentElement.setAttribute("data-pymixer", JSON.stringify({ err: String(e) }));
    }
  }

  window.addEventListener("pywebviewready", onReady);
  // Fallback for opening the HTML directly (screenshots / demos)
  function bootFallback() {
    if (state.config) {
      stamp();
      return;
    }
    // No pywebview bridge → demo immediately (sync), then try async refresh
    if (!api()) {
      demoBootstrap();
      wire();
      render();
      stamp();
    }
    refresh().then(stamp).catch(stamp);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootFallback);
  } else {
    bootFallback();
  }

  // Expose for headless tests
  window.__pymixer = { refresh, render, state, collectFromDom, demoBootstrap };
})();
