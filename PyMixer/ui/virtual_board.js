
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { knobs: {}, paused: false };

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  async function call(method, ...args) {
    const a = api();
    if (!a || typeof a[method] !== "function") throw new Error("bridge");
    return a[method](...args);
  }

  function build() {
    const knobs = $("knobs");
    const btns = $("btns");
    knobs.innerHTML = "";
    btns.innerHTML = "";
    for (let i = 1; i <= 5; i++) {
      const key = "K" + i;
      const card = document.createElement("div");
      card.className = "kcard";
      card.innerHTML =
        '<div class="lab">' + key + "</div>" +
        '<div class="slider-wrap"><input class="vslider" type="range" min="0" max="1023" value="512" data-knob="' + key + '" /></div>' +
        '<div class="val" data-val="' + key + '">512</div>';
      knobs.appendChild(card);
      const input = card.querySelector("input");
      input.addEventListener("input", async () => {
        const v = Number(input.value);
        card.querySelector('[data-val="' + key + '"]').textContent = String(v);
        try { await call("set_knob", key, v); } catch (_) {}
      });
    }
    for (let i = 1; i <= 10; i++) {
      const key = "B" + i;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "bbtn";
      b.textContent = key;
      b.addEventListener("click", async () => {
        try { await call("pulse_button", key); } catch (_) {}
      });
      btns.appendChild(b);
    }
  }

  function applyPaused(paused, reason) {
    state.paused = !!paused;
    const board = $("board");
    const banner = $("banner");
    const sub = $("subtitle");
    board.classList.toggle("paused", state.paused);
    banner.hidden = !state.paused;
    if (state.paused) {
      banner.textContent = reason || "Real board connected";
      sub.textContent = "Virtual inputs paused while hardware is live";
    } else {
      sub.textContent = "Moves change real Windows volume";
    }
    document.querySelectorAll("input.vslider, button.bbtn").forEach((el) => {
      el.disabled = state.paused;
    });
  }

  async function refresh() {
    if (!api()) return;
    try {
      const data = await call("get_board_state");
      applyPaused(!!data.real_board, data.real_board_reason || "Real board connected");
      const knobs = data.knobs || {};
      for (let i = 1; i <= 5; i++) {
        const key = "K" + i;
        const v = Math.max(0, Math.min(1023, Number(knobs[key] != null ? knobs[key] : 512)));
        const input = document.querySelector('input[data-knob="' + key + '"]');
        const label = document.querySelector('[data-val="' + key + '"]');
        if (input && Number(input.value) !== v && document.activeElement !== input) {
          input.value = String(v);
        }
        if (label) label.textContent = String(v);
      }
    } catch (_) {}
  }

  function boot() {
    build();
    refresh();
    setInterval(refresh, 250);
  }

  window.addEventListener("pywebviewready", boot);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(boot, 200));
  } else {
    setTimeout(boot, 200);
  }
})();
