(function () {
  "use strict";
  const state = { data: null, demo: false, timer: null, waiting: false };

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

  async function refresh() {
    if (!api()) {
      state.data = {
        active: "—",
        profiles: [],
        icons: {},
        connected: false,
        demo: false,
        live: emptyLive(),
      };
      state.demo = false;
      state.waiting = true;
      render();
      return;
    }
    try {
      state.data = await call("get_popup_state");
      // Hardware demo flag is for status only — never invent live numbers
      state.demo = !!(state.data && state.data.demo);
      state.waiting = false;
    } catch (e) {
      state.data = {
        active: "—",
        profiles: [],
        icons: {},
        connected: false,
        demo: false,
        live: emptyLive(),
      };
      state.demo = false;
      state.waiting = true;
    }
    render();
  }

  function renderLevels() {
    const root = $("levels");
    root.innerHTML = "";
    const live = (state.data && state.data.live) || emptyLive();
    for (let i = 1; i <= 5; i++) {
      const key = "K" + i;
      const entry = (live.knobs || {})[key] || {};
      const stale = !!live.stale || entry.pct == null;
      const pct = stale ? null : Math.max(0, Math.min(100, Math.round(Number(entry.pct) || 0)));
      const row = document.createElement("div");
      row.className = "level" + (stale ? " stale" : "");
      row.dataset.knob = key;
      row.innerHTML =
        '<span class="k">' +
        key +
        '</span><div class="bar"><i style="width:' +
        (pct == null ? 0 : pct) +
        '%"></i></div><span class="pct">' +
        (pct == null ? "—" : pct + "%") +
        "</span>";
      root.appendChild(row);
    }
  }

  function render() {
    const d = state.data || {};
    $("active-profile").textContent = d.active || "—";
    const pill = $("status-pill");
    const text = $("status-text");
    if (state.demo || d.demo) {
      pill.classList.remove("off");
      text.textContent = "Demo";
    } else if (d.connected) {
      pill.classList.remove("off");
      text.textContent = "Online";
    } else {
      pill.classList.add("off");
      text.textContent = state.waiting ? "Waiting…" : "Offline";
    }
    const list = $("profiles");
    list.innerHTML = "";
    (d.profiles || []).forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "prof" + (name === d.active ? " active" : "");
      const icon = (d.icons && d.icons[name]) || (name[0] || "?").toUpperCase();
      btn.innerHTML = '<span class="ic">' + icon + "</span><span>" + name + "</span>";
      btn.addEventListener("click", () => onSwitch(name));
      list.appendChild(btn);
    });
    renderLevels();
  }

  async function onSwitch(name) {
    if (!api()) return;
    try {
      await call("switch_profile", name);
      await refresh();
    } catch (_) {}
  }

  async function onSettings() {
    if (!api()) return;
    try {
      await call("open_settings");
    } catch (_) {}
  }

  async function onReconnect() {
    if (!api()) return;
    try {
      await call("reconnect");
      await refresh();
    } catch (_) {}
  }

  async function onQuit() {
    if (!api()) return;
    try {
      await call("quit_app");
    } catch (_) {}
  }

  function wire() {
    $("btn-settings").addEventListener("click", onSettings);
    $("btn-reconnect").addEventListener("click", onReconnect);
    $("btn-quit").addEventListener("click", onQuit);
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
        // Empty shell — show "—", then boot when bridge appears
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

  window.__tray_popup = { refresh, render, renderLevels, state };
})();
