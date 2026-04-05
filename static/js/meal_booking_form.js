(function () {
  function bind(meetingId, titleId) {
    var sel = document.getElementById(meetingId);
    var inp = document.getElementById(titleId);
    if (!sel || !inp) return;
    sel.addEventListener("change", function () {
      var opt = sel.options[sel.selectedIndex];
      var v = opt.getAttribute("data-suggested-title");
      if (v !== null && v !== "") inp.value = v;
    });
  }
  bind("meal_booking_list_meeting", "meal_booking_list_title");
  bind("meal_booking_setup_meeting", "meal_booking_setup_title");
})();
