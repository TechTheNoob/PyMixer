(function () {
  "use strict";
  const state = { data: null, waiting: false, timer: null };

  const $ = (id) => document.getElementById(id);

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  async function call(method, ...args) {
    const a = api();
    if (!a || typeof a[method] !== "function") throw new Error("Bridge not ready");
    return a[method](...args);
  }

  function emptyLive() {
    return { stale: true, connected: false, knobs: {} };
  }

  function emptyState() {
    return {
      active: "—",
      profiles: [],
      icons: {},
      connected: false,
      live: emptyLive(),
    };
  }

  async function refresh() {
    if (!api()) {
      state.data = emptyState();
      state.waiting = true;
      render();
      return;
    }
    try {
      state.data = await call("get_popup_state");
      state.waiting = false;
    } catch (e) {
      state.data = emptyState();
      state.waiting = true;
    }
    render();
  }

  function renderLevels() {
    const root = $("levels");
    if (!root) return;
    root.innerHTML = "";
    const live = (state.data && state.data.live) || emptyLive();
    for (let i = 1; i <= 5; i++) {
      const key = "K" + i;
      const entry = (live.knobs || {})[key] || {};
      const stale = !!live.stale || entry.pct == null;
      const pct = stale ? null : Math.max(0, Math.min(100, Math.round(Number(entry.pct))));
      const show = pct == null ? 0 : pct;
      const el = document.createElement("div");
      el.className = "lvl" + (stale ? " stale" : "");
      el.dataset.knob = key;
      el.innerHTML =
        '<div class="t">' +
        key +
        "</div>" +
        '<div class="bar' +
        (stale ? " stale" : "") +
        '">' +
        '<div class="fill" style="height:' +
        show +
        "%;opacity:" +
        (stale ? "0.35" : "1") +
        '"></div>' +
        '<div class="knob" style="bottom:calc(' +
        show +
        "% - 5px);opacity:" +
        (stale ? "0.35" : "1") +
        '"></div>' +
        "</div>" +
        '<div class="p' +
        (stale ? " dim" : "") +
        '">' +
        (pct == null ? "—" : pct + "%") +
        "</div>";
      root.appendChild(el);
    }
  }

  function renderProfiles() {
    const root = $("profiles");
    if (!root) return;
    root.innerHTML = "";
    const data = state.data || emptyState();
    const active = data.active || "";
    const icons = data.icons || {};
    (data.profiles || []).forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pitem" + (name === active ? " active" : "");
      btn.setAttribute("data-profile", name);
      const icon = icons[name] || (name.slice(0, 1) || "?").toUpperCase();
      btn.innerHTML =
        '<span class="ico" aria-hidden="true"></span> ' +
        '<span class="lab"></span>' +
        '<span class="check" aria-hidden="true">✓</span>';
      btn.querySelector(".ico").textContent = icon;
      btn.querySelector(".lab").textContent = name;
      btn.addEventListener("click", () => onSwitch(name));
      root.appendChild(btn);
    });
  }

  function render() {
    const data = state.data || emptyState();
    const activeEl = $("active-profile");
    if (activeEl) activeEl.textContent = data.active || "—";
    const pill = $("status-pill");
    const text = $("status-text");
    if (pill && text) {
      if (data.connected) {
        pill.classList.remove("off");
        text.textContent = "Live";
      } else {
        pill.classList.add("off");
        text.textContent = state.waiting ? "Waiting…" : "Offline";
      }
    }
    renderLevels();
    renderProfiles();
    const cbtn = $("btn-controller");
    if (cbtn) cbtn.hidden = !data.show_controller;
    stamp();
  }

  async function onSwitch(name) {
    if (!api()) return;
    try {
      await call("switch_profile", name);
      await call("dismiss");
    } catch (e) {
      console.warn(e);
    }
  }

  async function onSettings() {
    if (!api()) return;
    try {
      await call("open_settings");
      await call("dismiss");
    } catch (e) {
      console.warn(e);
    }
  }

  async function onController() {
    if (!api()) return;
    try {
      await call("show_controller");
    } catch (e) {
      console.warn(e);
    }
  }

  async function onReconnect() {
    if (!api()) return;
    try {
      await call("reconnect");
      await refresh();
    } catch (e) {
      console.warn(e);
    }
  }

  async function onQuit() {
    if (!api()) return;
    try {
      await call("quit_app");
    } catch (e) {
      console.warn(e);
    }
  }

  function stamp() {
    try {
      const d = state.data || {};
      document.documentElement.setAttribute(
        "data-tray-popup",
        JSON.stringify({
          active: d.active || null,
          profiles: d.profiles || [],
          connected: !!d.connected,
          profileButtons: Array.from(document.querySelectorAll("#profiles .pitem")).map((b) => ({
            className: b.className,
            lab: ((b.querySelector(".lab") || {}).textContent || ""),
            text: (b.textContent || "").replace(/\s+/g, " ").trim(),
          })),
        })
      );
    } catch (_) {}
  }

  function wire() {
    const s = $("btn-settings");
    const r = $("btn-reconnect");
    const q = $("btn-quit");
    const c = $("btn-controller");
    if (s) s.addEventListener("click", onSettings);
    if (r) r.addEventListener("click", onReconnect);
    if (q) q.addEventListener("click", onQuit);
    if (c) c.addEventListener("click", onController);
    let blurTimer = null;
    const dismiss = () => call("dismiss").catch(() => {});
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape") dismiss();
    });
    window.addEventListener("blur", () => {
      clearTimeout(blurTimer);
      blurTimer = setTimeout(() => {
        if (!document.hasFocus()) dismiss();
      }, 220);
    });
    window.addEventListener("focus", () => {
      clearTimeout(blurTimer);
    });
  }

  function startLivePoll() {
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(async () => {
      if (!api()) return;
      try {
        const live = await call("get_live");
        if (state.data) state.data.live = live;
        renderLevels();
      } catch (_) {}
    }, 150);
  }

  function boot() {
    wire();
    refresh().then(startLivePoll);
  }

  window.addEventListener("pywebviewready", boot);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (!api()) {
        wire();
        refresh();
        let tries = 0;
        const retry = setInterval(() => {
          tries += 1;
          if (api() || tries > 40) {
            clearInterval(retry);
            if (api()) boot();
          }
        }, 100);
      }
    });
  } else if (!api()) {
    wire();
    refresh();
  }

  window.__tray_popup = { refresh, render, renderLevels, renderProfiles, state };
})();
