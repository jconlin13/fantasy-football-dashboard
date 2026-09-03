/* Rosters. Reads site/data/rosters.json: who closed each season on which team.
 *
 * Three pickers rather than one big table -- ten teams times ~18 players is
 * 180 rows, unreadable at phone width. Pick a season, pick a manager, pick a
 * sort, see their roster. Same season/manager pattern as the Head-to-Head tab
 * on the analysis page.
 */

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var panel = $("panel");
  var data = null;
  var sortMode = "acquired";

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function dash(value) {
    return value === null || value === undefined ? "—" : value;
  }

  /* A player was drafted by this team whenever `round` is set -- true for
     both the Drafted and (never-seen-in-practice) Added/kept statuses, false
     for a Free Agent pickup. Sorting on that instead of the display string
     keeps the two concerns separate: what a row says vs. where it belongs. */
  function wasDrafted(p) {
    return p.round !== null && p.round !== undefined;
  }

  function acquiredLabel(p) {
    if (wasDrafted(p) && p.status === "Drafted") {
      return "Drafted " + p.round + "." + p.roundPick;
    }
    return p.status; // "Free Agent", or the rare flagged-keeper "Added"
  }

  /* A drafted pick carries real data worth a badge; a free-agent add is the
     "nothing eventful happened" case and stays plain text, so the badges
     that do appear are worth glancing at rather than covering every row. */
  function acquiredCell(p) {
    var label = acquiredLabel(p);
    if (wasDrafted(p) && p.status === "Drafted") {
      return el("span", "badge drafted", label);
    }
    return document.createTextNode(label);
  }

  function sortPlayers(players) {
    var copy = players.slice();
    if (sortMode === "points") {
      copy.sort(function (a, b) { return b.points - a.points; });
      return copy;
    }
    // "Draft order": every drafted player first, round 1 to last, then every
    // free agent after, highest-scoring first within each group.
    copy.sort(function (a, b) {
      var aDrafted = wasDrafted(a), bDrafted = wasDrafted(b);
      if (aDrafted !== bDrafted) { return aDrafted ? -1 : 1; }
      if (aDrafted) { return a.round - b.round; }
      return b.points - a.points;
    });
    return copy;
  }

  function renderRoster(year, manager) {
    var host = $("roster-host");
    host.textContent = "";

    var players = ((data.rosters[year] || {})[manager]) || [];
    if (!players.length) {
      host.appendChild(el("p", "explain", "No archived roster for " + manager + " in " + year + "."));
      return;
    }

    // Only the single newest season carries next-year outlook -- browsing an
    // old roster has nothing to project forward from, so those two columns
    // simply don't exist on the data for any other year.
    var hasOutlook = Object.prototype.hasOwnProperty.call(players[0], "nextSeasonPoints");
    var nextYear = Number(year) + 1;

    if (hasOutlook) {
      host.appendChild(el("p", "explain",
        nextYear + " pts is ESPN's own projection. " + nextYear + " round.pick is " +
        "split from ESPN's industry-wide average draft position for a " +
        Object.keys(data.rosters[year]).length + "-team league -- not this " +
        "league's actual future draft, which hasn't happened. A dash means the " +
        "player isn't on any of next season's ten rosters yet."
      ));
    }

    var scroller = el("div", "scroller");
    var table = el("table");

    var headers = ["Player", year + " pts", "Acquired"];
    if (hasOutlook) {
      headers.push(nextYear + " pts (proj.)", nextYear + " rd (proj.)");
    }

    var thead = el("thead");
    var hr = el("tr");
    headers.forEach(function (h) { hr.appendChild(el("th", null, h)); });
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = el("tbody");
    sortPlayers(players).forEach(function (p) {
      var tr = el("tr");
      tr.appendChild(el("td", null, p.name));
      tr.appendChild(el("td", null, p.points.toFixed(1)));
      var acquiredTd = el("td");
      acquiredTd.appendChild(acquiredCell(p));
      tr.appendChild(acquiredTd);
      if (hasOutlook) {
        var hasProj = p.nextSeasonPoints !== null && p.nextSeasonPoints !== undefined;
        tr.appendChild(el("td", null, dash(hasProj ? p.nextSeasonPoints.toFixed(1) : null)));
        // round.pick, matching the Drafted column's format -- never the raw
        // ADP float, which would print things like "1.33" and read exactly
        // like round 1 pick 33, nonsensical in a 10-team league.
        var hasAdpRound = p.nextSeasonRound !== null && p.nextSeasonRound !== undefined
          && p.nextSeasonPick !== null && p.nextSeasonPick !== undefined;
        tr.appendChild(el("td", null, dash(hasAdpRound ? p.nextSeasonRound + "." + p.nextSeasonPick : null)));
      }
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroller.appendChild(table);
    host.appendChild(scroller);
  }

  function renderPickers() {
    panel.textContent = "";
    panel.appendChild(el("p", "explain",
      "End-of-season rosters. “Season points” includes a free agent’s " +
      "points from before they were added to this team."
    ));

    var yearPicker = el("select");
    data.seasons.forEach(function (year) {
      var option = el("option", null, year);
      option.value = year;
      yearPicker.appendChild(option);
    });
    panel.appendChild(yearPicker);

    var managerPicker = el("select");
    panel.appendChild(managerPicker);

    var sortPicker = el("select");
    [["points", "Sort: points"], ["acquired", "Sort: draft order"]].forEach(function (pair) {
      var option = el("option", null, pair[1]);
      option.value = pair[0];
      sortPicker.appendChild(option);
    });
    sortPicker.value = sortMode;
    panel.appendChild(sortPicker);

    var host = el("div");
    host.id = "roster-host";
    panel.appendChild(host);

    function fillManagers(year) {
      var managers = Object.keys(data.rosters[year] || {}).sort();
      managerPicker.textContent = "";
      managers.forEach(function (manager) {
        var option = el("option", null, manager);
        option.value = manager;
        managerPicker.appendChild(option);
      });
      if (managers.length) { renderRoster(year, managers[0]); }
    }

    yearPicker.addEventListener("change", function () {
      fillManagers(Number(yearPicker.value));
    });
    managerPicker.addEventListener("change", function () {
      renderRoster(Number(yearPicker.value), managerPicker.value);
    });
    sortPicker.addEventListener("change", function () {
      sortMode = sortPicker.value;
      renderRoster(Number(yearPicker.value), managerPicker.value);
    });

    fillManagers(data.seasons[0]);
  }

  fetch("data/rosters.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) { throw new Error("rosters.json " + response.status); }
      return response.json();
    })
    .then(function (payload) {
      data = payload;
      $("generated").textContent = "updated " + data.generated;
      renderPickers();
    })
    .catch(function (error) {
      $("loading").textContent = "Could not load rosters. Try a refresh.";
      console.error(error);
    });
}());
