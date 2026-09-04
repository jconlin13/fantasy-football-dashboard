/* All-Time Analysis. Reads site/data/analysis.json and renders it as tabs.
 *
 * Every section leads with a one-sentence definition of what it is showing.
 * That is not decoration: the whole point of this site is settling arguments,
 * and a number nobody can explain just starts a new argument about the number.
 */

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var panel = $("panel");
  var data = null;

  /* ---------- small builders ---------- */

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function explain(text) {
    return el("p", "explain", text);
  }

  function signed(value, digits) {
    var n = Number(value);
    var span = el("span", n > 0 ? "pos" : (n < 0 ? "neg" : null));
    span.textContent = (n > 0 ? "+" : "") + n.toFixed(digits === undefined ? 2 : digits);
    return span;
  }

  /* Tables scroll inside their own container so a wide row never makes the
     whole page scroll sideways on a phone. */
  function table(headers, rows) {
    var scroller = el("div", "scroller");
    var t = el("table");

    var thead = el("thead");
    var hr = el("tr");
    headers.forEach(function (h) { hr.appendChild(el("th", null, h)); });
    thead.appendChild(hr);
    t.appendChild(thead);

    var tbody = el("tbody");
    rows.forEach(function (cells) {
      var tr = el("tr");
      cells.forEach(function (cell) {
        var td = el("td");
        if (cell instanceof Node) { td.appendChild(cell); }
        else { td.textContent = cell === null || cell === undefined ? "—" : String(cell); }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    t.appendChild(tbody);

    scroller.appendChild(t);
    return scroller;
  }

  function statRow(label, value, who) {
    var row = el("div", "stat");
    row.appendChild(el("div", "label", label));
    var right = el("div");
    right.appendChild(el("div", "value", value));
    if (who) { right.appendChild(el("span", "who", who)); }
    row.appendChild(right);
    return row;
  }

  /* ---------- sections ---------- */

  function champions() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "Every season since " + data.firstSeason + ", with the manager who won it. " +
      "Champions are derived from the playoff bracket, not from a label — ESPN " +
      "does not record one."
    ));

    // Which title this was for that manager -- "3rd" beside 2023 reads as a
    // running tally. Repeating the career total on every row would read as
    // though they won three that year.
    var sofar = {};
    var nth = {};
    data.seasons.forEach(function (season) {
      if (!season.champion) { return; }
      sofar[season.champion] = (sofar[season.champion] || 0) + 1;
      nth[season.year] = sofar[season.champion];
    });

    data.seasons.slice().reverse().forEach(function (season) {
      var row = el("div", "champ");
      row.appendChild(el("div", "year", season.year));
      row.appendChild(el("div", "name", season.champion || "—"));
      var count = nth[season.year];
      var mark = el("div", "rings", "🏆");
      if (count > 1) {
        mark.appendChild(el("span", "badge", count + (count === 2 ? "nd" : "rd")));
      }
      row.appendChild(mark);
      frag.appendChild(row);
    });
    return frag;
  }

  function managers() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "Career totals across every season a manager has played. Managers who have " +
      "left the league stay on this list — everyone else's record against them is " +
      "real and keeps counting."
    ));
    frag.appendChild(table(
      ["Manager", "Seasons", "Titles", "W", "L", "Win %", "Points"],
      data.managers.map(function (m) {
        return [
          m.manager, m.seasons, m.championships || "—", m.wins, m.losses,
          (m.winPct * 100).toFixed(1) + "%", Math.round(m.pointsFor).toLocaleString()
        ];
      })
    ));
    return frag;
  }

  function records() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "The extremes, regular season and playoffs kept separate. Consolation games " +
      "are excluded; the third-place game counts."
    ));

    [["regular", "Regular Season"], ["playoff", "Playoffs"]].forEach(function (pair) {
      var book = data.records[pair[0]];
      if (!book) { return; }
      frag.appendChild(el("h3", null, pair[1]));

      var labels = {
        highestWeek: "Highest Week",
        lowestWeek: "Lowest Week",
        biggestBlowout: "Biggest Blowout",
        narrowestWin: "Narrowest Win",
        mostPointsInALoss: "Most Points in a Loss"
      };
      Object.keys(labels).forEach(function (key) {
        var rec = book[key];
        if (!rec) { return; }
        frag.appendChild(statRow(
          labels[key],
          rec.value.toFixed(1),
          rec.manager + " | " + rec.year + " wk" + rec.week +
            (rec.opponent ? " vs " + rec.opponent : "")
        ));
      });
    });

    var best = data.records.bestSeason;
    var worst = data.records.worstSeason;
    var streaks = data.records.streaks || {};
    frag.appendChild(el("h3", null, "Seasons and Streaks"));
    if (best) {
      frag.appendChild(statRow("Best Season", best.wins + "-" + (best.games - best.wins),
        best.manager + " | " + best.year));
    }
    if (worst) {
      frag.appendChild(statRow("Worst Season", worst.wins + "-" + (worst.games - worst.wins),
        worst.manager + " | " + worst.year));
    }
    if (streaks.longestWinStreak) {
      frag.appendChild(statRow("Longest Win Streak", streaks.longestWinStreak.length,
        streaks.longestWinStreak.manager + " | through " + streaks.longestWinStreak.through));
    }
    if (streaks.longestLoseStreak) {
      frag.appendChild(statRow("Longest Losing Streak", streaks.longestLoseStreak.length,
        streaks.longestLoseStreak.manager + " | through " + streaks.longestLoseStreak.through));
    }
    return frag;
  }

  function headToHead() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "Career record against every other manager. A full grid is unreadable on a " +
      "phone, so pick a manager and see their whole rivalry list."
    ));

    var names = data.managers.map(function (m) { return m.manager; }).sort();
    var picker = el("select");
    names.forEach(function (name) {
      var option = el("option", null, name);
      option.value = name;
      picker.appendChild(option);
    });
    frag.appendChild(picker);

    var host = el("div");
    frag.appendChild(host);

    function draw(name) {
      host.textContent = "";
      var rows = data.headToHead.filter(function (r) { return r.manager === name; });
      rows.sort(function (a, b) { return (b.wins - b.losses) - (a.wins - a.losses); });
      host.appendChild(table(
        ["Opponent", "Record", "Avg Margin", "Playoffs"],
        rows.map(function (r) {
          var playoffs = (r.playoffWins || r.playoffLosses)
            ? r.playoffWins + "-" + r.playoffLosses : "—";
          return [r.opponent, r.wins + "-" + r.losses, signed(r.avgMargin, 1), playoffs];
        })
      ));
    }

    picker.addEventListener("change", function () { draw(picker.value); });
    draw(names[0]);
    return frag;
  }

  function luck() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "Each week, your score is compared with every other team that played: beat " +
      "7 of 9 and you earned 0.78 of a win. Add those up and you get expected " +
      "wins. Luck is what you actually won minus that — you would have won this " +
      "many games against an average schedule, and you actually won that many. " +
      "Regular season only, because playoff matchups come from seeding."
    ));
    frag.appendChild(table(
      ["Manager", "Actual", "Expected", "Luck"],
      data.luck.career.map(function (r) {
        return [r.manager, r.actualWins, r.expectedWins.toFixed(1), signed(r.luck, 1)];
      })
    ));
    return frag;
  }

  function lineups() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "What you started, over the best legal lineup that roster could have " +
      "produced. 100% means you could not have done better with hindsight. Slot " +
      "rules are read from each season, which matters — this league went from " +
      "nine starters and one quarterback to eleven with two."
    ));
    frag.appendChild(table(
      ["Manager", "Efficiency", "Points Benched", "Weeks"],
      data.lineups.career.map(function (r) {
        return [r.manager, (r.efficiency * 100).toFixed(1) + "%",
                Math.round(r.leftOnBench).toLocaleString(), r.weeks];
      })
    ));

    frag.appendChild(el("h3", null, "Worst Weeks Ever"));
    frag.appendChild(table(
      ["Manager", "Season", "Started", "Could Have", "Left"],
      data.lineups.worstWeeks.map(function (r) {
        return [r.manager, r.year + " wk" + r.week, r.actual.toFixed(1),
                r.optimal.toFixed(1), r.leftOnBench.toFixed(1)];
      })
    ));
    return frag;
  }

  function draft() {
    var frag = document.createDocumentFragment();
    frag.appendChild(explain(
      "Points your own draft picks scored for you, for as long as you kept them, " +
      "against what that draft slot usually returns. This is NOT a measure of who " +
      "drafts well: it tracks how long you hold picks almost as closely as it " +
      "tracks pick quality, so the weeks-held column sits right next to it."
    ));
    frag.appendChild(table(
      ["Manager", "Vs Slot", "Weeks Held", "Picks"],
      data.draft.byManager.map(function (r) {
        return [r.manager, signed(r.avgVsSlot, 1), r.avgWeeksHeld.toFixed(1), r.picks];
      })
    ));

    frag.appendChild(el("h3", null, "Best Picks Ever"));
    frag.appendChild(table(
      ["Manager", "Season", "Pick", "Returned", "Vs Slot"],
      data.draft.bestPicks.map(function (r) {
        return [r.manager, r.year, "#" + r.overall, r.returned.toFixed(1),
                signed(r.vsSlot, 1)];
      })
    ));

    var totals = data.trades.totals || {};
    frag.appendChild(el("h3", null, "The Trade Market"));
    frag.appendChild(explain(
      "There are no trade retrospectives here because there are barely any trades. " +
      "ESPN keeps the players involved for only two of them across eight seasons — " +
      "but the counts tell the story anyway."
    ));
    frag.appendChild(table(
      ["", "Count"],
      [
        ["Proposed", totals.TRADE_PROPOSAL || 0],
        ["Declined", totals.TRADE_DECLINE || 0],
        ["Accepted", totals.TRADE_ACCEPT || 0],
        ["Vetoed", totals.TRADE_VETO || 0]
      ]
    ));
    return frag;
  }

  /* ---------- tabs ---------- */

  var SECTIONS = [
    ["Champions", champions],
    ["Managers", managers],
    ["Records", records],
    ["Head-to-Head", headToHead],
    ["Luck", luck],
    ["Lineups", lineups],
    ["Draft", draft]
  ];

  function show(index) {
    var buttons = $("tabs").querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-selected", i === index ? "true" : "false");
    }
    panel.textContent = "";
    panel.appendChild(SECTIONS[index][1]());
    try {
      location.hash = SECTIONS[index][0].toLowerCase().replace(/[^a-z]/g, "");
    } catch (error) { /* hash is a nicety, not a requirement */ }
  }

  function render() {
    var leagueName = data.leagueName || "Fantasy League";
    $("span-years").textContent =
      leagueName + " · " + data.firstSeason + "–" + data.lastSeason;
    document.title = "All-Time Analysis · " + leagueName;
    var footerLeague = $("footer-league");
    if (footerLeague) { footerLeague.textContent = leagueName; }
    $("generated").textContent = "updated " + data.generated;

    var tabs = $("tabs");
    SECTIONS.forEach(function (section, index) {
      var button = el("button", null, section[0]);
      button.setAttribute("role", "tab");
      button.addEventListener("click", function () { show(index); });
      tabs.appendChild(button);
    });

    var wanted = (location.hash || "").replace("#", "");
    var start = 0;
    SECTIONS.forEach(function (section, index) {
      if (section[0].toLowerCase().replace(/[^a-z]/g, "") === wanted) { start = index; }
    });
    show(start);
  }

  fetch("data/analysis.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) { throw new Error("analysis.json " + response.status); }
      return response.json();
    })
    .then(function (payload) {
      data = payload;
      render();
    })
    .catch(function (error) {
      $("loading").textContent =
        "Could not load the league history. Try a refresh.";
      console.error(error);
    });
}());
