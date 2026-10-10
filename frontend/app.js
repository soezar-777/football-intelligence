/* FOOTBALL INTELLIGENCE dashboard — vanilla JS, no external libraries. */
(function () {
  "use strict";

  var state = {
    lang: localStorage.getItem("fi_lang") || "my",
    tab: "predictions",
    t: {},
    predictions: null,
    verification: null,
    performance: null,
  };

  var DATA_PATHS = {
    predictions: ["data/predictions.json", "../data/samples/predictions.json"],
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

  /* ------------------------------------------------- predictions tab */
  function renderPredictions(el) {
    var t = state.t, d = state.predictions;
    if (!d || !d.predictions || !d.predictions.length) {
      el.innerHTML = '<div class="empty">' + esc(t.no_data) + "</div>";
      return;
    }
    var html = '<div class="meta-line">' + esc(t.updated) + ": " +
      fmtKickoff(d.generated_at) + " · " + d.count + " ⚽</div>";
    d.predictions.forEach(function (p) {
      var m = p.markets || {}, ou = m.ou || {}, btts = m.btts || {};
      var picks = p.picks || {};
      html += '<div class="card">';
      html += '<div class="card-head"><span class="comp">' + esc(p.competition) +
        '</span><span class="kickoff">' + fmtKickoff(p.kickoff) + "</span></div>";
      html += '<div class="teams">' + esc(p.home_team.name) + " vs " +
        esc(p.away_team.name) + "</div>";
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
    });
    el.innerHTML = html;
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

    d.matches.slice().reverse().forEach(function (g) {
      html += '<div class="card">';
      html += '<div class="card-head"><span class="comp">' + esc(g.competition) +
        '</span><span class="actual-score">' + esc(g.actual) + "</span></div>";
      html += '<div class="teams">' + esc(g.home_team) + " vs " + esc(g.away_team) + "</div>";
      html += '<div class="chips">';
      Object.keys(g.grades || {}).forEach(function (mk) {
        var gr = g.grades[mk];
        html += '<span class="chip">' + esc(mk) + " " + esc(gr.pick || "–") +
          " " + gradeIcon(gr) + "</span>";
      });
      html += "</div></div>";
    });
    el.innerHTML = html;
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
      loadJSON(DATA_PATHS.predictions),
      loadJSON(DATA_PATHS.verification),
      loadJSON(DATA_PATHS.performance),
    ]);
  }).then(function (arr) {
    state.predictions = arr[0];
    state.verification = arr[1];
    state.performance = arr[2];
    render();
  });
})();
