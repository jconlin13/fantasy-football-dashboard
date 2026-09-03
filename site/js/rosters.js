/* Rosters. Reads site/data/rosters.json: who closed each season on which team.
 *
 * Two pickers rather than one big table -- ten teams times ~18 players is 180
 * rows, unreadable at phone width. Pick a season, pick a manager, see their
 * roster. Same pattern as the Head-to-Head tab on the analysis page.
 */

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var panel = $("panel");
  var data = null;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  var STATUS_CLASS = { Kept: "paid", Drafted: null, Added: null };

  function renderRoster(year, manager) {
    var host = $("roster-host");
    host.textContent = "";

    var players = ((data.rosters[year] || {})[manager]) || [];
    if (!players.length) {
      host.appendChild(el("p", "explain", "No archived roster for " + manager + " in " + year + "."));
      return;
    }

    if (players.every(function (p) { return p.points === 0; })) {
      host.appendChild(el("p", "explain",
        year + " hasn't kicked off yet, so season points read 0.0 for " +
        "everyone -- this is the roster as it stands today, going into the draft."
      ));
    }

    var scroller = el("div", "scroller");
    var table = el("table");

    var thead = el("thead");
    var hr = el("tr");
    ["Pos", "Player", "Season pts", "How acquired"].forEach(function (h) {
      hr.appendChild(el("th", null, h));
    });
    thead.appendChild(hr);
    table.appendChild(thead);

    var tbody = el("tbody");
    players.forEach(function (p) {
      var tr = el("tr");
      tr.appendChild(el("td", null, p.position));
      tr.appendChild(el("td", null, p.name));
      tr.appendChild(el("td", null, p.points.toFixed(1)));

      var statusCell = el("td");
      var label = p.status + (p.round ? " (rd " + p.round + ")" : "");
      if (STATUS_CLASS[p.status]) {
        var badge = el("span", "badge " + STATUS_CLASS[p.status], label);
        statusCell.appendChild(badge);
      } else {
        statusCell.textContent = label;
      }
      tr.appendChild(statusCell);

      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    scroller.appendChild(table);
    host.appendChild(scroller);
  }

  function renderPickers() {
    panel.textContent = "";
    panel.appendChild(el("p", "explain",
      "Every manager's roster at the end of a season -- exactly who they had, " +
      "useful for keeper calls. “Season pts” is a player’s full real-world " +
      "season total, the same number on any ESPN player card, not just what " +
      "they scored while on this roster."
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
