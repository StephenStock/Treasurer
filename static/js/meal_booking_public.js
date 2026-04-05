(function () {
  var form = document.getElementById("public-meal-form");
  var sel = document.getElementById("guest_count");
  var container = document.getElementById("guest-slots");
  if (!sel || !container) return;

  function sync() {
    var n = parseInt(sel.value, 10);
    if (isNaN(n)) n = 0;
    var slots = container.querySelectorAll(".guest-slot");
    slots.forEach(function (el) {
      var idx = parseInt(el.getAttribute("data-guest-index"), 10);
      var hide = idx > n;
      el.hidden = hide;
      el.querySelectorAll("input, select, textarea").forEach(function (inp) {
        inp.disabled = hide;
      });
    });
  }

  sel.addEventListener("change", sync);
  sync();

  if (form) {
    form.addEventListener("submit", sync);
  }
})();
