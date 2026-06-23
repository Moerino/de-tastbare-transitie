/* ============================================================================
   Globaal on-screen QWERTY-NL toetsenbord.
   ============================================================================
   - Verschijnt zodra een <input type="text|search|email|url|tel"> of <textarea>
     focus krijgt.
   - Tikken op een toets voegt het karakter toe aan het actieve veld en vuurt
     een 'input' event zodat bestaande luisteraars (zoals de suggest-list in
     src/app.js) er meteen op reageren.
   - Sluiten via de ⇩-toets, ESC, of door buiten de input + toetsenbord te
     tikken.

   Geen frameworks. Geen build-stap. Plain ES2017+.
============================================================================ */

(function () {
  "use strict";

  // ——— Configuratie ————————————————————————————————————————————————————————
  // Selecteert welke velden het toetsenbord triggeren. Velden met
  // [data-no-osk] worden expliciet overgeslagen (bv. voor verborgen velden).
  const TRIGGER_SELECTOR =
    'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([data-no-osk]), textarea:not([data-no-osk])';

  // QWERTY-NL compacte layout. Elke string-array = één rij.
  // Speciale tokens (in capitals) worden in renderKey afgehandeld.
  const LAYOUT = {
    lower: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "BACKSPACE"],
      ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l", "ENTER"],
      ["SHIFT", "z", "x", "c", "v", "b", "n", "m", "-"],
      ["SPACE", "HIDE"],
    ],
    upper: [
      ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "BACKSPACE"],
      ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"],
      ["A", "S", "D", "F", "G", "H", "J", "K", "L", "ENTER"],
      ["SHIFT", "Z", "X", "C", "V", "B", "N", "M", "-"],
      ["SPACE", "HIDE"],
    ],
  };

  // ——— State ——————————————————————————————————————————————————————————————
  let panel = null;
  let backdrop = null;
  let activeInput = null;
  let isUpper = false;
  // Met deze flag voorkomen we dat een mousedown/pointerdown op een toets
  // direct een blur op het input-veld triggert (waardoor het toetsenbord
  // zou willen sluiten net voordat de toets verwerkt is).
  let suppressBlur = false;

  // ——— Build DOM —————————————————————————————————————————————————————————
  function ensurePanel() {
    if (panel) return;
    panel = document.createElement("div");
    panel.className = "osk-panel";
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", "Toetsenbord op het scherm");

    // mousedown/pointerdown vóór click — preventDefault houdt focus op input.
    panel.addEventListener("mousedown", (e) => {
      e.preventDefault();
      suppressBlur = true;
    });
    panel.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      suppressBlur = true;
    });

    backdrop = document.createElement("div");
    backdrop.className = "osk-backdrop";
    backdrop.addEventListener("click", hide);

    document.body.appendChild(panel);
    document.body.appendChild(backdrop);
    renderLayout();
  }

  function renderLayout() {
    const rows = isUpper ? LAYOUT.upper : LAYOUT.lower;
    panel.innerHTML = "";
    rows.forEach((row) => {
      const rowEl = document.createElement("div");
      rowEl.className = "osk-row";
      row.forEach((token) => rowEl.appendChild(renderKey(token)));
      panel.appendChild(rowEl);
    });
  }

  function renderKey(token) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "osk-key";
    btn.tabIndex = -1; // niet via tab bereikbaar; voorkomt focus-diefstal
    let label = token;
    let action = () => insertChar(token);

    switch (token) {
      case "BACKSPACE":
        btn.classList.add("osk-key--wide");
        label = "⌫";
        action = backspace;
        break;
      case "ENTER":
        btn.classList.add("osk-key--wide");
        label = "↵";
        action = pressEnter;
        break;
      case "SHIFT":
        btn.classList.add("osk-key--wide");
        label = isUpper ? "⇧" : "⇪";
        action = toggleShift;
        if (isUpper) btn.classList.add("is-pressed");
        break;
      case "SPACE":
        btn.classList.add("osk-key--space");
        label = "spatie";
        action = () => insertChar(" ");
        break;
      case "HIDE":
        btn.classList.add("osk-key--wide");
        btn.classList.add("osk-key--hide");
        label = "⇩";
        action = hide;
        break;
    }

    btn.textContent = label;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      flashPress(btn);
      action();
      // Suppress-blur weer vrijgeven na een tik (volgende frame, na focus
      // terugzetten op input).
      requestAnimationFrame(() => {
        suppressBlur = false;
        if (activeInput) activeInput.focus();
      });
    });
    return btn;
  }

  function flashPress(btn) {
    btn.classList.add("is-pressed");
    setTimeout(() => btn.classList.remove("is-pressed"), 120);
  }

  // ——— Insert-acties ——————————————————————————————————————————————————————
  function insertChar(ch) {
    if (!activeInput) return;
    insertText(activeInput, ch);
    // Na een letter automatisch terug naar lowercase (capslock-vrij).
    // Caps-lock-gedrag: dubbele-tap op SHIFT zou je kunnen toevoegen; nu uit.
    if (isUpper) {
      isUpper = false;
      renderLayout();
    }
  }

  function backspace() {
    if (!activeInput) return;
    const start = activeInput.selectionStart;
    const end = activeInput.selectionEnd;
    if (start === null) {
      activeInput.value = activeInput.value.slice(0, -1);
    } else if (start !== end) {
      // Selectie aanwezig — verwijder selectie.
      const v = activeInput.value;
      activeInput.value = v.slice(0, start) + v.slice(end);
      activeInput.selectionStart = activeInput.selectionEnd = start;
    } else if (start > 0) {
      const v = activeInput.value;
      activeInput.value = v.slice(0, start - 1) + v.slice(start);
      activeInput.selectionStart = activeInput.selectionEnd = start - 1;
    }
    fireInputEvent(activeInput);
  }

  function pressEnter() {
    if (!activeInput) return;
    if (activeInput.tagName === "TEXTAREA") {
      insertText(activeInput, "\n");
      return;
    }
    // Voor inputs: probeer de naam te submitten via het form, anders blur.
    const form = activeInput.form;
    if (form) {
      // requestSubmit triggert form-validatie correct.
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    } else {
      activeInput.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true })
      );
    }
  }

  function toggleShift() {
    isUpper = !isUpper;
    renderLayout();
  }

  function insertText(el, text) {
    const start = el.selectionStart;
    const end = el.selectionEnd;
    if (start === null || end === null) {
      el.value = (el.value || "") + text;
    } else {
      const v = el.value || "";
      el.value = v.slice(0, start) + text + v.slice(end);
      el.selectionStart = el.selectionEnd = start + text.length;
    }
    fireInputEvent(el);
  }

  function fireInputEvent(el) {
    // 'input' triggert de suggest-list en andere reactieve UI.
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  // ——— Toon/Verberg ————————————————————————————————————————————————————————
  function show(target) {
    ensurePanel();
    activeInput = target;
    isUpper = false;
    renderLayout();
    // Volgende frame zodat de transform-transition vuurt.
    requestAnimationFrame(() => {
      panel.classList.add("is-open");
      backdrop.classList.add("is-open");
      document.body.classList.add("osk-open");
      // Wacht tot het paneel uitgeschoven is (transition 280 ms) en lift dan
      // de input boven het toetsenbord uit als hij eronder verdwijnt.
      requestAnimationFrame(() => {
        setTimeout(liftInputIfHidden, 30);
      });
    });
  }

  function hide() {
    if (!panel) return;
    panel.classList.remove("is-open");
    backdrop.classList.remove("is-open");
    document.body.classList.remove("osk-open");
    // Reset elke shift die we hebben aangebracht.
    document.querySelectorAll("[data-osk-shifted]").forEach((el) => {
      el.style.transform = "";
      el.style.transition = "";
      delete el.dataset.oskShifted;
    });
    if (activeInput) {
      activeInput.blur();
      activeInput = null;
    }
  }

  // Containers die hun eigen CSS-shift hebben (zie keyboard.css). De JS lift
  // mag ze niet aanraken omdat hun bestaande transform (bv. translateX(-50%))
  // anders kapotgaat.
  const OSK_CSS_HANDLED = ".route-overlay";

  /**
   * Als de actieve input onder de bovenkant van het toetsenbord ligt, schuif
   * dan zijn dichtstbijzijnde fixed/absolute container omhoog zodat hij
   * zichtbaar wordt. Voor inputs in normale page-flow gebruiken we scrollIntoView.
   */
  function liftInputIfHidden() {
    if (!activeInput || !panel) return;
    // Element zit al in een container die zijn eigen CSS-shift heeft? Niets doen.
    if (activeInput.closest(OSK_CSS_HANDLED)) return;
    const inputRect = activeInput.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const gap = 16; // pixels ruimte tussen input en toetsenbord
    const overlap = inputRect.bottom - panelRect.top + gap;
    if (overlap <= 0) return;

    // Zoek de dichtstbijzijnde positioned ancestor om te verschuiven.
    let container = activeInput.parentElement;
    while (
      container &&
      container !== document.body &&
      !["fixed", "absolute", "sticky"].includes(
        getComputedStyle(container).position
      )
    ) {
      container = container.parentElement;
    }

    if (container && container !== document.body) {
      container.style.transition = "transform 0.28s ease-out";
      container.style.transform = `translateY(-${overlap}px)`;
      container.dataset.oskShifted = "1";
    } else {
      // In normale page-flow → scroll de pagina.
      window.scrollBy({ top: overlap, behavior: "smooth" });
    }
  }

  // ——— Triggers ————————————————————————————————————————————————————————————
  document.addEventListener("focusin", (e) => {
    const t = e.target;
    if (!t || !(t instanceof Element)) return;
    if (!t.matches(TRIGGER_SELECTOR)) return;
    show(t);
  });

  document.addEventListener("focusout", (e) => {
    // Wanneer een toets is ingedrukt willen we het toetsenbord niet sluiten.
    if (suppressBlur) return;
    // Korte vertraging zodat een focus-shift naar een ander veld het paneel
    // open kan houden.
    setTimeout(() => {
      if (!activeInput) return;
      const next = document.activeElement;
      if (next && next.matches && next.matches(TRIGGER_SELECTOR)) {
        activeInput = next;
        return;
      }
      hide();
    }, 50);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel && panel.classList.contains("is-open")) {
      hide();
    }
  });
})();
