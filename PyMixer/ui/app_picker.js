/* Discord-dark searchable app picker for PyMixer settings */
(function (global) {
  "use strict";

  function displayName(value) {
    if (!value) return "Unassigned";
    if (value === "focused_app") return "Focused App";
    if (value === "explorer.exe") return "Master Volume";
    if (value === "toggle_mic_mute") return "Mic Mute";
    if (value === "toggle_master_mute") return "Master Mute";
    if (value === "lock_pc") return "Lock PC";
    if (value === "next_profile") return "Next Profile";
    if (value === "__url__") return "Open Webpage…";
    if (String(value).startsWith("profile:")) return "Profile: " + value.slice(8);
    return String(value).replace(/\.exe$/i, "");
  }

  let openPicker = null;

  function closeAppPicker() {
    if (openPicker) {
      openPicker.classList.remove("open");
      openPicker = null;
    }
  }

  function labelForValue(value, special, catalog) {
    if (!value) return "— none —";
    const hit = (special || []).find((o) => o.value === value);
    if (hit) return hit.label;
    const cat = catalog || {};
    for (const group of [cat.audio || [], cat.running || []]) {
      const e = group.find((x) => x.value === value);
      if (e) return e.label;
    }
    return displayName(value);
  }

  function createAppPicker(opts) {
    const special = opts.special || [];
    const getCatalog = opts.getCatalog || (() => ({ audio: [], running: [] }));
    const onChange = opts.onChange || (() => {});
    const compact = !!opts.compact;
    const current = opts.current || "";
    const looksLikeUrl = opts.looksLikeUrl || (() => false);

    const root = document.createElement("div");
    root.className = "app-picker" + (compact ? " compact" : "");
    if (opts.dataAttr && opts.dataKey) root.dataset[opts.dataAttr] = opts.dataKey;

    Object.defineProperty(root, "value", {
      get() {
        return root.dataset.value || "";
      },
      set(v) {
        root.dataset.value = v == null ? "" : String(v);
        const lab = root.querySelector(".ap-label");
        if (lab) lab.textContent = labelForValue(root.dataset.value, special, getCatalog());
      },
    });

    const initial = looksLikeUrl(current) ? "__url__" : current || "";
    root.dataset.value = initial;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ap-btn";
    btn.innerHTML = '<span class="ap-label"></span><span class="ap-caret">▾</span>';
    btn.querySelector(".ap-label").textContent = labelForValue(initial, special, getCatalog());

    const panel = document.createElement("div");
    panel.className = "ap-panel";
    panel.innerHTML =
      '<div class="ap-search-wrap"><input class="ap-search" type="text" placeholder="Search apps…" spellcheck="false" /></div>' +
      '<div class="ap-list" role="listbox"></div>' +
      '<div class="ap-manual">' +
      '<button type="button" class="ap-manual-toggle">Type an .exe…</button>' +
      '<div class="ap-manual-row">' +
      '<input class="ap-manual-input" type="text" placeholder="MyApp.exe" spellcheck="false" />' +
      '<button type="button" class="ap-manual-ok">Use</button>' +
      "</div></div>";

    let showAll = false;
    let activeIndex = -1;
    let flat = [];

    function buildGroups(filter) {
      const q = (filter || "").trim().toLowerCase();
      const cat = getCatalog() || { audio: [], running: [] };
      const groups = [];
      const seen = new Set();

      function pushGroup(title, items) {
        const rows = [];
        (items || []).forEach((item) => {
          const value = item.value;
          const label = item.label || displayName(value);
          if (seen.has(value)) return;
          if (q && !String(label).toLowerCase().includes(q) && !String(value).toLowerCase().includes(q))
            return;
          seen.add(value);
          rows.push({ value, label });
        });
        if (rows.length) groups.push({ title: title, rows: rows });
      }

      pushGroup(
        "Special actions",
        special.map((o) => ({ value: o.value, label: o.label }))
      );

      if (
        initial &&
        initial !== "__url__" &&
        !seen.has(initial) &&
        /\.exe$/i.test(initial)
      ) {
        if (!q || initial.toLowerCase().includes(q) || displayName(initial).toLowerCase().includes(q)) {
          pushGroup("Current", [{ value: initial, label: displayName(initial) }]);
        }
      }

      pushGroup("Apps currently playing audio", cat.audio || []);

      const running = cat.running || [];
      if (showAll) {
        pushGroup("Other running apps", running);
      } else if (running.length) {
        groups.push({ title: "Other running apps", rows: [], expander: true, count: running.length });
        if (q) {
          const matched = running.filter(
            (e) =>
              String(e.label).toLowerCase().includes(q) || String(e.value).toLowerCase().includes(q)
          );
          if (matched.length) pushGroup("Other running apps (matches)", matched);
        }
      }
      return groups;
    }

    function renderList() {
      const list = panel.querySelector(".ap-list");
      const filter = panel.querySelector(".ap-search").value;
      list.innerHTML = "";
      flat = [];
      activeIndex = -1;
      buildGroups(filter).forEach((g) => {
        const head = document.createElement("div");
        head.className = "ap-group";
        head.textContent = g.title;
        list.appendChild(head);
        if (g.expander && !showAll) {
          const exp = document.createElement("button");
          exp.type = "button";
          exp.className = "ap-expand";
          exp.textContent = "Show all running apps… (" + g.count + ")";
          exp.addEventListener("click", (e) => {
            e.stopPropagation();
            showAll = true;
            renderList();
          });
          list.appendChild(exp);
          return;
        }
        g.rows.forEach((row) => {
          const el = document.createElement("button");
          el.type = "button";
          el.className = "ap-option" + (row.value === root.value ? " selected" : "");
          el.setAttribute("role", "option");
          el.dataset.value = row.value;
          el.innerHTML = '<span class="ap-opt-label"></span><span class="ap-opt-sub"></span>';
          el.querySelector(".ap-opt-label").textContent = row.label;
          if (row.value && /\.exe$/i.test(row.value) && row.label !== row.value) {
            el.querySelector(".ap-opt-sub").textContent = row.value;
          }
          el.addEventListener("click", (e) => {
            e.stopPropagation();
            pick(row.value);
          });
          list.appendChild(el);
          flat.push(el);
        });
      });
    }

    function pick(value) {
      root.value = value;
      closeAppPicker();
      onChange(value);
    }

    function open() {
      if (openPicker === root) {
        closeAppPicker();
        return;
      }
      closeAppPicker();
      showAll = false;
      root.classList.add("open");
      openPicker = root;
      renderList();
      const search = panel.querySelector(".ap-search");
      search.value = "";
      setTimeout(function () {
        search.focus();
      }, 0);
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      open();
    });
    panel.querySelector(".ap-search").addEventListener("input", renderList);
    panel.querySelector(".ap-search").addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIndex = Math.min(flat.length - 1, activeIndex + 1);
        flat.forEach(function (el, i) {
          el.classList.toggle("active", i === activeIndex);
        });
        if (flat[activeIndex]) flat[activeIndex].scrollIntoView({ block: "nearest" });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = Math.max(0, activeIndex - 1);
        flat.forEach(function (el, i) {
          el.classList.toggle("active", i === activeIndex);
        });
        if (flat[activeIndex]) flat[activeIndex].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (activeIndex >= 0 && flat[activeIndex]) pick(flat[activeIndex].dataset.value);
      } else if (e.key === "Escape") {
        e.preventDefault();
        closeAppPicker();
      }
    });

    const manualRow = panel.querySelector(".ap-manual-row");
    panel.querySelector(".ap-manual-toggle").addEventListener("click", function (e) {
      e.stopPropagation();
      manualRow.classList.toggle("show");
      if (manualRow.classList.contains("show")) panel.querySelector(".ap-manual-input").focus();
    });
    panel.querySelector(".ap-manual-ok").addEventListener("click", function (e) {
      e.stopPropagation();
      var v = panel.querySelector(".ap-manual-input").value.trim();
      if (!v) return;
      if (!/\.exe$/i.test(v)) v += ".exe";
      pick(v);
    });

    root.appendChild(btn);
    root.appendChild(panel);
    return root;
  }

  document.addEventListener("click", function (e) {
    if (openPicker && !openPicker.contains(e.target)) closeAppPicker();
  });

  global.PyMixerAppPicker = {
    create: createAppPicker,
    close: closeAppPicker,
    displayName: displayName,
  };
})(window);
