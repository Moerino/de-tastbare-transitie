/*
 * tracking.js — alfatest-tracking + begeleide testflow voor
 * "De Tastbare Transitie".
 *
 * Wat dit script doet:
 *   1. Genereert/onthoudt een sessie-UUID per bezoeker (localStorage).
 *   2. Logt pageviews + kliks via tracker.php.
 *   3. Toont een vaste feedbackknop rechtsonder (m.u.v. alfatest- en
 *      welkomschermen).
 *   4. Bestuurt de begeleide alfatestflow: één taak tegelijk in een
 *      sticky banner, onzichtbare timer per taak, transitie-popup met
 *      sterrenrating bij voltooiing, en na T3 doorverwijzing naar de
 *      post-sessie vragenlijst (vragenlijst.html).
 *
 * Statusopslag:
 *   - localStorage  : sessie-id (overleeft refresh + nieuw tabblad).
 *   - sessionStorage: alfatest-state, taak-index, starttijden.
 *     Zo begint elke nieuwe browsersessie automatisch met een schone
 *     flow zodra ze opnieuw op alfatest.html starten.
 */

(function () {
  "use strict";

  // ===================================================================
  // CONFIG
  // ===================================================================
  const SCRIPT_EL = document.currentScript;
  const ENDPOINT =
    (SCRIPT_EL && SCRIPT_EL.getAttribute("data-endpoint")) ||
    window.EHC_TRACKER_ENDPOINT ||
    "./tracker.php";

  const STORAGE_KEY = "ehc_sessie_id";
  const PAGE = (
    (location.pathname.split("/").pop() || "index.html") + ""
  ).toLowerCase();

  // Pagina's waar geen FAB en geen taakbanner verschijnen.
  const ALFATEST_CHROME_HIDDEN = new Set([
    "welkom.html",
    "alfatest.html",
    "vragenlijst.html",
    "",
  ]);

  // ===================================================================
  // TAAK-DEFINITIES — elk thema komt één keer aan bod
  // ===================================================================
  const TASKS = [
    {
      key: "T1_hyperloop",
      num: 1,
      titel: "Taak 1: Wat is de hyperloop",
      opdracht:
        "Bekijk de pagina 'Wat is de hyperloop?'. Lees de uitleg en de tijdlijn en kijk een stukje van de video.",
      kort: "Bekijk de uitleg over de hyperloop.",
      vraag: "Was deze uitleg duidelijk voor jou?",
    },
    {
      key: "T2_co2",
      num: 2,
      titel: "Taak 2: CO₂ vergelijken op de kaart",
      opdracht:
        "Open de kaart, plan een rit van Groningen naar Berlijn en vergelijk de CO₂-uitstoot van de hyperloop met die van de auto.",
      kort: "Plan op de kaart Groningen naar Berlijn en vergelijk hyperloop met auto.",
      vraag: "Heb je gevonden wat je zocht?",
    },
    {
      key: "T3_geluid",
      num: 3,
      titel: "Taak 3: Geluid in de buurt",
      opdracht:
        "Zoek informatie op over hoeveel geluid de hyperloop maakt en hoe dat zich verhoudt tot een trein.",
      kort: "Lees de informatie over geluid.",
      vraag: "Was deze informatie duidelijk voor jou?",
    },
    {
      key: "T4_veiligheid",
      num: 4,
      titel: "Taak 4: Veiligheid",
      opdracht:
        "Bekijk de veiligheidspagina. Wat gebeurt er als er onverwacht lucht in de buis komt?",
      kort: "Lees hoe het systeem reageert als er iets misgaat.",
      vraag: "Voel je je goed geïnformeerd over de veiligheid?",
    },
    {
      key: "T5_regio",
      num: 5,
      titel: "Taak 5: Wat betekent het voor de regio",
      opdracht:
        "Bekijk de pagina over de regio. Wat verandert er volgens de installatie in Noord-Nederland door het EHC?",
      kort: "Lees wat het EHC betekent voor de regio.",
      vraag: "Was deze informatie duidelijk voor jou?",
    },
    {
      key: "T6_stem",
      num: 6,
      titel: "Taak 6: Jouw stem",
      opdracht:
        "Stel je hebt een vraag, idee of zorg over de hyperloop in jullie buurt. Laat dat achter via 'Jouw stem'.",
      kort: "Verstuur een vraag, idee of zorg via 'Jouw stem'.",
      vraag: "Hoe makkelijk was het om je stem te laten horen?",
    },
  ];
  const TOTAL_TASKS = TASKS.length;

  // ===================================================================
  // SESSIE-ID
  // ===================================================================
  function uuidv4() {
    if (window.crypto && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    const buf = new Uint8Array(16);
    if (window.crypto && crypto.getRandomValues) crypto.getRandomValues(buf);
    else for (let i = 0; i < 16; i++) buf[i] = Math.floor(Math.random() * 256);
    buf[6] = (buf[6] & 0x0f) | 0x40;
    buf[8] = (buf[8] & 0x3f) | 0x80;
    const h = Array.from(buf, (b) => b.toString(16).padStart(2, "0"));
    return (
      h.slice(0, 4).join("") + "-" +
      h.slice(4, 6).join("") + "-" +
      h.slice(6, 8).join("") + "-" +
      h.slice(8, 10).join("") + "-" +
      h.slice(10, 16).join("")
    );
  }

  function getSessionId() {
    try {
      let id = localStorage.getItem(STORAGE_KEY);
      if (!id) {
        id = uuidv4();
        localStorage.setItem(STORAGE_KEY, id);
      }
      return id;
    } catch (_) {
      if (!window.__ehcSessieFallback) window.__ehcSessieFallback = uuidv4();
      return window.__ehcSessieFallback;
    }
  }
  const SESSIE_ID = getSessionId();

  // ===================================================================
  // VERZENDEN
  // ===================================================================
  function send(payload) {
    const body = JSON.stringify({
      sessie_id: SESSIE_ID,
      pagina: PAGE,
      tijdstip: new Date().toISOString(),
      ...payload,
    });

    try {
      if (
        payload.actie === "pageleave" &&
        navigator.sendBeacon &&
        typeof Blob !== "undefined"
      ) {
        const blob = new Blob([body], { type: "application/json" });
        if (navigator.sendBeacon(ENDPOINT, blob)) return;
      }
    } catch (_) {}

    try {
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
        mode: "cors",
        credentials: "omit",
      }).catch(() => {});
    } catch (_) {}
  }

  function describeElement(el) {
    if (!el || el.nodeType !== 1) return "";
    const tag = el.tagName.toLowerCase();
    const id = el.id ? "#" + el.id : "";
    const cls =
      el.classList && el.classList.length
        ? "." + Array.from(el.classList).join(".")
        : "";
    let label =
      el.getAttribute("aria-label") ||
      el.getAttribute("data-track") ||
      (el.innerText || el.textContent || "").trim().slice(0, 80);
    if (label) label = label.replace(/\s+/g, " ");
    const href = el.getAttribute && el.getAttribute("href");
    return [
      tag + id + cls,
      label ? `text="${label}"` : "",
      href ? `href="${href}"` : "",
    ]
      .filter(Boolean)
      .join(" ");
  }

  // Coordinaat-suffix voor hotzone-analyse. Wordt door de admin afgesplitst
  // via SUBSTRING_INDEX(element, ' @[', 1) zodat de top-klikken-statistiek
  // ongewijzigd blijft, en geparseerd voor de heatmap.
  function coordSuffix(e) {
    const x = Math.round(e.clientX);
    const y = Math.round(e.clientY);
    const sy = Math.round(window.scrollY || 0);
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    return ` @[x=${x} y=${y} vw=${vw} vh=${vh} sy=${sy}]`;
  }

  // Admin-preview detectie: als een iframe in admin.php deze pagina laadt
  // met ?admin=1, dan slaan we tracking volledig over om datavervuiling te
  // voorkomen.
  function isAdminPreview() {
    try {
      const p = new URLSearchParams(location.search);
      if (p.get("admin") === "1") return true;
    } catch (_) {}
    return false;
  }
  const ADMIN_PREVIEW = isAdminPreview();

  // ===================================================================
  // AUTO-TRACKING
  // ===================================================================
  if (!ADMIN_PREVIEW) {
    send({ actie: "pageview", element: document.title || "" });

    document.addEventListener(
      "click",
      function (e) {
        const target = e.target.closest(
          "a, button, [role='button'], .menu-tile, .stem-filter"
        );
        if (!target) return;
        send({
          actie: "klik",
          element: describeElement(target) + coordSuffix(e),
        });
      },
      true
    );

    window.addEventListener("pagehide", function () {
      send({ actie: "pageleave", element: document.title || "" });
    });
  } else {
    // In admin-preview: rapporteer de scrollHeight aan de parent, zodat de
    // admin-iframe op de juiste hoogte kan worden gezet voor de heatmap.
    function reportHeight() {
      try {
        const h = Math.max(
          document.documentElement.scrollHeight,
          document.body ? document.body.scrollHeight : 0
        );
        window.parent.postMessage({
          type: "ehc-admin-preview-height",
          height: h,
          width: window.innerWidth,
        }, "*");
      } catch (_) {}
    }
    window.addEventListener("load", () => {
      reportHeight();
      setTimeout(reportHeight, 200);
      setTimeout(reportHeight, 800);
    });
    new ResizeObserver(reportHeight).observe(document.documentElement);
  }

  // ===================================================================
  // ALFATEST-STATE
  // ===================================================================
  function ssGet(k) {
    try { return sessionStorage.getItem(k); } catch (_) { return null; }
  }
  function ssSet(k, v) {
    try { sessionStorage.setItem(k, v); } catch (_) {}
  }
  function ssDel(k) {
    try { sessionStorage.removeItem(k); } catch (_) {}
  }

  function getState() {
    return {
      active: ssGet("ehc_alfatest_active") === "1",
      done: ssGet("ehc_alfatest_done") === "1",
      idx: parseInt(ssGet("ehc_alfatest_idx") || "0", 10) || 0,
    };
  }

  function currentTask() {
    const s = getState();
    if (!s.active || s.done) return null;
    return TASKS[s.idx] || null;
  }

  function startTimer(key) {
    ssSet("ehc_t_" + key + "_start", Date.now().toString());
  }
  function readDuration(key) {
    const v = parseInt(ssGet("ehc_t_" + key + "_start") || "0", 10);
    return v ? Date.now() - v : null;
  }

  // Wordt vanuit alfatest.html aangeroepen via window.EHCAlfa.start().
  function startAlfatest() {
    ssSet("ehc_alfatest_active", "1");
    ssSet("ehc_alfatest_idx", "0");
    ssDel("ehc_alfatest_done");
    startTimer(TASKS[0].key);
    send({
      actie: "alfatest_start",
      element: TASKS[0].key,
    });
  }

  function advanceTo(nextIdx) {
    if (nextIdx >= TOTAL_TASKS) {
      ssSet("ehc_alfatest_done", "1");
      send({ actie: "alfatest_voltooid", element: "alle_taken" });
      // Direct doorsturen naar de post-sessie vragenlijst.
      location.href = "./vragenlijst.html";
      return;
    }
    ssSet("ehc_alfatest_idx", String(nextIdx));
    startTimer(TASKS[nextIdx].key);
    send({ actie: "taak_start", element: TASKS[nextIdx].key });
    renderTaskBanner();
  }

  function completeCurrentTask(expectedKey) {
    const s = getState();
    if (!s.active || s.done) return;
    const task = TASKS[s.idx];
    if (!task) return;
    // Alleen voortgaan als de juiste taak nu actief is, anders alleen
    // een logregel zonder de flow te verstoren.
    if (task.key !== expectedKey) {
      send({
        actie: "trigger_out_of_order",
        element: expectedKey + "_terwijl_" + task.key,
      });
      return;
    }
    // Voorkom dubbele popup als de gebruiker de banner spamt of een
    // trigger nog een keer vuurt terwijl het scherm al openstaat.
    if (document.querySelector(".ehc-feedback-overlay")) return;
    // BELANGRIJK: we loggen 'taak_voltooid' pas wanneer de tester
    // daadwerkelijk op 'Volgende taak' klikt. Sluiten met x, ESC of
    // klik buiten de popup houdt de taak actief.
    send({ actie: "taak_afronden_geopend", element: task.key });
    showTransitionPopup(task, s.idx);
  }

  // Beschikbaar maken voor alfatest.html (Start-knop).
  window.EHCAlfa = {
    start: startAlfatest,
    state: getState,
  };

  // ===================================================================
  // POPUP-FRAMEWORK
  // ===================================================================
  function buildPopup(opts) {
    const {
      title,
      askText,
      includeText = true,
      requireScore = true,
      submitText = "Verstuur",
      cancelText = "Annuleer",
      showCancel = true,
      onSubmit,
      onClose,
      autoCloseMs = 900,
    } = opts;

    const overlay = document.createElement("div");
    overlay.className = "ehc-feedback-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", title || "Feedback");

    overlay.innerHTML = `
      <div class="ehc-feedback-modal">
        <button type="button" class="ehc-feedback-close" aria-label="Sluiten">×</button>
        <h2 class="ehc-feedback-title"></h2>
        <p class="ehc-feedback-ask"></p>
        <div class="ehc-stars" role="radiogroup" aria-label="Beoordeling">
          ${[1, 2, 3, 4, 5]
            .map(
              (n) =>
                `<button type="button" class="ehc-star" data-value="${n}" role="radio" aria-checked="false" aria-label="${n} ster${n > 1 ? "ren" : ""}">★</button>`
            )
            .join("")}
        </div>
        <label class="ehc-feedback-textwrap${includeText ? "" : " is-hidden"}">
          <span class="ehc-feedback-textlabel">Toelichting (optioneel)</span>
          <textarea class="ehc-feedback-text" rows="3" maxlength="2000"
            placeholder="Wat wil je nog kwijt?"></textarea>
        </label>
        <div class="ehc-feedback-actions">
          ${showCancel ? `<button type="button" class="ehc-feedback-cancel"></button>` : ""}
          <button type="button" class="ehc-feedback-submit" disabled></button>
        </div>
        <p class="ehc-feedback-thanks" role="status">Bedankt voor je feedback!</p>
      </div>
    `;

    overlay.querySelector(".ehc-feedback-title").textContent = title || "";
    overlay.querySelector(".ehc-feedback-ask").textContent = askText || "";
    const submitBtn = overlay.querySelector(".ehc-feedback-submit");
    submitBtn.textContent = submitText;
    const cancelBtn = overlay.querySelector(".ehc-feedback-cancel");
    if (cancelBtn) cancelBtn.textContent = cancelText;
    if (!requireScore) submitBtn.disabled = false;

    let score = 0;
    const stars = overlay.querySelectorAll(".ehc-star");
    stars.forEach((star) => {
      star.addEventListener("click", () => {
        score = parseInt(star.getAttribute("data-value"), 10);
        stars.forEach((s) => {
          const v = parseInt(s.getAttribute("data-value"), 10);
          const on = v <= score;
          s.classList.toggle("is-active", on);
          s.setAttribute("aria-checked", on ? "true" : "false");
        });
        if (requireScore) submitBtn.disabled = score < 1;
      });
    });

    function close(reason) {
      overlay.classList.add("is-closing");
      setTimeout(() => {
        overlay.remove();
        if (typeof onClose === "function") onClose(reason);
      }, 180);
    }

    overlay.querySelector(".ehc-feedback-close").addEventListener("click", () => close("close"));
    if (cancelBtn) {
      cancelBtn.addEventListener("click", () => close("cancel"));
    }
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close("outside");
    });
    function onKey(e) {
      if (e.key === "Escape") {
        document.removeEventListener("keydown", onKey);
        close("escape");
      }
    }
    document.addEventListener("keydown", onKey);

    submitBtn.addEventListener("click", () => {
      const text = overlay.querySelector(".ehc-feedback-text").value.trim();
      if (typeof onSubmit === "function") onSubmit({ score, text });
      const thanks = overlay.querySelector(".ehc-feedback-thanks");
      thanks.classList.add("is-visible");
      submitBtn.disabled = true;
      setTimeout(() => close("submit"), autoCloseMs);
    });

    document.body.appendChild(overlay);
    setTimeout(() => stars[0] && stars[0].focus(), 30);
    return overlay;
  }

  // ===================================================================
  // FEEDBACK-FAB (algemene knop rechtsonder)
  // ===================================================================
  // ——— Marker-plaatsing voor pinpoint feedback ———
  let activeMarker = null;

  function describeElementAt(x, y) {
    const el = document.elementFromPoint(x, y);
    if (!el) return "geen_element";
    const parts = [el.tagName.toLowerCase()];
    if (el.id) parts.push("#" + el.id);
    if (el.classList && el.classList.length) {
      // Negeer onze eigen marker/popup classes om ruis te beperken.
      const cls = Array.from(el.classList).filter(
        (c) => !c.startsWith("ehc-")
      );
      if (cls.length) parts.push("." + cls.join("."));
    }
    let txt = (el.innerText || el.textContent || "").trim();
    txt = txt.replace(/\s+/g, " ").slice(0, 60);
    return parts.join("") + (txt ? ' text="' + txt + '"' : "");
  }

  function placeMarker(clientX, clientY) {
    if (activeMarker) activeMarker.remove();
    const dot = document.createElement("div");
    dot.className = "ehc-marker-dot";
    dot.style.left = clientX + "px";
    dot.style.top = clientY + "px";
    dot.setAttribute("aria-hidden", "true");
    document.body.appendChild(dot);
    activeMarker = dot;
    return {
      clientX,
      clientY,
      pageX: clientX + window.scrollX,
      pageY: clientY + window.scrollY,
      viewportW: window.innerWidth,
      viewportH: window.innerHeight,
      scrollY: window.scrollY,
      element: describeElementAt(clientX, clientY),
    };
  }

  function clearMarker() {
    if (activeMarker) {
      activeMarker.remove();
      activeMarker = null;
    }
  }

  function formatMarkerForLog(m) {
    if (!m) return "geen_marker";
    return (
      "marker x=" + Math.round(m.clientX) +
      " y=" + Math.round(m.clientY) +
      " viewport=" + m.viewportW + "x" + m.viewportH +
      " scrollY=" + Math.round(m.scrollY) +
      " | " + m.element
    );
  }

  function startMarkerMode(onPicked) {
    // Voorkom dubbel openen.
    if (document.querySelector(".ehc-marker-instruction")) return;

    const banner = document.createElement("div");
    banner.className = "ehc-marker-instruction";
    banner.innerHTML = `
      <span class="ehc-marker-instruction-text">
        Klik op de plek waar je feedback over hebt.
      </span>
      <button type="button" class="ehc-marker-skip">Sla over</button>
      <button type="button" class="ehc-marker-cancel" aria-label="Annuleer">×</button>
    `;
    document.body.appendChild(banner);
    document.body.classList.add("ehc-marker-mode");

    function cleanup() {
      document.body.classList.remove("ehc-marker-mode");
      banner.remove();
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("keydown", onKey);
    }

    function onDocClick(e) {
      // Klikken op de instructiebanner zelf telt niet als marker-plek.
      if (banner.contains(e.target)) return;
      // Negeer klik op de FAB zelf zodat openen → direct sluiten niet kan.
      if (e.target.closest(".ehc-feedback-fab")) return;
      e.preventDefault();
      e.stopPropagation();
      const marker = placeMarker(e.clientX, e.clientY);
      cleanup();
      onPicked(marker);
    }

    function onKey(e) {
      if (e.key === "Escape") {
        cleanup();
        // ESC = volledig annuleren (zelfde als x).
        onPicked("cancelled");
      }
    }

    banner.querySelector(".ehc-marker-skip").addEventListener("click", () => {
      cleanup();
      onPicked(null);
    });
    banner.querySelector(".ehc-marker-cancel").addEventListener("click", () => {
      cleanup();
      onPicked("cancelled");
    });

    // Capture-phase zodat we klikken op andere knoppen vóór ze afvangen.
    setTimeout(() => {
      document.addEventListener("click", onDocClick, true);
      document.addEventListener("keydown", onKey);
    }, 0);
  }

  function openGeneralFeedback() {
    send({ actie: "feedback_geopend", element: "feedbackknop" });
    startMarkerMode((marker) => {
      if (marker === "cancelled") {
        // Volledig geannuleerd, geen popup openen.
        send({ actie: "feedback_geannuleerd", element: "marker_cancelled" });
        return;
      }
      const markerInfo = formatMarkerForLog(marker);
      send({
        actie: marker ? "feedback_marker_geplaatst" : "feedback_marker_overgeslagen",
        element: markerInfo,
      });
      buildPopup({
        title: "Geef ons feedback",
        askText: marker
          ? "Wat wil je kwijt over de plek die je hebt aangetikt?"
          : "Hoe ervaar je dit moment van de installatie?",
        includeText: true,
        onSubmit: ({ score, text }) => {
          send({
            actie: "feedback",
            element: markerInfo,
            feedback_score: score,
            feedback_tekst: text || null,
          });
        },
        onClose: () => {
          // Marker mag blijven staan tijdens analyse; we ruimen op na sluiten.
          clearMarker();
        },
      });
    });
  }

  function mountFeedbackButton() {
    if (ALFATEST_CHROME_HIDDEN.has(PAGE)) return;
    if (document.querySelector(".ehc-feedback-fab")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ehc-feedback-fab";
    btn.setAttribute("aria-label", "Geef feedback");
    btn.innerHTML =
      '<span class="ehc-feedback-fab-icon" aria-hidden="true">★</span>' +
      '<span class="ehc-feedback-fab-text">Feedback</span>';
    btn.addEventListener("click", openGeneralFeedback);
    document.body.appendChild(btn);
  }

  // ===================================================================
  // TAAKBANNER
  // ===================================================================
  function isPreviewEmbed() {
    // De gevolgen-pagina laadt map-app.html in een iframe met
    // ?embed=preview; app.js zet daar body.map-embed-preview op.
    // In die preview-modus moet er géén banner verschijnen.
    if (document.body.classList.contains("map-embed-preview")) return true;
    try {
      if (window.self !== window.top) return true;
    } catch (_) {
      return true;
    }
    return false;
  }

  function renderTaskBanner() {
    const existing = document.querySelector(".ehc-task-banner");
    if (existing) existing.remove();

    const task = currentTask();
    if (!task) return;
    if (ALFATEST_CHROME_HIDDEN.has(PAGE)) return;
    if (isPreviewEmbed()) return;

    const banner = document.createElement("button");
    banner.type = "button";
    banner.className = "ehc-task-banner";
    banner.setAttribute("aria-label",
      "Klik om taak " + task.num + " af te ronden en te beoordelen");
    banner.innerHTML = `
      <div class="ehc-task-banner-inner">
        <div class="ehc-task-banner-meta">
          <span class="ehc-task-banner-num">Taak ${task.num} / ${TOTAL_TASKS}</span>
        </div>
        <p class="ehc-task-banner-text"></p>
        <span class="ehc-task-banner-hint" aria-hidden="true">Tik om af te ronden</span>
      </div>
    `;
    banner.querySelector(".ehc-task-banner-text").textContent = task.opdracht;
    banner.addEventListener("click", () => {
      const cur = currentTask();
      if (!cur) return;
      send({ actie: "taak_handmatig_voltooid", element: cur.key });
      completeCurrentTask(cur.key);
    });
    document.body.appendChild(banner);
    document.body.classList.add("ehc-has-task-banner");
  }

  // ===================================================================
  // TRANSITIE-POPUP (na voltooide taak)
  // ===================================================================
  function showTransitionPopup(task, idx) {
    const isLast = idx >= TOTAL_TASKS - 1;
    const nextTask = !isLast ? TASKS[idx + 1] : null;
    const submitLabel = isLast
      ? "Naar de vragenlijst"
      : "Volgende taak";

    // Kleine extra zin met de volgende opdracht als die er is.
    const ask = isLast
      ? task.vraag +
        " Hierna volgt nog een korte vragenlijst om je ervaring vast te leggen."
      : task.vraag +
        " Daarna krijg je taak " + (idx + 2) + ": " + nextTask.kort;

    buildPopup({
      title: "Taak " + task.num + " afronden",
      askText: ask,
      includeText: true,
      requireScore: false,
      showCancel: false,
      submitText: submitLabel,
      autoCloseMs: 400,
      onSubmit: ({ score, text }) => {
        // Pas hier wordt de taak echt voltooid: log duur + feedback.
        const dur = readDuration(task.key);
        send({
          actie: "taak_voltooid",
          element: task.key,
          feedback_tekst: dur !== null ? "duration_ms=" + dur : null,
        });
        send({
          actie: "taak_feedback",
          element: task.key,
          feedback_score: score,
          feedback_tekst: text || null,
        });
      },
      onClose: (reason) => {
        if (reason === "submit") {
          advanceTo(idx + 1);
        } else {
          // x, ESC of klik buiten de popup: taak blijft gewoon actief.
          // Tester kan via de banner de popup opnieuw openen.
          send({
            actie: "taak_afronden_afgebroken",
            element: task.key + "|reason=" + reason,
          });
        }
      },
    });
  }

  // ===================================================================
  // PAGINA-SPECIFIEKE TRIGGERS
  // ===================================================================
  function initMapAppTriggers() {
    if (PAGE !== "map-app.html") return;
    if (isPreviewEmbed()) return; // geen taak-triggers in iframe-preview
    const planBtn = document.getElementById("planRouteBtn");
    const grid = document.getElementById("comparisonGrid");
    if (!planBtn || !grid) return;

    let routePlanned = false;
    let t2Fired = false;
    planBtn.addEventListener("click", () => {
      routePlanned = true;
      send({ actie: "route_gepland", element: "planRouteBtn" });
    });

    // We loggen wel dat de vergelijking verschenen is (handig voor de
    // admin-flowchart), maar voltooien geen taak meer automatisch.
    let t2Logged = false;
    const t2Observer = new MutationObserver(() => {
      if (!routePlanned || t2Logged) return;
      if (grid.children && grid.children.length > 0) {
        t2Logged = true;
        send({ actie: "vergelijking_zichtbaar", element: "comparisonGrid" });
      }
    });
    t2Observer.observe(grid, { childList: true, subtree: true });

    // ——— Modus-selectie (geluidsringen-feature) ———
    // Loggen wat de tester selecteert, geen auto-completion.
    let lastSelectedLabel = null;

    function readSelectedLabel() {
      const sel = grid.querySelector(".mode-card.selected");
      if (!sel) return null;
      const titles = sel.querySelectorAll(".impact-title");
      const label =
        (titles[1] && titles[1].textContent) ||
        (titles[0] && titles[0].textContent) ||
        sel.textContent ||
        "onbekend";
      return label.trim().replace(/\s+/g, " ").slice(0, 80);
    }

    const selectionObserver = new MutationObserver(() => {
      const current = readSelectedLabel();
      if (current && current !== lastSelectedLabel) {
        send({ actie: "modus_geselecteerd", element: current });
        lastSelectedLabel = current;
      } else if (!current && lastSelectedLabel) {
        send({ actie: "modus_gedeselecteerd", element: lastSelectedLabel });
        lastSelectedLabel = null;
      }
    });
    selectionObserver.observe(grid, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["class"],
    });
  }

  function initGevolgenTriggers() {
    if (PAGE !== "gevolgen.html") return;
    let geluidEl = null;
    document.querySelectorAll(".gevolgen-columns h3").forEach((h) => {
      if (
        h.textContent &&
        h.textContent.trim().toLowerCase().startsWith("geluid")
      ) {
        geluidEl = h.parentElement;
      }
    });
    if (!geluidEl || !("IntersectionObserver" in window)) return;

    // Loggen dat de geluidssectie in beeld is, geen auto-completion.
    let logged = false;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (
            !logged &&
            entry.isIntersecting &&
            entry.intersectionRatio >= 0.5
          ) {
            logged = true;
            send({ actie: "geluidssectie_zichtbaar", element: "gevolgen-geluid" });
            io.disconnect();
          }
        });
      },
      { threshold: [0, 0.5, 1] }
    );
    io.observe(geluidEl);
  }

  function initStemTriggers() {
    if (PAGE !== "je-stem.html") return;
    const form = document.getElementById("stemForm");
    if (!form) return;
    form.addEventListener(
      "submit",
      () => {
        send({ actie: "stem_verzonden", element: "stemForm" });
      },
      false
    );
  }

  // ===================================================================
  // INIT
  // ===================================================================
  function init() {
    if (ADMIN_PREVIEW) return; // geen UI-extra's in admin-preview
    // mountFeedbackButton(); // verwijderd in iteratie 2 (aanpassing 3): voorkomt verwarring met taak-popups
    renderTaskBanner();
    initMapAppTriggers();
    initGevolgenTriggers();
    initStemTriggers();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
