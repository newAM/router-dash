// Progressive enhancements: local timestamps and lease table sorting.
// No external dependencies; the page is fully usable without JavaScript.
"use strict";

// Render <time datetime="..."> elements in the browser's local timezone
// as YYYY-MM-DD HH:MM (24-hour clock), independent of the browser locale.
// The server renders the same shape in UTC as a no-JS fallback.
function localTimes() {
  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }
  document.querySelectorAll("time[datetime]").forEach(function (el) {
    var d = new Date(el.getAttribute("datetime"));
    if (!isNaN(d.getTime())) {
      el.textContent =
        d.getFullYear() +
        "-" +
        pad(d.getMonth() + 1) +
        "-" +
        pad(d.getDate()) +
        " " +
        pad(d.getHours()) +
        ":" +
        pad(d.getMinutes());
    }
  });
}

// Sort the lease table when a column header button is clicked.
// Rows are ordered by the canonical data-v attribute the server attaches
// to each cell (e.g. an IPv4 address as a 32-bit integer).
function enableSorting() {
  var table = document.querySelector("table.sortable");
  if (!table || !table.tHead || !table.tBodies[0]) return;
  var tbody = table.tBodies[0];

  table.tHead.addEventListener("click", function (ev) {
    var button = ev.target.closest("th button");
    if (!button) return;
    var th = button.closest("th");
    var headers = Array.prototype.slice.call(th.parentElement.children);
    var col = headers.indexOf(th);
    if (col < 0) return;
    var type = button.dataset.type || "str";
    var descending = th.getAttribute("aria-sort") === "ascending";

    headers.forEach(function (h) {
      h.removeAttribute("aria-sort");
    });
    th.setAttribute("aria-sort", descending ? "descending" : "ascending");

    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var av = a.cells[col].getAttribute("data-v") || "";
      var bv = b.cells[col].getAttribute("data-v") || "";
      var cmp;
      if (type === "num") {
        var an = parseFloat(av);
        var bn = parseFloat(bv);
        cmp = (isNaN(an) ? 0 : an) - (isNaN(bn) ? 0 : bn);
      } else {
        cmp = av.localeCompare(bv);
      }
      return descending ? -cmp : cmp;
    });
    rows.forEach(function (row) {
      tbody.appendChild(row);
    });
  });
}

localTimes();
enableSorting();
