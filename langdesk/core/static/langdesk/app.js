// Langdesk: small progressive enhancements. Everything works without JavaScript.
(function () {
  "use strict";

  // Show or hide fields that only apply to one modality (e.g. the site picker).
  function syncModality(form) {
    var checked = form.querySelector('input[name="modality"]:checked');
    var mode = checked ? checked.value : "";
    form.querySelectorAll("[data-show-when]").forEach(function (el) {
      var modes = el.getAttribute("data-show-when").split(" ");
      el.classList.toggle("is-hidden", modes.indexOf(mode) === -1);
    });
    form.querySelectorAll("[data-required-when]").forEach(function (el) {
      var on = el.getAttribute("data-required-when").split(" ").indexOf(mode) !== -1;
      el.classList.toggle("is-hidden", !on);
    });
  }

  document.querySelectorAll("form[data-request-form]").forEach(function (form) {
    form.addEventListener("change", function (event) {
      if (event.target.name === "modality") syncModality(form);
    });
    syncModality(form);
  });

  // Copy-to-clipboard buttons.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.getElementById(button.getAttribute("data-copy"));
      if (!target || !navigator.clipboard) return;
      navigator.clipboard.writeText(target.value || target.textContent).then(function () {
        var label = button.textContent;
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = label; }, 1500);
      });
    });
  });

  // Confirm destructive actions.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  // Keep the coordinator board fresh while it sits open on a screen.
  var refresh = document.body.getAttribute("data-refresh");
  if (refresh) {
    setInterval(function () {
      var busy = document.activeElement && /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName);
      if (!document.hidden && !busy) window.location.reload();
    }, parseInt(refresh, 10) * 1000);
  }

  // Scroll SMS simulator thread to the newest message.
  var thread = document.querySelector(".thread");
  if (thread) thread.scrollTop = thread.scrollHeight;
})();
