// Small enhancements on top of pages that work without this file.

/**
 * Show that a submitted form is working, so a slow FHIR server doesn't look like a dead button.
 * The button is disabled too, so a second click can't save a second run.
 */
function markBusy(event) {
  const button = event.target.querySelector("button[type=submit]");
  if (!button || button.disabled) return;
  button.dataset.label = button.textContent;
  button.textContent = button.dataset.busyLabel || "Working…";
  button.classList.add("is-busy");
  button.setAttribute("aria-busy", "true");
  button.disabled = true;
}

/** Undo the busy state when the browser shows this page again from its back/forward cache. */
function clearBusy(event) {
  if (!event.persisted) return;
  for (const button of document.querySelectorAll("button.is-busy")) {
    button.textContent = button.dataset.label;
    button.classList.remove("is-busy");
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }
}

document.addEventListener("submit", markBusy);
window.addEventListener("pageshow", clearBusy);
