/* FOOTBALL INTELLIGENCE dashboard — vanilla JS, no external libraries. */
(function () {
  "use strict";

  var state = {
    lang: localStorage.getItem("fi_lang") || "my",
    tab: "predictions",
    t: {},
    predictions: null,
    search: "",
    vsearch: "",
    teamsMy: null,
    verification: null,
    performance: null,
    drillLeague: null,
  };

  /* Predictions are published per competition (predictions_<CODE>.json) so each
     file stays small; the loader below merges them into one list. */
  var COMPETITIONS = ["PL", "BL1", "SA", "PD", "FL1", "DED", "PPL", "CL", "ELC", "BSA", "BL2", "SDV", "ALV"];

  /* League names for search (code + English + Burmese) */
  var COMPETITION_NAMES = {
    "PL":  { en: "Premier League",       my: "ပရီးမီးယားလိဂ်" },
    "BL1": { en: "Bundesliga",           my: "ဘွန်ဒက်စ်လီဂါ" },
    "SA":  { en: "Serie A",              my: "စီးရီးအေ" },
    "PD":  { en: "La Liga",              my: "လာလီဂါ" },
    "FL1": { en: "Ligue 1",              my: "လီဂူး ၁" },
    "DED": { en: "Eredivisie",           my: "အီရီဒီဗီစီ" },
    "PPL": { en: "Primeira Liga",        my: "ပရိုင်းမီရာလိဂ်" },
    "CL":  { en: "Champions League",     my: "ချန်ပီယံလိဂ်" },
    "ELC": { en: "Championship",         my: "ချန်ပီယံရှစ်" },
    "BSA": { en: "Brasileirao Serie A",  my: "ဘရာဇီးလ်စီးရီးအေ" },
    "BL2": { en: "2. Bundesliga",        my: "ဘွန်ဒက်စ်လီဂါ ၂" },
    "SDV": { en: "Segunda Division",     my: "စီကွန်ဒါ" },
    "ALV": { en: "Allsvenskan",          my: "ဆွီဒင်လိဂ်" }
  };

  var DATA_PATHS = {
    predictionFiles: COMPETITIONS.map(function (c) { return "data/predictions_" + c + ".json"; }),
    predictionsSample: ["../data/samples/predictions.json"],
    verification: ["data/verification.json", "../data/samples/verification.json"],
    performance: ["data/performance.json", "../data/samples/performance.json"],
  };

  function $(id) { return document.getElementById(id); }

  function loadJSON(paths) {
    var chain = Promise.resolve(null);
    paths.forEach(function (p) {
      chain = chain.then(function (found) {
        if (found) return found;
        return fetch(p, { cache: "no-store" }).then(function (r) {
          return r.ok ? r.json() : null;
        }).catch(function () { return null; });
      });
    });
    return chain;
  }

  function loadPredictions() {
    return Promise.all(DATA_PATHS.predictionFiles.map(function (p) {
      return fetch(p, { cache: "no-store" }).then(function (r) {
        return r.ok ? r.json() : null;
      }).catch(function () { return null; });
    })).then(function (parts) {
      var merged = [], generated = null, version = null;
      parts.forEach(function (part) {
        if (part && part.predictions && part.predictions.length) {
          merged = merged.concat(part.predictions);
          if (!generated || (part.generated_at && part.generated_at > generated)) {
            generated = part.generated_at;
          }
          version = version || part.model_version;
        }
      });
      if (!merged.length) return loadJSON(DATA_PATHS.predictionsSample);
      merged.sort(function (a, b) {
        var ka = a.kickoff || "", kb = b.kickoff || "";
        return ka < kb ? -1 : (ka > kb ? 1 : 0);
      });
      return {
        model_version: version,
        generated_at: generated,
        count: merged.length,
        predictions: merged,
      };
    });
  }

  function pct(p) {
    if (p === null || p === undefined || isNaN(p)) return "–";
    return (p * 100).toFixed(1) + "%";
  }

  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
      });
  }

  function fmtKickoff(iso) {
    if (!iso) return "–";
    try {
      return new Date(iso).toLocaleString(state.lang === "my" ? "my-MM" : "en-GB", {
        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
    } catch (e) { return iso; }
  }

  function probRow(label, p, hot) {
    return '<div class="prob-row"><span class="prob-label">' + esc(label) + '</span>' +
      '<span class="prob-bar"><span class="prob-fill' + (hot ? " hot" : "") +
      '" style="width:' + Math.max(0, Math.min(100, p * 100)) + '%"></span></span>' +
      '<span class="prob-val">' + pct(p) + "</span></div>";
  }

  function sectionTitle(text) {
    return '<div class="market"><div class="market-title">' + esc(text) + "</div>";
  }

  /* team name in current language: Burmese transliteration when UI is
     Burmese and a mapping exists, otherwise the English name */
  function teamName(name) {
    if (state.lang === "my" && state.teamsMy && state.teamsMy[name]) {
      return state.teamsMy[name];
    }
    return name;
  }

  /* Accent-insensitive matching so "almeria" finds "Almería" etc. */
  function normStr(s) {
    return (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }

  function leagueDisplayName(code) {
    var cn = COMPETITION_NAMES[code];
    if (!cn) return code;
    return state.lang === "my" ? cn.my : cn.en;
  }

  /* "Today" follows the digest convention: UTC calendar date of kickoff.
     (Evening matches in Myanmar are still grouped under the same UTC day,
     e.g. 01:30 MMT Oct 13 counts as Oct 12's matches.) */
  function todayKeyUTC() {
    return new Date().toISOString().slice(0, 10);
  }
  function kickoffDayUTC(iso) {
    return (iso || "").slice(0, 10);
  }

  /* Tap a team name -> filter the list to that team */
  function filterByTeam(name) {
    state.search = name;
    var input = $("team-search");
    if (input) {
      input.value = name;
      if (!$("search-clear")) {
        var b = document.createElement("button");
        b.id = "search-clear";
        b.setAttribute("aria-label", "clear");
        b.textContent = "✕";
        b.addEventListener("click", clearSearch);
        input.parentNode.appendChild(b);
      }
    }
    renderPredictionList();
    var list = $("pred-list");
    if (list && list.scrollIntoView) list.scrollIntoView();
  }

  function teamMatch(p, q) {
    q = normStr(q);
    var names = [
      ((p.home_team && p.home_team.name) || ""),
      ((p.away_team && p.away_team.name) || "")
    ];
    // also match Burmese names so search works in both scripts
    if (state.teamsMy) {
      names.push(state.teamsMy[names[0]] || "", state.teamsMy[names[1]] || "");
    }
    // also match league: code, English name, Burmese name
    var cn = COMPETITION_NAMES[p.competition];
    if (cn) names.push(p.competition, cn.en, cn.my);
    else if (p.competition) names.push(p.competition);
    for (var i = 0; i < names.length; i++) {
      if (names[i] && normStr(names[i]).indexOf(q) !== -1) return true;
    }
    return false;
  }

  /* ------------------------------------------------- predictions tab */
  function filteredPredictions() {
    var d = state.predictions;
    var list = (d && d.predictions) || [];
    var q = (state.search || "").trim().toLowerCase();
    if (!q) return list;
    return list.filter(function (p) { return teamMatch(p, q); });
  }

  function predictionCardHTML(p) {
    var t = state.t;
    var html = "";
    // "probably playing now" badge: free API has no real-time live feed,
    // so estimate from kickoff time (0-105 min ago, still marked TIMED)
    var liveBadge = "";
    try {
      var minsAgo = (Date.now() - new Date(p.kickoff).getTime()) / 60000;
      if ((p.status === "TIMED" || p.status === "SCHEDULED") &&
          minsAgo >= 0 && minsAgo <= 105) {
        liveBadge = ' <span class="live-badge">\uD83D\uDD34 ' +
          esc(t.likely_live || "") + "</span>";
      }
    } catch (e) { /* ignore bad dates */ }
    var m = p.markets || {}, ou = m.ou || {}, btts = m.btts || {};
    var picks = p.picks || {};
    html += '<div class="card">';
    html += '<div class="card-head"><span class="comp">' + esc(p.competition) +
      '</span><span class="kickoff">' + fmtKickoff(p.kickoff) + "</span></div>";
    html += '<div class="teams"><span class="team-link" data-team="' +
      esc(p.home_team.name) + '">' + esc(teamName(p.home_team.name)) + "</span> vs " +
      '<span class="team-link" data-team="' + esc(p.away_team.name) + '">' +
      esc(teamName(p.away_team.name)) + "</span>" + liveBadge + "</div>";
    html += '<div class="xg-line">' + esc(t.xg) + ": " + p.xg.home + " – " +
      p.xg.away + "</div>";

    var x12 = m["1x2"] || {};
    html += sectionTitle(t.market_1x2);
    html += probRow(t.home, x12.home, picks["1x2"] && picks["1x2"].selection === "home");
    html += probRow(t.draw, x12.draw, picks["1x2"] && picks["1x2"].selection === "draw");
    html += probRow(t.away, x12.away, picks["1x2"] && picks["1x2"].selection === "away");
    html += "</div>";

    if (ou["2.5"]) {
      html += sectionTitle(t.market_ou25);
      html += probRow(t.over + " 2.5", ou["2.5"].over,
        picks.ou25 && picks.ou25.selection === "over");
      html += probRow(t.under + " 2.5", ou["2.5"].under,
        picks.ou25 && picks.ou25.selection === "under");
      html += "</div>";
    }
    html += sectionTitle(t.market_btts);
    html += probRow(t.yes, btts.yes, picks.btts && picks.btts.selection === "yes");
    html += probRow(t.no, btts.no, picks.btts && picks.btts.selection === "no");
    html += "</div>";

    if (m.correct_scores && m.correct_scores.length) {
      html += sectionTitle(t.market_cs) + '<div class="chips">';
      m.correct_scores.forEach(function (s) {
        html += '<span class="chip">' + esc(s.score) + " · " + pct(s.prob) + "</span>";
      });
      html += "</div></div>";
    }

    if (m.ah) {
      html += sectionTitle(t.market_ah);
      Object.keys(m.ah).forEach(function (line) {
        var a = m.ah[line];
        html += probRow(line + " " + t.cover, a.cover, false);
      });
      html += "</div>";
    }

    html += '<div class="market"><div class="market-title">' + esc(t.picks_title) + "</div>";
    html += '<div class="picks">';
    var anyPick = false;
    [["1x2", t.market_1x2], ["ou25", t.market_ou25], ["btts", t.market_btts],
     ["ah", t.market_ah], ["correct_score", t.market_cs]].forEach(function (pair) {
      var pk = picks[pair[0]];
      if (pk) {
        anyPick = true;
        var label = pk.selection || (pk.line + " " + pk.side);
        html += '<span class="pick-badge">✓ ' + esc(label) + " " + pct(pk.prob) + "</span>";
      }
    });
    if (!anyPick) html += '<span class="pick-none">' + esc(t.no_pick) + "</span>";
    html += "</div></div>";

    html += "</div>";
    return html;
  }

  function renderPredictionList() {
    var t = state.t, d = state.predictions;
    var holder = $("pred-list");
    if (!holder || !d) return;
    var html = "";
    if (state.search) {
      // search mode: flat list across all predictions
      var list = filteredPredictions();
      html += '<div class="meta-line">' + esc(t.updated) + ": " +
        fmtKickoff(d.generated_at) + " \u00b7 " + list.length + " / " + d.count + " \u26bd</div>";
      if (!list.length) {
        html += '<div class="empty">' + esc(t.no_result || t.no_data) + "</div>";
      }
      list.forEach(function (p) { html += predictionCardHTML(p); });
    } else if (state.drillLeague) {
      // drill-down: this league's matches today, with back button
      var tk = todayKeyUTC();
      var dlist = d.predictions.filter(function (p) {
        return p.competition === state.drillLeague && kickoffDayUTC(p.kickoff) === tk;
      });
      html += '<div class="drill-head"><span class="back-btn" data-back="1">\u2190 ' +
        esc(t.back || "Back") + '</span><span class="drill-title">' +
        esc(leagueDisplayName(state.drillLeague)) + " \u00b7 " + dlist.length +
        " " + esc(t.matches || "") + "</span></div>";
      if (!dlist.length) {
        html += '<div class="empty">' + esc(t.no_result || t.no_data) + "</div>";
      }
      dlist.forEach(function (p) { html += predictionCardHTML(p); });
    } else {
      // home: only leagues playing today, grouped with headers
      var tk2 = todayKeyUTC();
      var today = d.predictions.filter(function (p) {
        return kickoffDayUTC(p.kickoff) === tk2;
      });
      html += '<div class="meta-line">' + esc(t.today || "Today") + ": " +
        today.length + " " + esc(t.matches || "") + " \u26bd</div>";
      if (!today.length) {
        html += '<div class="empty">' + esc(t.no_result || t.no_data) + "</div>";
      }
      var groups = {}, order = [];
      today.forEach(function (p) {
        var c = p.competition || "?";
        if (!groups[c]) { groups[c] = []; order.push(c); }
        groups[c].push(p);
      });
      order.forEach(function (c) {
        html += '<div class="league-header" data-league="' + esc(c) + '">' +
          '<span class="league-name">' + esc(leagueDisplayName(c)) + "</span>" +
          '<span class="league-count">' + groups[c].length + "</span>" +
          '<span class="league-arrow">\u203a</span></div>';
      });
    }
    holder.innerHTML = html;
  }

  function clearSearch() {
    state.search = "";
    var input = $("team-search");
    if (input) { input.value = ""; input.focus(); }
    var btn = $("search-clear");
    if (btn) btn.remove();
    renderPredictionList();
  }

  function renderPredictions(el) {
    var t = state.t, d = state.predictions;
    if (!d || !d.predictions || !d.predictions.length) {
      el.innerHTML = '<div class="empty">' + esc(t.no_data) + "</div>";
      return;
    }
    el.innerHTML =
      '<div class="search-wrap">' +
        '<input id="team-search" type="search" autocomplete="off" placeholder="' +
          esc(t.search_placeholder || "") + '" value="' + esc(state.search || "") + '">' +
        (state.search ? '<button id="search-clear" aria-label="clear">\u2715</button>' : "") +
      "</div>" +
      '<div id="pred-list"></div>';
    var input = $("team-search");
    var searchTimer = null;
    var syncClearBtn = function () {
      var btn = $("search-clear");
      if (input.value && !btn) {
        var b = document.createElement("button");
        b.id = "search-clear";
        b.setAttribute("aria-label", "clear");
        b.textContent = "\u2715";
        b.addEventListener("click", clearSearch);
        input.parentNode.appendChild(b);
      } else if (!input.value && btn) {
        btn.remove();
      }
    };
    input.addEventListener("input", function () {
      state.search = input.value;
      syncClearBtn();
      // debounce: re-render only after the user pauses typing (220ms),
      // so fast typing doesn't rebuild all cards on every keystroke
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        searchTimer = null;
        // skip if the query changed again while waiting
        if (state.search === input.value) renderPredictionList();
      }, 220);
    });
    var cb = $("search-clear");
    if (cb) cb.addEventListener("click", clearSearch);
    // delegated taps: league headers drill in, back button goes home,
    // team names filter
    // (bound once per container to avoid stacking on re-render)
    if (!el.dataset.bound) {
      el.dataset.bound = "1";
      el.addEventListener("click", function (ev) {
        var t = ev.target;
        while (t && t !== el) {
          if (t.classList && t.classList.contains("team-link") && t.dataset.team) {
            filterByTeam(t.dataset.team);
            return;
          }
          if (t.classList && t.classList.contains("back-btn")) {
            state.drillLeague = null;
            renderPredictionList();
            return;
          }
          if (t.classList && t.classList.contains("league-header") && t.dataset.league) {
            state.drillLeague = t.dataset.league;
            renderPredictionList();
            if (el.scrollIntoView) el.scrollIntoView();
            return;
          }
          t = t.parentNode;
        }
      });
    }
    renderPredictionList();
  }


  /* ------------------------------------------------ verification tab */
  function gradeIcon(g) {
    if (g.hit === true) return '<span class="grade hit">✓</span>';
    if (g.hit === false) return '<span class="grade miss">✗</span>';
    return '<span class="grade void">–</span>';
  }

  function renderVerification(el) {
    var t = state.t, d = state.verification;
    if (!d || !d.matches || !d.matches.length) {
      el.innerHTML = '<div class="empty">' + esc(t.no_data) + "</div>";
      return;
    }
    var html = '<div class="meta-line">' + esc(t.updated) + ": " +
      fmtKickoff(d.generated_at) + " · " + esc(t.graded) + ": " + d.graded_count + "</div>";

    html += '<div class="card">' + sectionTitle(t.overall);
    Object.keys(d.summary || {}).forEach(function (mk) {
      var s = d.summary[mk];
      if (s.hit_rate !== null && s.hit_rate !== undefined) {
        html += probRow(mk.toUpperCase(), s.hit_rate, false) ;
      }
    });
    html += "</div></div>";

    html += '<div class="search-wrap">' +
      '<input id="verif-search" type="search" autocomplete="off" placeholder="' +
        esc(t.search_placeholder || "") + '" value="' + esc(state.vsearch || "") + '">' +
      (state.vsearch ? '<button id="vsearch-clear" aria-label="clear">\u2715</button>' : "") +
      "</div>" +
      '<div id="verif-list"></div>';
    el.innerHTML = html;

    var input = $("verif-search");
    var vTimer = null;
    var syncClearBtn = function () {
      var btn = $("vsearch-clear");
      if (input.value && !btn) {
        var b = document.createElement("button");
        b.id = "vsearch-clear";
        b.setAttribute("aria-label", "clear");
        b.textContent = "\u2715";
        b.addEventListener("click", clearVSearch);
        input.parentNode.appendChild(b);
      } else if (!input.value && btn) {
        btn.remove();
      }
    };
    input.addEventListener("input", function () {
      state.vsearch = input.value;
      syncClearBtn();
      if (vTimer) clearTimeout(vTimer);
      vTimer = setTimeout(function () {
        vTimer = null;
        if (state.vsearch === input.value) renderVerificationList();
      }, 220);
    });
    var cb = $("vsearch-clear");
    if (cb) cb.addEventListener("click", clearVSearch);
    renderVerificationList();
  }

  function clearVSearch() {
    state.vsearch = "";
    var input = $("verif-search");
    if (input) { input.value = ""; input.focus(); }
    var btn = $("vsearch-clear");
    if (btn) btn.remove();
    renderVerificationList();
  }

  function verifMatch(g, q) {
    q = normStr(q);
    var names = [(g.home_team || ""), (g.away_team || "")];
    if (state.teamsMy) {
      names.push(state.teamsMy[names[0]] || "", state.teamsMy[names[1]] || "");
    }
    var cn = COMPETITION_NAMES[g.competition];
    if (cn) names.push(g.competition, cn.en, cn.my);
    else if (g.competition) names.push(g.competition);
    for (var i = 0; i < names.length; i++) {
      if (names[i] && normStr(names[i]).indexOf(q) !== -1) return true;
    }
    return false;
  }

  function renderVerificationList() {
    var t = state.t, d = state.verification;
    var holder = $("verif-list");
    if (!holder || !d) return;
    var q = (state.vsearch || "").trim().toLowerCase();
    var list = d.matches.slice().reverse();
    if (q) {
      list = list.filter(function (g) { return verifMatch(g, q); });
    }
    var html = "";
    if (!list.length) {
      html += '<div class="empty">' + esc(t.no_result || t.no_data) + "</div>";
    }
    list.forEach(function (g) {
      html += '<div class="card">';
      html += '<div class="card-head"><span class="comp">' + esc(g.competition) +
        '</span><span class="actual-score">' + esc(g.actual) + "</span></div>";
      html += '<div class="teams">' + esc(teamName(g.home_team)) + " vs " + esc(teamName(g.away_team)) + "</div>";
      html += '<div class="chips">';
      Object.keys(g.grades || {}).forEach(function (mk) {
        var gr = g.grades[mk];
        html += '<span class="chip">' + esc(mk) + " " + esc(gr.pick || "–") +
          " " + gradeIcon(gr) + "</span>";
      });
      html += "</div></div>";
    });
    holder.innerHTML = html;
  }

  /* ------------------------------------------------ performance tab */
  function renderPerformance(el) {
    var t = state.t, d = state.performance;
    if (!d || !d.graded_total) {
      el.innerHTML = '<div class="empty">' + esc(t.no_data) + "</div>";
      return;
    }
    var html = '<div class="meta-line">' + esc(t.updated) + ": " +
      fmtKickoff(d.generated_at) + " · " + esc(t.model) + ": " +
      esc(d.model_version || "–") + "</div>";

    html += '<div class="card">' + sectionTitle(t.overall);
    Object.keys(d.overall || {}).forEach(function (mk) {
      var s = d.overall[mk];
      if (s.hit_rate !== null && s.hit_rate !== undefined) {
        html += probRow(mk.toUpperCase() + " (" + s.hit + "/" + s.graded + ")",
          s.hit_rate, s.hit_rate >= 0.5);
      }
    });
    if (d.brier_1x2 !== null && d.brier_1x2 !== undefined) {
      html += '<div class="meta-line">' + esc(t.brier) + ": " + d.brier_1x2 + "</div>";
    }
    html += "</div></div>";

    html += '<div class="card">' + sectionTitle(t.rolling30);
    Object.keys(d.rolling_last_30 || {}).forEach(function (mk) {
      var s = d.rolling_last_30[mk];
      if (s.hit_rate !== null && s.hit_rate !== undefined) {
        html += probRow(mk.toUpperCase(), s.hit_rate, s.hit_rate >= 0.5);
      }
    });
    html += "</div></div>";

    var comps = d.by_competition || {};
    if (Object.keys(comps).length) {
      html += '<div class="card">' + sectionTitle(t.by_competition);
      html += '<table class="perf"><tr><th></th><th class="num">1X2</th>' +
        '<th class="num">O/U</th><th class="num">BTTS</th></tr>';
      Object.keys(comps).forEach(function (code) {
        var c = comps[code];
        html += "<tr><td><b>" + esc(code) + "</b></td><td class='num'>" +
          pct(c["1x2"].hit_rate) + "</td><td class='num'>" + pct(c.ou25.hit_rate) +
          "</td><td class='num'>" + pct(c.btts.hit_rate) + "</td></tr>";
      });
      html += "</table></div></div>";
    }
    el.innerHTML = html;
  }

  /* ------------------------------------------------------------- i18n */
  function applyI18n() {
    var t = state.t;
    document.documentElement.lang = state.lang;
    $("app-subtitle").textContent = t.app_subtitle || "";
    $("tabbtn-predictions").textContent = t.tab_predictions || "";
    $("tabbtn-verification").textContent = t.tab_verification || "";
    $("tabbtn-performance").textContent = t.tab_performance || "";
    $("lang-my").classList.toggle("active", state.lang === "my");
    $("lang-en").classList.toggle("active", state.lang === "en");
  }

  function render() {
    applyI18n();
    renderPredictions($("tab-predictions"));
    renderVerification($("tab-verification"));
    renderPerformance($("tab-performance"));
    var p = state.predictions;
    $("footer-meta").textContent =
      (state.t.model || "") + ": " + (p && p.model_version ? p.model_version : "–");
  }

  function setTab(name) {
    state.tab = name;
    document.querySelectorAll(".tabs button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.tab === name);
    });
    document.querySelectorAll(".tab-panel").forEach(function (s) {
      s.classList.toggle("active", s.id === "tab-" + name);
    });
  }

  function setLang(lang) {
    state.lang = lang;
    localStorage.setItem("fi_lang", lang);
    loadJSON(["i18n/" + lang + ".json"]).then(function (t) {
      state.t = t || {};
      render();
    });
  }

  /* -------------------------------------------------------------- init */
  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () { setTab(b.dataset.tab); });
  });
  $("lang-my").addEventListener("click", function () { setLang("my"); });
  $("lang-en").addEventListener("click", function () { setLang("en"); });

  loadJSON(["i18n/" + state.lang + ".json"]).then(function (t) {
    state.t = t || {};
    return Promise.all([
      loadPredictions(),
      loadJSON(DATA_PATHS.verification),
      loadJSON(DATA_PATHS.performance),
      loadJSON(["i18n/teams_my.json"]),
    ]);
  }).then(function (arr) {
    state.predictions = arr[0];
    state.verification = arr[1];
    state.performance = arr[2];
    state.teamsMy = arr[3] || {};
    render();
  });
})();
