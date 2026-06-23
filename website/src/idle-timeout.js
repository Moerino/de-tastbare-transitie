/**
 * 5 min inactiviteit → dialoog. Geen "Ja" binnen 15 s → welkom.
 * "Nee ik ben weg" → direct welkom. "Ja" sluit de dialoog en reset de 5 min timer.
 */
(function initIdleTimeout() {
  const IDLE_MS = 5 * 60 * 1000;
  const AWAY_MS = 15 * 1000;

  let idleTimerId = null;
  let awayTimerId = null;
  let countdownIntervalId = null;
  let dialogEl = null;
  let countdownEl = null;
  let dialogOpen = false;

  function welkomUrl() {
    return new URL("./welkom.html", window.location.href).href;
  }

  function goWelkom() {
    window.location.href = welkomUrl();
  }

  function clearAwayTimers() {
    if (awayTimerId) {
      clearTimeout(awayTimerId);
      awayTimerId = null;
    }
    if (countdownIntervalId) {
      clearInterval(countdownIntervalId);
      countdownIntervalId = null;
    }
  }

  function ensureDialog() {
    if (dialogEl) return dialogEl;
    dialogEl = document.createElement("dialog");
    dialogEl.id = "ehc-idle-dialog";
    dialogEl.className = "idle-dialog";
    dialogEl.innerHTML = [
      "<h2>Ben je er nog?</h2>",
      "<p id=\"ehc-idle-countdown\" class=\"idle-countdown\"></p>",
      "<div class=\"idle-dialog-actions\">",
      "<button type=\"button\" class=\"idle-yes\" id=\"ehc-idle-yes\">Ja, ik ben er</button>",
      "<button type=\"button\" class=\"idle-no\" id=\"ehc-idle-no\">Nee, ik ga weg</button>",
      "</div>",
    ].join("");
    document.body.appendChild(dialogEl);

    dialogEl.querySelector("#ehc-idle-yes").addEventListener("click", onYes);
    dialogEl.querySelector("#ehc-idle-no").addEventListener("click", onNo);
    return dialogEl;
  }

  function updateCountdown(secondsLeft) {
    if (!countdownEl) countdownEl = document.getElementById("ehc-idle-countdown");
    if (!countdownEl) return;
    if (secondsLeft > 0) {
      countdownEl.textContent = `Zo terug naar welkom (${secondsLeft}s).`;
    } else {
      countdownEl.textContent = "";
    }
  }

  function startAwaySequence() {
    clearAwayTimers();
    let left = Math.ceil(AWAY_MS / 1000);
    updateCountdown(left);
    countdownIntervalId = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(countdownIntervalId);
        countdownIntervalId = null;
        return;
      }
      updateCountdown(left);
    }, 1000);
    awayTimerId = setTimeout(() => {
      clearAwayTimers();
      goWelkom();
    }, AWAY_MS);
  }

  function openDialog() {
    if (dialogOpen) return;
    dialogOpen = true;
    clearTimeout(idleTimerId);
    idleTimerId = null;
    const dlg = ensureDialog();
    startAwaySequence();
    if (typeof dlg.showModal === "function") dlg.showModal();
  }

  function onYes() {
    clearAwayTimers();
    dialogOpen = false;
    if (dialogEl && typeof dialogEl.close === "function") dialogEl.close();
    updateCountdown(0);
    scheduleIdle();
  }

  function onNo() {
    clearAwayTimers();
    dialogOpen = false;
    if (dialogEl && typeof dialogEl.close === "function") dialogEl.close();
    goWelkom();
  }

  function scheduleIdle() {
    clearTimeout(idleTimerId);
    idleTimerId = setTimeout(openDialog, IDLE_MS);
  }

  function onActivity() {
    if (dialogOpen) return;
    scheduleIdle();
  }

  ["pointerdown", "keydown", "scroll", "touchstart", "click"].forEach((evt) => {
    window.addEventListener(evt, onActivity, { passive: true, capture: true });
  });

  scheduleIdle();
})();
