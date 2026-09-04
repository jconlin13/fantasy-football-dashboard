/* Splash page. Reads site/data/draft.json and renders whatever is filled in.
 *
 * Nothing here assumes a field exists. The config is meant to be filled in a
 * piece at a time as the draft firms up, so a missing value hides its card
 * rather than rendering an empty box.
 */

(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  function show(el) { if (el) { el.hidden = false; } }

  /* "August 28th" reads better than "August 28" on a page whose whole job is
     to tell you when the draft is. */
  function ordinal(n) {
    if (n % 100 >= 11 && n % 100 <= 13) { return n + "th"; }
    return n + ["th", "st", "nd", "rd"][n % 10] || n + "th";
  }

  function formatWhen(date) {
    var day = date.toLocaleDateString(undefined, { weekday: "long" });
    var month = date.toLocaleDateString(undefined, { month: "long" });
    var time = date.toLocaleTimeString(undefined, {
      hour: "numeric",
      minute: "2-digit"
    });
    return day + ", " + month + " " + ordinal(date.getDate()) + " · " + time;
  }

  function startCountdown(date) {
    var card = $("countdown-card");
    var units = $("clock").querySelectorAll("[data-unit]");

    function tick() {
      var remaining = date.getTime() - Date.now();
      if (remaining <= 0) {
        // The countdown has done its job; stop showing a row of zeroes.
        card.hidden = true;
        return false;
      }
      var seconds = Math.floor(remaining / 1000);
      var values = {
        days: Math.floor(seconds / 86400),
        hours: Math.floor(seconds / 3600) % 24,
        minutes: Math.floor(seconds / 60) % 60,
        seconds: seconds % 60
      };
      for (var i = 0; i < units.length; i++) {
        var unit = units[i];
        var value = values[unit.getAttribute("data-unit")];
        unit.textContent = value < 10 ? "0" + value : String(value);
      }
      return true;
    }

    if (tick()) {
      show(card);
      setInterval(tick, 1000);
    }
  }

  function sha256Hex(text) {
    var bytes = new TextEncoder().encode(text);
    return crypto.subtle.digest("SHA-256", bytes).then(function (buffer) {
      var out = [];
      new Uint8Array(buffer).forEach(function (b) {
        out.push(b.toString(16).padStart(2, "0"));
      });
      return out.join("");
    });
  }

  /* The gate is friction, not security -- the page is static, so the check runs
     in the visitor's browser and the hash is public. ESPN's own login is what
     actually keeps a stranger out of the draft room. Treating it as anything
     more than a speed bump would be kidding ourselves. */
  function setupLaunch(data) {
    var link = $("launch");
    var gate = $("gate");
    var note = $("gate-note");
    if (!data.espnUrl) { return; }

    link.href = data.espnUrl;

    var locked = !!data.passphraseSha256;
    var unlocked = sessionStorage.getItem("mhd-unlocked") === data.passphraseSha256;
    // crypto.subtle only exists in a secure context, so it is missing over
    // file://. Rather than lock everyone out during local development, fall
    // back to showing the button -- see the note above about what this gate is.
    var canHash = !!(window.crypto && crypto.subtle);

    if (!locked || unlocked || !canHash) {
      show(link);
      return;
    }

    show(gate);
    gate.addEventListener("submit", function (event) {
      event.preventDefault();
      sha256Hex($("gate-input").value.trim()).then(function (hex) {
        if (hex === data.passphraseSha256) {
          sessionStorage.setItem("mhd-unlocked", data.passphraseSha256);
          gate.hidden = true;
          note.hidden = true;
          show(link);
        } else {
          note.textContent = "Not the password. Ask in the group chat.";
          note.className = "gate-note error";
          show(note);
        }
      });
    });
  }

  function renderOrder(order) {
    if (!order || !order.length) { return; }
    var list = $("order-list");

    order.forEach(function (entry) {
      var li = document.createElement("li");

      var pick = document.createElement("span");
      pick.className = "pick";
      pick.textContent = entry.pick;
      li.appendChild(pick);

      var name = document.createElement("span");
      name.className = "name";
      name.textContent = entry.name;
      li.appendChild(name);

      if (entry.status) {
        var badge = document.createElement("span");
        // Only a clean "paid" earns the solid accent treatment; anything
        // else -- "mostly paid", etc -- gets the gold in-progress tone
        // rather than rounding up to fully paid, and is shown verbatim.
        badge.className = "badge " + (entry.status === "paid" ? "paid" : "partial");
        badge.textContent = entry.status === "paid" ? "Paid ✓" : entry.status;
        li.appendChild(badge);
      }

      list.appendChild(li);
    });

    show($("order-card"));
  }

  function render(data) {
    if (data.leagueName) {
      document.title = data.leagueName + " · Draft Day";
      var footerLeague = $("footer-league");
      if (footerLeague) { footerLeague.textContent = data.leagueName; }
    }

    if (data.label) {
      $("hero-label").textContent = data.label;
      if (data.kind) {
        $("hero-kind").textContent = data.kind;
        show($("hero-kind"));
      }
      show($("hero"));
    }

    var date = data.datetime ? new Date(data.datetime) : null;
    if (date && isNaN(date.getTime())) { date = null; }

    if (date || data.location || data.espnUrl) {
      if (data.kind) { $("draft-kind").textContent = data.kind; }
      // No date means ESPN has no draft scheduled and nobody has announced one
      // by hand. Say so plainly rather than counting down to a placeholder.
      $("draft-when").textContent = date ? formatWhen(date) : "Not set";
      if (data.location) {
        $("draft-where").textContent = data.location;
        show($("draft-where"));
      }
      setupLaunch(data);
      show($("draft-card"));
    }

    if (date) { startCountdown(date); }

    var dues = data.dues || {};
    if (dues.amount || dues.venmoUrl) {
      $("dues-amount").textContent = dues.amount || "TBD";
      var venmo = $("venmo");
      var venmoHint = $("venmo-hint");
      if (dues.venmoUrl) {
        venmo.href = dues.venmoUrl;
        venmo.textContent = "Pay Dues";
        venmo.className = "btn";
      } else {
        // A missing Venmo link is worth surfacing, not hiding -- an owner
        // who forgot to set it should see the gap here, not hear about it
        // from the group chat instead. Not a working link: href="#" just
        // scrolls to the top of the page rather than going anywhere wrong.
        venmo.href = "#";
        venmo.textContent = "Add Venmo";
        venmo.className = "btn secondary";
        show(venmoHint);
      }
      show(venmo);
      show($("dues-card"));
    }

    renderOrder(data.order);
  }

  fetch("data/draft.json", { cache: "no-store" })
    .then(function (response) {
      if (!response.ok) { throw new Error("draft.json " + response.status); }
      return response.json();
    })
    .then(render)
    .catch(function (error) {
      console.error("could not load draft data", error);
    });
}());
