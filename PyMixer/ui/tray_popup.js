(function () {
  "use strict";
  const state = { data: null, demo: false, timer: null };

  const $ = (id) => document.getElementById(id);

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  async function call(method, ...args) {
    const a = api();
    if (!a || typeof a[method] !== "function") throw new Error("Bridge not ready");
    return a[method](...args);
  }

  function demoData() {
    return {
      active: "Gaming",
      profiles: ["Default", "Gaming", "Work", "Music"],
      icons: { Default: "D", Gaming: "G", Work: "W", Music: "M" },
      connected: true,
      live: {
        stale: false,
        knobs: {
          K1: { pct: 55 }, K2: { pct: 12 }, K3: { pct: 72 }, K4: { pct: 68 }, K5: { pct: 40 },
        },
      },
    };
  }

  async function refresh() {
    try {
      state.data = await call("get_popup_state");
      state.demo = false;
    } catch (e) {
      state.data = demoData();
      state.demo = true;
    }
    render();
  }

  function renderLevels() {
    const root = $("levels");
    root.innerHTML = "";
    const live = (state.data && state.data.live) || { stale: true, knobs: {} };
    for (let i = 1; i <= 5; i++) {
      const key = "K" + i;
      const entry = (live.knobs || {})[key] || {};
      const stale = !!live.stale || entry.pct == null;
      const pct = stale ? 0 : Math.max(0, Math.min(100, Math.round(Number(entry.pct))));
      const el = document.createElement("div");
      el.className = "lvl";
      el.innerHTML =
        '<div class="t">K' + i + "</div>" +
        '<div class="bar' + (stale ? " stale" : "") + '">' +
        '<div class="fill" style="height:' + pct + '%;opacity:' + (stale ? "0.35" : "1") + '"></div>' +
        '<div class="knob" style="bottom:calc(' + pct + '% - 5px);opacity:' + (stale ? "0.35" : "1") + '"></div>' +
        "</div>" +
        '<div class="p' + (stale ? " dim" : "") + '">' + (stale ? "—" : pct + "%") + "</div>";
      root.appendChild(el);
    }
  }

  function renderProfiles() {
    const root = $("profiles");
    root.innerHTML = "";
    const data = state.data || demoData();
    const active = data.active || "Default";
    const icons = data.icons || {};
    (data.profiles || []).forEach((name) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "pitem" + (name === active ? " active" : "");
      btn.innerHTML =
        '<span class="ico">' + (icons[name] || name.slice(0, 1).toUpperCase()) + "</span>" +
        '<span class="lab"></span><span class="check">✓</span>';
      btn.querySelector(".lab").textContent = name;
      btn.addEventListener("click", () => onSwitch(name));
      root.appendChild(btn);
    });
  }

  function render() {
    const data = state.data || demoData();
    $("active-profile").textContent = data.active || "Default";
    const pill = $("status-pill");
    const text = $("status-text");
    if (data.demo || state.demo) {
      pill.classList.remove("off");
      text.textContent = "Demo";
      state.demo = true;
    } else if (data.connected) {
      pill.classList.remove("off");
      text.textContent = "Live";
    } else {
      pill.classList.add("off");
      text.textContent = "Offline";
    }
    renderLevels();
    renderProfiles();
    stamp();
  }

  async function onSwitch(name) {
    if (state.demo) {
      state.data.active = name;
      render();
      setTimeout(() => call("dismiss").catch(() => {}), 120);
      return;
    }
    try {
      await call("switch_profile", name);
      await call("dismiss");
    } catch (e) {
      console.warn(e);
    }
  }

  async function onSettings() {
    if (state.demo) return;
    try {
      await call("open_settings");
      await call("dismiss");
    } catch (e) {
      console.warn(e);
    }
  }

  async function onReconnect() {
    if (state.demo) {
      state.data.connected = true;
      render();
      return;
    }
    try {
      await call("reconnect");
      await refresh();
    } catch (e) {
      console.warn(e);
    }
  }

  async function onQuit() {
    if (state.demo) return;
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
          demo: !!state.demo,
          active: d.active || null,
          profiles: d.profiles || [],
          connected: !!d.connected,
          hasFakeChrome: !!document.querySelector(".titlebar, .winbtns, #btn-close"),
        })
      );
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
      // Debounce: tray icon click can blur then immediately re-show
      clearTimeout(blurTimer);
      blurTimer = setTimeout(() => {
        if (!document.hasFocus()) dismiss();
      }, 220);
    });
    window.addEventListener("focus", () => {
      clearTimeout(blurTimer);
    });
  }

  function boot() {
    wire();
    refresh().then(() => {
      if (state.timer) clearInterval(state.timer);
      state.timer = setInterval(async () => {
        if (state.demo) return;
        try {
          const live = await call("get_live");
          if (state.data) state.data.live = live;
          renderLevels();
        } catch (_) {}
      }, 150);
    });
  }

  window.addEventListener("pywebviewready", boot);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (!api()) {
        state.data = demoData();
        state.demo = true;
        wire();
        render();
      }
    });
  } else if (!api()) {
    state.data = demoData();
    state.demo = true;
    wire();
    render();
  }

  window.__tray_popup = { refresh, render, state, demoData };
})();
