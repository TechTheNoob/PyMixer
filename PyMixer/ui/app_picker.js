/* Discord-dark searchable app picker — body-level fixed portal */
(function (global) {
  "use strict";

  var MARGIN = 8;
  var MIN_WIDTH = 240;
  var openRoot = null;
  var openPanel = null;
  var openTrigger = null;
  var boundScrollClose = null;

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
    var s = String(value);
    if (/\.lnk$/i.test(s)) {
      var base = s.split(/\\|\//).pop() || s;
      return base.replace(/\.lnk$/i, "");
    }
    return s.replace(/\.exe$/i, "");
  }

  function labelForValue(value, special, catalog) {
    if (!value) return "— none —";
    var hit = (special || []).find(function (o) { return o.value === value; });
    if (hit) return hit.label;
    var cat = catalog || {};
    var groups = [cat.audio || [], cat.running || [], cat.installed || []];
    for (var g = 0; g < groups.length; g++) {
      var e = groups[g].find(function (x) { return x.value === value; });
      if (e) return e.label;
    }
    return displayName(value);
  }

  function closeAppPicker() {
    if (openPanel && openPanel.parentNode) {
      openPanel.parentNode.removeChild(openPanel);
    }
    if (openRoot) openRoot.classList.remove("open");
    if (boundScrollClose) {
      window.removeEventListener("scroll", boundScrollClose, true);
      window.removeEventListener("resize", boundScrollClose);
      boundScrollClose = null;
    }
    openRoot = null;
    openPanel = null;
    openTrigger = null;
  }

  function positionPanel(panel, trigger) {
    var rect = trigger.getBoundingClientRect();
    var vw = window.innerWidth || document.documentElement.clientWidth;
    var vh = window.innerHeight || document.documentElement.clientHeight;

    // Width: at least trigger, min 240, but never past viewport margins
    var maxW = Math.max(MIN_WIDTH, vw - MARGIN * 2);
    var width = Math.max(rect.width, MIN_WIDTH);
    if (width > maxW) width = maxW;
    // At very small windows, go near full width
    if (vw < 480) width = Math.max(vw - MARGIN * 2, 120);

    // Horizontal: prefer align to trigger left; clamp into viewport
    var left = rect.left;
    if (left + width > vw - MARGIN) left = vw - MARGIN - width;
    if (left < MARGIN) left = MARGIN;

    // Measure preferred height after content is in DOM
    panel.style.visibility = "hidden";
    panel.style.display = "flex";
    panel.style.position = "fixed";
    panel.style.left = "0px";
    panel.style.top = "0px";
    panel.style.width = width + "px";
    panel.style.maxHeight = "none";
    var list = panel.querySelector(".ap-list");
    if (list) list.style.maxHeight = "";
    // Force layout
    var natural = panel.getBoundingClientRect().height || 280;

    var spaceBelow = vh - rect.bottom - MARGIN;
    var spaceAbove = rect.top - MARGIN;
    var flipUp = spaceBelow < 160 && spaceAbove > spaceBelow;
    var available = flipUp ? spaceAbove : spaceBelow;
    // Always leave margin; ensure at least a usable height
    available = Math.max(120, Math.min(available, vh - MARGIN * 2));
    var maxHeight = Math.min(natural, available);

    var top;
    if (flipUp) {
      top = rect.top - maxHeight - 4;
      if (top < MARGIN) top = MARGIN;
    } else {
      top = rect.bottom + 4;
      if (top + maxHeight > vh - MARGIN) {
        maxHeight = Math.max(120, vh - MARGIN - top);
      }
      if (top < MARGIN) top = MARGIN;
    }

    // Cap list so search stays pinned; panel uses flex column
    var searchH = 0;
    var manualH = 0;
    var sw = panel.querySelector(".ap-search-wrap");
    var man = panel.querySelector(".ap-manual");
    if (sw) searchH = sw.getBoundingClientRect().height || 44;
    if (man) manualH = man.getBoundingClientRect().height || 36;
    var listMax = Math.max(60, maxHeight - searchH - manualH);
    if (list) list.style.maxHeight = listMax + "px";

    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
    panel.style.width = Math.round(width) + "px";
    panel.style.maxHeight = Math.round(maxHeight) + "px";
    panel.style.visibility = "visible";
    panel.dataset.flip = flipUp ? "up" : "down";
  }

  function createAppPicker(opts) {
    var special = opts.special || [];
    var getCatalog = opts.getCatalog || function () { return { audio: [], running: [] }; };
    var onChange = opts.onChange || function () {};
    var compact = !!opts.compact;
    var current = opts.current || "";
    var looksLikeUrl = opts.looksLikeUrl || function () { return false; };
    var onBrowse = opts.onBrowse || null;

    var root = document.createElement("div");
    root.className = "app-picker" + (compact ? " compact" : "");
    if (opts.dataAttr && opts.dataKey) root.dataset[opts.dataAttr] = opts.dataKey;

    Object.defineProperty(root, "value", {
      get: function () { return root.dataset.value || ""; },
      set: function (v) {
        root.dataset.value = v == null ? "" : String(v);
        var lab = root.querySelector(".ap-label");
        if (lab) lab.textContent = labelForValue(root.dataset.value, special, getCatalog());
      },
    });

    var initial = looksLikeUrl(current) ? "__url__" : current || "";
    root.dataset.value = initial;

    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ap-btn";
    btn.innerHTML = '<span class="ap-label"></span><span class="ap-caret">▾</span>';
    btn.querySelector(".ap-label").textContent = labelForValue(initial, special, getCatalog());

    var showAll = false;
    var activeIndex = -1;
    var flat = [];
    var panel = null;

    function buildPanel() {
      var el = document.createElement("div");
      el.className = "ap-panel ap-panel-portal";
      el.setAttribute("role", "dialog");
      el.innerHTML =
        '<div class="ap-search-wrap"><input class="ap-search" type="text" placeholder="Search apps…" spellcheck="false" /></div>' +
        '<div class="ap-list" role="listbox"></div>' +
        '<div class="ap-manual">' +
        '<button type="button" class="ap-browse">Browse for app…</button>' +
        '<button type="button" class="ap-manual-toggle">Type a name or path…</button>' +
        '<div class="ap-manual-row">' +
        '<input class="ap-manual-input" type="text" placeholder="MyApp.exe or path" spellcheck="false" />' +
        '<button type="button" class="ap-manual-ok">Use</button>' +
        "</div></div>";
      return el;
    }

    function buildGroups(filter) {
      var q = (filter || "").trim().toLowerCase();
      var cat = getCatalog() || { audio: [], running: [] };
      var groups = [];
      var seen = {};

      function pushGroup(title, items) {
        var rows = [];
        (items || []).forEach(function (item) {
          var value = item.value;
          var label = item.label || displayName(value);
          if (seen[value]) return;
          if (q && String(label).toLowerCase().indexOf(q) < 0 && String(value).toLowerCase().indexOf(q) < 0)
            return;
          seen[value] = true;
          rows.push({ value: value, label: label });
        });
        if (rows.length) groups.push({ title: title, rows: rows });
      }

      pushGroup(
        "Special actions",
        special.map(function (o) { return { value: o.value, label: o.label }; })
      );

      if (initial && initial !== "__url__" && !seen[initial] && /\.exe$/i.test(initial)) {
        if (!q || initial.toLowerCase().indexOf(q) >= 0 || displayName(initial).toLowerCase().indexOf(q) >= 0) {
          pushGroup("Current", [{ value: initial, label: displayName(initial) }]);
        }
      }

      pushGroup("Apps currently playing audio", cat.audio || []);

      var running = cat.running || [];
      if (showAll) {
        pushGroup("Other running apps", running);
      } else if (running.length) {
        groups.push({ title: "Other running apps", rows: [], expander: true, count: running.length });
        if (q) {
          var matched = running.filter(function (e) {
            return (
              String(e.label).toLowerCase().indexOf(q) >= 0 ||
              String(e.value).toLowerCase().indexOf(q) >= 0
            );
          });
          if (matched.length) pushGroup("Other running apps (matches)", matched);
        }
      }

      var installed = cat.installed || [];
      if (installed.length) {
        if (q) {
          var im = installed.filter(function (e) {
            return (
              String(e.label).toLowerCase().indexOf(q) >= 0 ||
              String(e.value).toLowerCase().indexOf(q) >= 0
            );
          });
          pushGroup("Installed apps (Start Menu)", im.slice(0, 80));
        } else {
          pushGroup("Installed apps (Start Menu)", installed.slice(0, 60));
        }
      }
      return groups;
    }

    function renderList() {
      if (!panel) return;
      var list = panel.querySelector(".ap-list");
      var filter = panel.querySelector(".ap-search").value;
      list.innerHTML = "";
      flat = [];
      activeIndex = -1;
      buildGroups(filter).forEach(function (g) {
        var head = document.createElement("div");
        head.className = "ap-group";
        head.textContent = g.title;
        list.appendChild(head);
        if (g.expander && !showAll) {
          var exp = document.createElement("button");
          exp.type = "button";
          exp.className = "ap-expand";
          exp.textContent = "Show all running apps… (" + g.count + ")";
          exp.addEventListener("click", function (e) {
            e.stopPropagation();
            showAll = true;
            renderList();
            positionPanel(panel, openTrigger || btn);
          });
          list.appendChild(exp);
          return;
        }
        g.rows.forEach(function (row) {
          var opt = document.createElement("button");
          opt.type = "button";
          opt.className = "ap-option" + (row.value === root.value ? " selected" : "");
          opt.setAttribute("role", "option");
          opt.dataset.value = row.value;
          opt.innerHTML = '<span class="ap-opt-label"></span><span class="ap-opt-sub"></span>';
          opt.querySelector(".ap-opt-label").textContent = row.label;
          if (row.value && /\.exe$/i.test(row.value) && row.label !== row.value) {
            opt.querySelector(".ap-opt-sub").textContent = row.value;
          }
          opt.addEventListener("click", function (e) {
            e.stopPropagation();
            pick(row.value);
          });
          list.appendChild(opt);
          flat.push(opt);
        });
      });
    }

    function pick(value) {
      root.value = value;
      closeAppPicker();
      onChange(value);
    }

    function open(anchor) {
      if (openRoot === root) {
        closeAppPicker();
        return;
      }
      closeAppPicker();
      showAll = false;
      root.classList.add("open");
      panel = buildPanel();
      document.body.appendChild(panel);
      openRoot = root;
      openPanel = panel;
      var trigger = anchor || btn;
      openTrigger = trigger;

      renderList();
      positionPanel(panel, trigger);

      var search = panel.querySelector(".ap-search");
      search.value = "";
      setTimeout(function () { search.focus(); }, 0);

      search.addEventListener("input", function () {
        renderList();
        positionPanel(panel, openTrigger || btn);
      });
      search.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          activeIndex = Math.min(flat.length - 1, activeIndex + 1);
          flat.forEach(function (el, i) { el.classList.toggle("active", i === activeIndex); });
          if (flat[activeIndex]) flat[activeIndex].scrollIntoView({ block: "nearest" });
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          activeIndex = Math.max(0, activeIndex - 1);
          flat.forEach(function (el, i) { el.classList.toggle("active", i === activeIndex); });
          if (flat[activeIndex]) flat[activeIndex].scrollIntoView({ block: "nearest" });
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (activeIndex >= 0 && flat[activeIndex]) pick(flat[activeIndex].dataset.value);
        } else if (e.key === "Escape") {
          e.preventDefault();
          closeAppPicker();
        }
      });

      var manualRow = panel.querySelector(".ap-manual-row");
      panel.querySelector(".ap-manual-toggle").addEventListener("click", function (e) {
        e.stopPropagation();
        manualRow.classList.toggle("show");
        positionPanel(panel, openTrigger || btn);
        if (manualRow.classList.contains("show")) panel.querySelector(".ap-manual-input").focus();
      });
      panel.querySelector(".ap-manual-ok").addEventListener("click", function (e) {
        e.stopPropagation();
        var v = panel.querySelector(".ap-manual-input").value.trim();
        if (!v) return;
        // Don't force .exe onto paths, protocols, .lnk, or shell: URIs
        if (
          !/\.exe$/i.test(v) &&
          !/\.lnk$/i.test(v) &&
          !/^[a-z][a-z0-9+\-.]*:/i.test(v) &&
          !/^shell:/i.test(v) &&
          v.indexOf("\\") < 0 &&
          v.indexOf("/") < 0 &&
          v.indexOf(" ") < 0
        ) {
          v += ".exe";
        }
        pick(v);
      });

      var browseBtn = panel.querySelector(".ap-browse");
      if (browseBtn) {
        browseBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          function applyPath(path) {
            if (path) pick(String(path));
          }
          if (typeof onBrowse === "function") {
            Promise.resolve(onBrowse()).then(applyPath).catch(function () {});
            return;
          }
          var a = window.pywebview && window.pywebview.api;
          if (a && typeof a.browse_for_app === "function") {
            Promise.resolve(a.browse_for_app()).then(applyPath).catch(function () {});
          }
        });
      }

      // Stop clicks inside panel from counting as outside
      panel.addEventListener("click", function (e) { e.stopPropagation(); });
      panel.addEventListener("mousedown", function (e) { e.stopPropagation(); });

      boundScrollClose = function (e) {
        // Ignore scrolls inside the portal list (keyboard nav / overflow)
        if (e && e.type === "scroll" && panel && e.target && panel.contains(e.target)) return;
        closeAppPicker();
      };
      window.addEventListener("scroll", boundScrollClose, true);
      window.addEventListener("resize", boundScrollClose);
    }

    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      open(compact ? (root.closest(".bcard") || btn) : btn);
    });

    root.appendChild(btn);
    root.open = open;
    root.getTrigger = function () { return btn; };
    // Panel is portaled to body on open — not a child of root
    return root;
  }

  document.addEventListener("click", function (e) {
    if (!openPanel) return;
    if (openPanel.contains(e.target)) return;
    if (openTrigger && openTrigger.contains(e.target)) return;
    if (openRoot && openRoot.contains(e.target)) return;
    closeAppPicker();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openPanel) {
      e.preventDefault();
      closeAppPicker();
    }
  });

  global.PyMixerAppPicker = {
    create: createAppPicker,
    close: closeAppPicker,
    displayName: displayName,
    _positionPanel: positionPanel, // test/debug
  };
})(window);
