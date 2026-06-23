<?php
/**
 * admin.php : eenvoudig dashboard voor de alfatest.
 * Wachtwoord staat in config.php (sleutel 'admin_password').
 *
 * Functionaliteit:
 *   - Loginformulier met session-cookie.
 *   - Overzicht: totaal sessies, populairste pagina's en elementen,
 *     gemiddelde feedbackscores per taak.
 *   - Sessielijst met klik-door naar individuele sessie.
 *   - Detailpagina per sessie: chronologische flowchart van events.
 *   - CSV-export van alle interacties (?export=csv).
 */

define('EHC_TRACKER_ENTRY', true);
$config = require __DIR__ . '/config.php';

session_start();

// ——— Login-flow —————————————————————————————————————————————
if (isset($_POST['logout'])) {
    $_SESSION = [];
    session_destroy();
    header('Location: admin.php');
    exit;
}

if (isset($_POST['admin_password'])) {
    if (hash_equals((string)$config['admin_password'], (string)$_POST['admin_password'])) {
        $_SESSION['ehc_admin'] = true;
    } else {
        $loginError = 'Onjuist wachtwoord.';
    }
}

$loggedIn = !empty($_SESSION['ehc_admin']);

// ——— Sessie verwijderen ——————————————————————————————————————
// Alleen via POST + ingelogd + bevestigingsveld. Stuurt door naar het
// hoofd-dashboard met een flash-melding.
if ($loggedIn
    && isset($_POST['delete_session'])
    && isset($_POST['sessie_id'])
    && ($_POST['confirm'] ?? '') === '1'
) {
    $sid = (string)$_POST['sessie_id'];
    if ($sid !== '') {
        try {
            $pdo = getPdo($config);
            $stmt = $pdo->prepare('DELETE FROM interacties WHERE sessie_id = :sid');
            $stmt->execute([':sid' => $sid]);
            $_SESSION['flash'] = sprintf(
                'Sessie %s verwijderd (%d events gewist).',
                substr($sid, 0, 8), $stmt->rowCount()
            );
        } catch (Throwable $e) {
            $_SESSION['flash_error'] = 'Verwijderen mislukt: ' . $e->getMessage();
        }
        header('Location: admin.php');
        exit;
    }
}

// Flash-melding (1 keer tonen)
$flash = $_SESSION['flash'] ?? null;
$flashError = $_SESSION['flash_error'] ?? null;
unset($_SESSION['flash'], $_SESSION['flash_error']);

function htmlEsc($v) {
    return htmlspecialchars((string)$v, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function getPdo(array $config) {
    $dsn = sprintf(
        'mysql:host=%s;dbname=%s;charset=%s',
        $config['db_host'],
        $config['db_name'],
        $config['db_charset']
    );
    return new PDO($dsn, $config['db_user'], $config['db_pass'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);
}

function formatDuration($seconds) {
    $seconds = max(0, (int)$seconds);
    if ($seconds < 60) return $seconds . ' sec';
    $m = floor($seconds / 60);
    $s = $seconds % 60;
    if ($m < 60) return $m . ' min ' . str_pad((string)$s, 2, '0', STR_PAD_LEFT) . ' sec';
    $h = floor($m / 60);
    $m = $m % 60;
    return $h . ' uur ' . str_pad((string)$m, 2, '0', STR_PAD_LEFT) . ' min';
}

function shortSession($sessieId) {
    return substr((string)$sessieId, 0, 8);
}

/**
 * Splitst de coordinaat-suffix " @[x=NN y=NN vw=NN vh=NN sy=NN]" van het
 * element-veld. Returns [cleanElement, coordsOrNull].
 */
function splitCoords($element) {
    if (!is_string($element) || strpos($element, ' @[') === false) {
        return [$element, null];
    }
    $parts = explode(' @[', $element, 2);
    $clean = rtrim($parts[0]);
    $raw   = rtrim($parts[1], ']');
    $coords = [];
    foreach (explode(' ', $raw) as $token) {
        if (strpos($token, '=') === false) continue;
        [$k, $v] = explode('=', $token, 2);
        $coords[$k] = (int)$v;
    }
    if (!isset($coords['x'], $coords['y'])) return [$clean, null];
    return [$clean, $coords];
}

// ——— CSV-export ————————————————————————————————————————————
if ($loggedIn && isset($_GET['export']) && $_GET['export'] === 'csv') {
    try {
        $pdo = getPdo($config);
        $stmt = $pdo->query(
            'SELECT id, sessie_id, pagina, actie, element, tijdstip,
                    feedback_tekst, feedback_score, aangemaakt_op
             FROM interacties
             ORDER BY tijdstip ASC, id ASC'
        );
        header('Content-Type: text/csv; charset=utf-8');
        header('Content-Disposition: attachment; filename="alfatest-data-' . date('Ymd-His') . '.csv"');
        $out = fopen('php://output', 'w');
        // BOM zodat Excel UTF-8 herkent.
        fprintf($out, "\xEF\xBB\xBF");
        fputcsv($out, [
            'id', 'sessie_id', 'pagina', 'actie', 'element',
            'tijdstip', 'feedback_tekst', 'feedback_score', 'aangemaakt_op'
        ]);
        while ($row = $stmt->fetch()) {
            fputcsv($out, $row);
        }
        fclose($out);
        exit;
    } catch (Throwable $e) {
        http_response_code(500);
        echo 'Export mislukt: ' . htmlEsc($e->getMessage());
        exit;
    }
}

// ——— Routing ——————————————————————————————————————————————
$view = 'overview';
$selectedSession = null;
$selectedPage    = null;
if ($loggedIn && isset($_GET['heatmap'])) {
    $view = 'heatmap';
    $selectedPage = (string)$_GET['heatmap'];
    if (!empty($_GET['session'])) {
        $selectedSession = (string)$_GET['session'];
    }
} elseif ($loggedIn && !empty($_GET['session'])) {
    $selectedSession = (string)$_GET['session'];
    $view = 'session';
}

// ——— Stats ophalen ——————————————————————————————————————————
$stats = [
    'totaalSessies'   => 0,
    'totaalEvents'    => 0,
    'topPaginas'      => [],
    'topElementen'    => [],
    'taakScores'      => [],
    'algemeneScore'   => null,
    'sessies'         => [],
];
$sessionDetail = null;
$heatmap = null;
$dbError = null;

if ($loggedIn) {
    try {
        $pdo = getPdo($config);

        if ($view === 'overview') {
            $stats['totaalSessies'] = (int)$pdo->query(
                'SELECT COUNT(DISTINCT sessie_id) FROM interacties'
            )->fetchColumn();

            $stats['totaalEvents'] = (int)$pdo->query(
                'SELECT COUNT(*) FROM interacties'
            )->fetchColumn();

            $stats['topPaginas'] = $pdo->query(
                'SELECT pagina, COUNT(*) AS bezoeken,
                        COUNT(DISTINCT sessie_id) AS unieke_sessies
                 FROM interacties
                 WHERE actie = "pageview"
                 GROUP BY pagina
                 ORDER BY bezoeken DESC
                 LIMIT 15'
            )->fetchAll();

            // Klik-element bevat optioneel " @[x=.. y=..]"-suffix met coords.
            // Voor de aggregatie strippen we die, anders telt elk uniek
            // coordinaat als apart element en wordt de top onbruikbaar.
            $stats['topElementen'] = $pdo->query(
                'SELECT TRIM(SUBSTRING_INDEX(element, " @[", 1)) AS element,
                        COUNT(*) AS aantal
                 FROM interacties
                 WHERE actie = "klik" AND element IS NOT NULL AND element <> ""
                 GROUP BY TRIM(SUBSTRING_INDEX(element, " @[", 1))
                 ORDER BY aantal DESC
                 LIMIT 20'
            )->fetchAll();

            $stats['taakScores'] = $pdo->query(
                'SELECT element AS taak,
                        COUNT(*) AS aantal_reacties,
                        ROUND(AVG(feedback_score), 2) AS gemiddelde,
                        MIN(feedback_score) AS minimum,
                        MAX(feedback_score) AS maximum
                 FROM interacties
                 WHERE actie = "taak_feedback" AND feedback_score IS NOT NULL
                 GROUP BY element
                 ORDER BY element ASC'
            )->fetchAll();

            $row = $pdo->query(
                'SELECT COUNT(*) AS aantal,
                        ROUND(AVG(feedback_score), 2) AS gemiddelde
                 FROM interacties
                 WHERE actie = "feedback" AND feedback_score IS NOT NULL'
            )->fetch();
            $stats['algemeneScore'] = $row ?: null;

            // Sessielijst met aggregates per sessie.
            $stats['sessies'] = $pdo->query(
                'SELECT sessie_id,
                        MIN(tijdstip)  AS start_tijd,
                        MAX(tijdstip)  AS eind_tijd,
                        COUNT(*)       AS aantal_events,
                        COUNT(DISTINCT pagina) AS aantal_paginas,
                        SUM(CASE WHEN actie = "taak_voltooid" THEN 1 ELSE 0 END) AS voltooide_taken,
                        SUM(CASE WHEN actie = "feedback" THEN 1 ELSE 0 END) AS algemene_feedback,
                        ROUND(AVG(CASE WHEN actie = "taak_feedback" THEN feedback_score END), 1) AS gem_taak_score
                 FROM interacties
                 GROUP BY sessie_id
                 ORDER BY MAX(tijdstip) DESC
                 LIMIT 200'
            )->fetchAll();
        } elseif ($view === 'heatmap') {
            // Lijst van pagina's met aantal kliks (voor de picker).
            $heatmap = [
                'paginas'     => $pdo->query(
                    'SELECT pagina, COUNT(*) AS klikken,
                            COUNT(DISTINCT sessie_id) AS sessies
                     FROM interacties
                     WHERE actie = "klik" AND pagina IS NOT NULL
                     GROUP BY pagina
                     ORDER BY klikken DESC'
                )->fetchAll(),
                'page'        => $selectedPage,
                'sessie_id'   => $selectedSession,
                'sessies_op_pagina' => [],
                'clicks'      => [],
            ];

            if ($selectedPage) {
                // Alle sessies die ooit op deze pagina hebben geklikt
                // (voor de filter-dropdown).
                $stmt = $pdo->prepare(
                    'SELECT DISTINCT sessie_id
                     FROM interacties
                     WHERE actie = "klik" AND pagina = :p
                     ORDER BY sessie_id'
                );
                $stmt->execute([':p' => $selectedPage]);
                $heatmap['sessies_op_pagina'] = $stmt->fetchAll(PDO::FETCH_COLUMN);

                // Alle klikken op de pagina, optioneel gefilterd op sessie.
                if ($selectedSession) {
                    $stmt = $pdo->prepare(
                        'SELECT sessie_id, element, tijdstip
                         FROM interacties
                         WHERE actie = "klik" AND pagina = :p AND sessie_id = :s
                         ORDER BY tijdstip ASC'
                    );
                    $stmt->execute([':p' => $selectedPage, ':s' => $selectedSession]);
                } else {
                    $stmt = $pdo->prepare(
                        'SELECT sessie_id, element, tijdstip
                         FROM interacties
                         WHERE actie = "klik" AND pagina = :p
                         ORDER BY tijdstip ASC'
                    );
                    $stmt->execute([':p' => $selectedPage]);
                }
                $raw = $stmt->fetchAll();

                // Parse coordinaten uit het element-veld.
                foreach ($raw as $r) {
                    [$cleanEl, $coords] = splitCoords($r['element']);
                    if (!$coords) continue;
                    $heatmap['clicks'][] = [
                        'sessie_id' => $r['sessie_id'],
                        'element'   => $cleanEl,
                        'tijdstip'  => $r['tijdstip'],
                        'x'         => $coords['x'],
                        'y'         => $coords['y'] + ($coords['sy'] ?? 0),
                        'vw'        => $coords['vw'] ?? 1280,
                        'vh'        => $coords['vh'] ?? 720,
                    ];
                }
            }
        } elseif ($view === 'session' && $selectedSession) {
            $stmt = $pdo->prepare(
                'SELECT id, pagina, actie, element, tijdstip,
                        feedback_tekst, feedback_score
                 FROM interacties
                 WHERE sessie_id = :sid
                 ORDER BY tijdstip ASC, id ASC'
            );
            $stmt->execute([':sid' => $selectedSession]);
            $events = $stmt->fetchAll();

            if ($events) {
                $startTs = strtotime($events[0]['tijdstip']);
                $endTs   = strtotime($events[count($events) - 1]['tijdstip']);
                $sessionDetail = [
                    'sessie_id'     => $selectedSession,
                    'start'         => $events[0]['tijdstip'],
                    'eind'          => $events[count($events) - 1]['tijdstip'],
                    'duur'          => $endTs - $startTs,
                    'aantal_events' => count($events),
                    'events'        => $events,
                    'start_ts'      => $startTs,
                ];
            } else {
                $sessionDetail = [
                    'sessie_id' => $selectedSession,
                    'events'    => [],
                ];
            }
        }
    } catch (Throwable $e) {
        $dbError = $e->getMessage();
    }
}

// ——— Helpers voor de flowchart ——————————————————————————————

// Welke actie-typen krijgen welk kleur-accent in de timeline?
$ACTIE_COLOR = [
    'pageview'               => 'page',
    'klik'                   => 'click',
    'taak_handmatig_voltooid' => 'task',
    'taak_voltooid'          => 'task',
    'taak_feedback'          => 'task',
    'feedback'               => 'feedback',
    'feedback_geopend'       => 'feedback',
    'feedback_marker_geplaatst' => 'feedback',
    'feedback_marker_overgeslagen' => 'feedback',
    'feedback_geannuleerd'   => 'feedback',
    'alfatest_start'         => 'milestone',
    'alfatest_voltooid'      => 'milestone',
    'vragenlijst_antwoord'   => 'questionnaire',
    'vragenlijst_voltooid'   => 'milestone',
    'stem_verzonden'         => 'milestone',
    'route_gepland'          => 'action',
    'modus_geselecteerd'     => 'action',
    'modus_gedeselecteerd'   => 'action',
    'vergelijking_zichtbaar' => 'action',
    'geluidssectie_zichtbaar' => 'action',
    'geluidsringen_zichtbaar' => 'action',
];

function actieKleur(string $actie, array $map): string {
    return $map[$actie] ?? 'default';
}

function leesbareActie(string $actie): string {
    $vertaling = [
        'pageview'                    => 'Pagina bezocht',
        'klik'                        => 'Klik',
        'taak_handmatig_voltooid'     => 'Taakbanner aangetikt',
        'taak_voltooid'               => 'Taak voltooid',
        'taak_feedback'               => 'Taak-feedback verstuurd',
        'taak_afronden_afgebroken'    => 'Taak-popup afgebroken',
        'feedback'                    => 'Algemene feedback',
        'feedback_geopend'            => 'Feedback-popup geopend',
        'feedback_marker_geplaatst'   => 'Marker geplaatst',
        'feedback_marker_overgeslagen'=> 'Marker overgeslagen',
        'feedback_geannuleerd'        => 'Feedback geannuleerd',
        'alfatest_start'              => 'Alfatest gestart',
        'alfatest_voltooid'           => 'Alle taken voltooid',
        'vragenlijst_antwoord'        => 'Vragenlijst antwoord',
        'vragenlijst_voltooid'        => 'Vragenlijst verstuurd',
        'stem_verzonden'              => 'Stem verstuurd',
        'route_gepland'               => 'Route gepland (kaart)',
        'modus_geselecteerd'          => 'Modus geselecteerd',
        'modus_gedeselecteerd'        => 'Modus gedeselecteerd',
        'vergelijking_zichtbaar'      => 'Vergelijking verschenen',
        'geluidssectie_zichtbaar'     => 'Geluidssectie in beeld',
        'geluidsringen_zichtbaar'     => 'dB-ringen in beeld',
    ];
    return $vertaling[$actie] ?? $actie;
}

?>
<!doctype html>
<html lang="nl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Alfatest dashboard | EHC</title>
  <link rel="stylesheet" href="./site.css" />
  <link rel="stylesheet" href="./tracking.css" />
  <style>
    .admin-shell { max-width: 1180px; margin: 0 auto; padding: 32px 16px 80px; }
    .admin-grid { display: grid; gap: 18px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-bottom: 24px; }
    .admin-card { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 20px; padding: 18px 20px; }
    .admin-card h3 { margin: 0 0 6px; font-size: 13pt; opacity: 0.9; }
    .admin-card .big { font-size: 28pt; font-weight: 700; }
    table.admin-table { width: 100%; border-collapse: collapse; margin: 10px 0 30px; font-size: 13pt; }
    table.admin-table th, table.admin-table td { text-align: left; padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.1); }
    table.admin-table th { font-weight: 700; opacity: 0.85; }
    table.admin-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
    table.admin-table tr.clickable:hover { background: rgba(255,255,255,0.04); cursor: pointer; }
    table.admin-table a { color: #ff7a3d; text-decoration: none; }
    table.admin-table a:hover { text-decoration: underline; }
    .admin-actions { display: flex; gap: 12px; flex-wrap: wrap; margin: 0 0 24px; }
    .admin-login { max-width: 380px; margin: 80px auto; background: rgba(255,255,255,0.06); padding: 24px; border-radius: 20px; }
    .admin-login input[type="password"] { width: 100%; padding: 10px 12px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.05); color: #fff; font-family: inherit; font-size: 13pt; margin-bottom: 14px; }
    .admin-login .error { color: #ffb39a; margin: 0 0 12px; }
    .admin-footer { font-size: 11pt; opacity: 0.6; margin-top: 40px; }
    .badge { display: inline-block; background: rgba(255,255,255,0.1); padding: 2px 10px; border-radius: 999px; font-size: 11pt; margin-left: 6px; }
    .back-link-btn { display: inline-flex; align-items: center; gap: 6px; font-size: 13pt; color: #ff7a3d; text-decoration: none; margin-bottom: 14px; }
    .back-link-btn:hover { text-decoration: underline; }

    /* ——— Sessielijst ——— */
    .sessie-row a { font-weight: 600; }
    .sessie-meta { font-size: 11pt; opacity: 0.7; }

    /* ——— Flowchart / timeline ——— */
    .flow-meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 28px; }
    .flow-meta .admin-card { padding: 14px 16px; }
    .flow-meta .admin-card h3 { font-size: 11pt; opacity: 0.7; }
    .flow-meta .admin-card .val { font-size: 16pt; font-weight: 700; margin-top: 2px; word-break: break-all; }

    .flow {
      position: relative;
      margin: 0;
      padding: 0 0 20px 0;
    }
    .flow::before {
      content: "";
      position: absolute;
      left: 90px;
      top: 0;
      bottom: 0;
      width: 2px;
      background: rgba(255,255,255,0.12);
    }
    .flow-step {
      position: relative;
      display: grid;
      grid-template-columns: 80px 22px 1fr;
      gap: 10px;
      align-items: flex-start;
      padding: 6px 0;
    }
    .flow-time {
      font-variant-numeric: tabular-nums;
      font-size: 11pt;
      opacity: 0.7;
      padding-top: 14px;
      text-align: right;
      white-space: nowrap;
    }
    .flow-dot {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      margin: 18px auto 0;
      background: #888;
      border: 3px solid #2a0d04;
      box-shadow: 0 0 0 1px rgba(255,255,255,0.15);
      position: relative;
      z-index: 2;
    }
    .flow-step.color-page    .flow-dot { background: #3da9fc; }
    .flow-step.color-click   .flow-dot { background: #d8d8d8; }
    .flow-step.color-task    .flow-dot { background: #ff7a3d; }
    .flow-step.color-feedback .flow-dot { background: #f7c548; }
    .flow-step.color-milestone .flow-dot { background: #6cd97e; width: 18px; height: 18px; margin-top: 16px; }
    .flow-step.color-questionnaire .flow-dot { background: #c98bdb; }
    .flow-step.color-action  .flow-dot { background: #5dd6c2; }

    .flow-card {
      background: rgba(255,255,255,0.05);
      border: 1px solid rgba(255,255,255,0.08);
      border-radius: 12px;
      padding: 10px 14px;
      margin: 6px 0;
    }
    .flow-card .head {
      display: flex;
      align-items: baseline;
      gap: 10px;
      flex-wrap: wrap;
    }
    .flow-card .actie {
      font-weight: 700;
      font-size: 13pt;
    }
    .flow-card .pagina {
      font-size: 11pt;
      opacity: 0.75;
      background: rgba(255,255,255,0.07);
      padding: 2px 8px;
      border-radius: 999px;
    }
    .flow-card .element {
      margin-top: 4px;
      font-size: 11.5pt;
      opacity: 0.85;
      word-break: break-word;
    }
    .flow-card .feedback {
      margin-top: 6px;
      padding: 6px 10px;
      background: rgba(255,122,61,0.12);
      border-left: 3px solid #ff7a3d;
      border-radius: 6px;
      font-size: 11.5pt;
    }
    .flow-card .feedback .stars {
      color: #f7c548;
      letter-spacing: 1px;
      margin-right: 8px;
    }
    .flow-legend {
      display: flex;
      gap: 14px;
      flex-wrap: wrap;
      margin: 0 0 18px;
      font-size: 11pt;
      opacity: 0.8;
    }
    .flow-legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .flow-legend i {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
    }

    /* Delta-tijd onder absolute tijd */
    .flow-delta {
      font-size: 9.5pt;
      opacity: 0.5;
      margin-top: 2px;
    }

    /* Inactiviteits-gap tussen events */
    .flow-gap {
      display: grid;
      grid-template-columns: 80px 22px 1fr;
      gap: 10px;
      padding: 4px 0;
    }
    .flow-gap span {
      grid-column: 3;
      font-size: 10.5pt;
      opacity: 0.45;
      font-style: italic;
      padding: 2px 0 2px 4px;
    }

    /* Hotzone dots over de iframe */
    .hot-dot {
      position: absolute;
      width: 18px;
      height: 18px;
      margin: -9px 0 0 -9px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255,88,35,0.85) 0%, rgba(255,88,35,0.4) 60%, rgba(255,88,35,0) 100%);
      mix-blend-mode: multiply;
      pointer-events: auto;
      cursor: help;
    }
    .hot-dot:hover {
      background: radial-gradient(circle, rgba(255,255,0,0.9) 0%, rgba(255,200,0,0.5) 70%, rgba(255,200,0,0) 100%);
      z-index: 10;
    }

    /* Heatmap-toggle en legenda */
    .hot-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: 0 0 16px;
      flex-wrap: wrap;
    }
    .hot-toggle-btn {
      background: rgba(255,255,255,0.08);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.18);
      border-radius: 999px;
      padding: 8px 16px;
      font-family: inherit;
      font-size: 11.5pt;
      cursor: pointer;
      font-weight: 600;
    }
    .hot-toggle-btn:hover { background: rgba(255,255,255,0.14); }
    .hot-toggle-btn.is-active {
      background: var(--ehc-orange, rgba(255,88,35,0.85));
      border-color: transparent;
    }
    .hot-radius {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
      font-size: 11.5pt;
      opacity: 0.85;
    }
    .hot-radius input[type="range"] { width: 140px; }
    .hot-legend {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      margin: 14px auto 0;
      font-size: 10.5pt;
      opacity: 0.85;
    }
    .hot-gradient {
      display: inline-block;
      width: 200px;
      height: 12px;
      border-radius: 6px;
      background: linear-gradient(
        90deg,
        rgb(0,0,180) 0%,
        rgb(0,120,240) 20%,
        rgb(0,220,200) 40%,
        rgb(120,240,0) 60%,
        rgb(255,200,0) 80%,
        rgb(255,40,0) 100%
      );
    }

    /* Delete-knop, klein (in tabel) */
    .btn-del {
      background: transparent;
      color: rgba(255,140,120,0.85);
      border: 1px solid rgba(255,140,120,0.35);
      width: 30px;
      height: 30px;
      border-radius: 50%;
      font-size: 16pt;
      line-height: 1;
      cursor: pointer;
      padding: 0;
    }
    .btn-del:hover {
      background: rgba(255,80,40,0.25);
      color: #fff;
      border-color: rgba(255,80,40,0.7);
    }

    /* Delete-knop, groot (op detail-pagina) */
    .btn-del-large {
      background: rgba(255,80,40,0.18);
      color: #ffb39a;
      border: 1px solid rgba(255,80,40,0.45);
      padding: 10px 22px;
      font-size: 13pt;
      font-weight: 600;
      border-radius: 999px;
      cursor: pointer;
      font-family: inherit;
    }
    .btn-del-large:hover {
      background: rgba(255,80,40,0.35);
      color: #fff;
      border-color: rgba(255,80,40,0.8);
    }
  </style>
</head>
<body>
<?php if (!$loggedIn): ?>
  <div class="admin-login">
    <h1 style="text-align:center; font-size:22pt;">Dashboard</h1>
    <p style="text-align:center; opacity:0.85;">Log in om de testdata te bekijken.</p>
    <?php if (!empty($loginError)): ?>
      <p class="error"><?= htmlEsc($loginError) ?></p>
    <?php endif; ?>
    <form method="post" autocomplete="off">
      <label for="adminpw" style="display:block; margin-bottom:6px;">Wachtwoord</label>
      <input id="adminpw" type="password" name="admin_password" required autofocus />
      <button class="btn-primary" type="submit" style="width:100%;">Inloggen</button>
    </form>
  </div>
<?php elseif ($view === 'session'): ?>
  <div class="admin-shell">
    <a class="back-link-btn" href="admin.php">&larr; Terug naar overzicht</a>
    <header style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <h1 style="margin:0;">Sessie <code style="font-size:18pt;"><?= htmlEsc(shortSession($selectedSession)) ?></code></h1>
      <div style="display:flex; gap:10px; align-items:center;">
        <form method="post" style="margin:0;"
              onsubmit="return confirm('Sessie <?= htmlEsc(shortSession($selectedSession)) ?> verwijderen?\nAlle events van deze tester worden definitief gewist.');">
          <input type="hidden" name="delete_session" value="1" />
          <input type="hidden" name="sessie_id" value="<?= htmlEsc($selectedSession) ?>" />
          <input type="hidden" name="confirm" value="1" />
          <button type="submit" class="btn-del-large">Sessie verwijderen</button>
        </form>
        <form method="post" style="margin:0;">
          <button class="btn-primary" type="submit" name="logout" value="1" style="padding:10px 22px; font-size:13pt;">Uitloggen</button>
        </form>
      </div>
    </header>

    <?php if ($dbError): ?>
      <p style="background:rgba(255,80,40,0.25); padding:12px 16px; border-radius:12px; margin-top:18px;">
        Databasefout: <?= htmlEsc($dbError) ?>
      </p>
    <?php elseif (empty($sessionDetail['events'])): ?>
      <p style="margin-top:24px; opacity:0.7;">Geen events gevonden voor deze sessie.</p>
    <?php else: ?>
      <section class="flow-meta">
        <div class="admin-card">
          <h3>Sessie-ID</h3>
          <div class="val"><?= htmlEsc($sessionDetail['sessie_id']) ?></div>
        </div>
        <div class="admin-card">
          <h3>Start</h3>
          <div class="val"><?= htmlEsc($sessionDetail['start']) ?></div>
        </div>
        <div class="admin-card">
          <h3>Eind</h3>
          <div class="val"><?= htmlEsc($sessionDetail['eind']) ?></div>
        </div>
        <div class="admin-card">
          <h3>Totale duur</h3>
          <div class="val"><?= htmlEsc(formatDuration($sessionDetail['duur'])) ?></div>
        </div>
        <div class="admin-card">
          <h3>Aantal events</h3>
          <div class="val"><?= htmlEsc($sessionDetail['aantal_events']) ?></div>
        </div>
      </section>

      <div class="flow-legend">
        <span><i style="background:#6cd97e"></i> Mijlpaal</span>
        <span><i style="background:#3da9fc"></i> Pagina</span>
        <span><i style="background:#d8d8d8"></i> Klik</span>
        <span><i style="background:#5dd6c2"></i> Actie</span>
        <span><i style="background:#ff7a3d"></i> Taak</span>
        <span><i style="background:#f7c548"></i> Feedback</span>
        <span><i style="background:#c98bdb"></i> Vragenlijst</span>
      </div>

      <?php
        // Unieke pagina's in deze sessie, voor de "bekijk hotzones"-links.
        $sessiePages = [];
        foreach ($sessionDetail['events'] as $ev) {
          if ($ev['pagina']) $sessiePages[$ev['pagina']] = true;
        }
        $sessiePages = array_keys($sessiePages);
      ?>
      <?php if ($sessiePages): ?>
        <p style="font-size:11.5pt; opacity:0.85; margin:0 0 16px;">
          Bekijk hotzones voor deze sessie:
          <?php foreach ($sessiePages as $sp): ?>
            <a class="badge" style="color:#ff7a3d; text-decoration:none;"
               href="admin.php?heatmap=<?= htmlEsc(urlencode($sp)) ?>&session=<?= htmlEsc(urlencode($selectedSession)) ?>">
              <?= htmlEsc($sp) ?>
            </a>
          <?php endforeach; ?>
        </p>
      <?php endif; ?>

      <div class="flow" role="list">
        <?php
          $prevTs = null;
          foreach ($sessionDetail['events'] as $ev):
            $ts = strtotime($ev['tijdstip']);
            $delta = $ts - $sessionDetail['start_ts'];
            $sinceLast = $prevTs === null ? null : ($ts - $prevTs);
            $prevTs = $ts;
            $kleur = actieKleur($ev['actie'], $ACTIE_COLOR);
            [$cleanElement, $clickCoords] = splitCoords($ev['element']);
        ?>
          <?php if ($sinceLast !== null && $sinceLast >= 3): ?>
            <div class="flow-gap" aria-hidden="true">
              <span><?= htmlEsc(formatDuration($sinceLast)) ?> tussenpauze</span>
            </div>
          <?php endif; ?>
          <div class="flow-step color-<?= htmlEsc($kleur) ?>" role="listitem">
            <div class="flow-time">
              +<?= htmlEsc(formatDuration($delta)) ?>
              <?php if ($sinceLast !== null && $sinceLast > 0): ?>
                <div class="flow-delta">+<?= htmlEsc(formatDuration($sinceLast)) ?></div>
              <?php endif; ?>
            </div>
            <div class="flow-dot" aria-hidden="true"></div>
            <div class="flow-card">
              <div class="head">
                <span class="actie"><?= htmlEsc(leesbareActie($ev['actie'])) ?></span>
                <?php if ($ev['pagina']): ?>
                  <span class="pagina"><?= htmlEsc($ev['pagina']) ?></span>
                <?php endif; ?>
              </div>
              <?php if ($cleanElement): ?>
                <div class="element"><?= htmlEsc($cleanElement) ?></div>
              <?php endif; ?>
              <?php if ($clickCoords): ?>
                <div class="element" style="opacity:0.6; font-size:10.5pt;">
                  klik op (<?= (int)$clickCoords['x'] ?>, <?= (int)$clickCoords['y'] ?>)
                  op viewport <?= (int)($clickCoords['vw'] ?? 0) ?>×<?= (int)($clickCoords['vh'] ?? 0) ?>
                </div>
              <?php endif; ?>
              <?php if ($ev['feedback_score'] !== null || $ev['feedback_tekst']): ?>
                <div class="feedback">
                  <?php if ($ev['feedback_score'] !== null):
                    $score = (int)$ev['feedback_score'];
                  ?>
                    <span class="stars">
                      <?= str_repeat('★', $score) . str_repeat('☆', 5 - $score) ?>
                    </span>
                    <strong><?= htmlEsc($score) ?>/5</strong>
                  <?php endif; ?>
                  <?php if ($ev['feedback_tekst']): ?>
                    <div style="margin-top:4px;">
                      <?= nl2br(htmlEsc($ev['feedback_tekst'])) ?>
                    </div>
                  <?php endif; ?>
                </div>
              <?php endif; ?>
            </div>
          </div>
        <?php endforeach; ?>
      </div>
    <?php endif; ?>
  </div>
<?php elseif ($view === 'heatmap'): ?>
  <div class="admin-shell" style="max-width: 1500px;">
    <a class="back-link-btn" href="admin.php">&larr; Terug naar overzicht</a>
    <header style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <h1 style="margin:0;">
        Hotzones
        <?php if ($heatmap && $heatmap['page']): ?>
          : <code style="font-size:18pt;"><?= htmlEsc($heatmap['page']) ?></code>
        <?php endif; ?>
      </h1>
      <form method="post" style="margin:0;">
        <button class="btn-primary" type="submit" name="logout" value="1" style="padding:10px 22px; font-size:13pt;">Uitloggen</button>
      </form>
    </header>

    <?php if ($dbError): ?>
      <p style="background:rgba(255,80,40,0.25); padding:12px 16px; border-radius:12px; margin-top:18px;">
        Databasefout: <?= htmlEsc($dbError) ?>
      </p>
    <?php endif; ?>

    <?php if (!$heatmap || !$heatmap['page']): ?>
      <p style="margin-top:18px; opacity:0.85;">Kies een pagina om de hotzones te bekijken.</p>
      <table class="admin-table" style="max-width:600px;">
        <thead><tr><th>Pagina</th><th class="num">Klikken</th><th class="num">Sessies</th></tr></thead>
        <tbody>
        <?php if (!$heatmap || !$heatmap['paginas']): ?>
          <tr><td colspan="3" style="opacity:0.7;">Nog geen klikdata.</td></tr>
        <?php else: foreach ($heatmap['paginas'] as $r): ?>
          <tr class="clickable"
              onclick="location.href='admin.php?heatmap=<?= htmlEsc(urlencode($r['pagina'])) ?>'">
            <td><a href="admin.php?heatmap=<?= htmlEsc(urlencode($r['pagina'])) ?>"><?= htmlEsc($r['pagina']) ?></a></td>
            <td class="num"><?= htmlEsc($r['klikken']) ?></td>
            <td class="num"><?= htmlEsc($r['sessies']) ?></td>
          </tr>
        <?php endforeach; endif; ?>
        </tbody>
      </table>
    <?php else: ?>
      <!-- Sessiefilter -->
      <form method="get" class="admin-actions" style="margin: 18px 0;">
        <input type="hidden" name="heatmap" value="<?= htmlEsc($heatmap['page']) ?>" />
        <label style="display:flex; align-items:center; gap:8px;">
          Filter op sessie:
          <select name="session"
                  style="padding:8px 12px; border-radius:10px; border:1px solid rgba(255,255,255,0.2); background:rgba(255,255,255,0.05); color:#fff; font-family:inherit;"
                  onchange="this.form.submit()">
            <option value="">Alle sessies (<?= count($heatmap['clicks']) ?> klikken)</option>
            <?php foreach ($heatmap['sessies_op_pagina'] as $sid): ?>
              <option value="<?= htmlEsc($sid) ?>"
                      <?= $sid === $heatmap['sessie_id'] ? 'selected' : '' ?>>
                <?= htmlEsc(shortSession($sid)) ?>
              </option>
            <?php endforeach; ?>
          </select>
        </label>
        <?php if ($heatmap['sessie_id']): ?>
          <a class="btn-primary" href="admin.php?heatmap=<?= htmlEsc(urlencode($heatmap['page'])) ?>"
             style="background:rgba(255,255,255,0.12);">Filter wissen</a>
        <?php endif; ?>
      </form>

      <p style="opacity:0.75; font-size:11.5pt; margin: 0 0 12px;">
        <?= count($heatmap['clicks']) ?> klikken weergegeven.
        Coordinaten zijn pagina-relatief en geschaald naar 1280 pixels breed.
        Een klik = een oranje punt; gestapelde klikken donkerder.
      </p>

      <?php
        // Vaste 16:9 verhouding. We schalen de iframe naar deze hoogte
        // en mappen klik-coordinaten naar dezelfde verhouding zodat de
        // visualisatie altijd hetzelfde formaat heeft, ongeacht hoe ver
        // testers gescrold hebben.
        $targetWidth  = 1280;
        $targetHeight = (int)round($targetWidth * 9 / 16); // = 720
        $maxY         = $targetHeight;

        $scaledClicks = [];
        foreach ($heatmap['clicks'] as $c) {
          $scale = $targetWidth / max(320, (int)$c['vw']);
          $sx = (int)round($c['x'] * $scale);
          $sy = (int)round($c['y'] * $scale);
          // Klikken die buiten het 16:9 frame vallen (laag op de pagina
          // na scrollen) worden naar de onderrand geclampt, zodat ze nog
          // wel zichtbaar zijn op de heatmap zonder het frame te rekken.
          if ($sy > $targetHeight - 4) $sy = $targetHeight - 4;
          $scaledClicks[] = [
            'x' => $sx, 'y' => $sy,
            'sessie' => $c['sessie_id'],
            'element' => $c['element'],
            'tijdstip' => $c['tijdstip'],
          ];
        }
      ?>

      <div class="hot-toggle" role="group" aria-label="Weergave kiezen">
        <button type="button" class="hot-toggle-btn is-active" data-mode="heat">Dichtheid</button>
        <button type="button" class="hot-toggle-btn" data-mode="dots">Losse klikken</button>
        <button type="button" class="hot-toggle-btn" data-mode="both">Beide</button>
        <label class="hot-radius">
          Radius
          <input type="range" id="hotRadius" min="20" max="120" value="55" />
          <span id="hotRadiusVal">55</span>px
        </label>
      </div>

      <div class="heatmap-wrap" style="position:relative; width:<?= $targetWidth ?>px; max-width:100%; margin: 0 auto; border-radius:12px; overflow:hidden; border:1px solid rgba(255,255,255,0.15);">
        <iframe
          id="heatmapFrame"
          src="<?= htmlEsc($heatmap['page']) ?>?admin=1"
          title="Preview van <?= htmlEsc($heatmap['page']) ?>"
          style="display:block; width:100%; height:<?= $maxY ?>px; border:0; background:#fff;"
        ></iframe>
        <canvas
          id="heatmapCanvas"
          width="<?= $targetWidth ?>"
          height="<?= $maxY ?>"
          style="position:absolute; inset:0; pointer-events:none; mix-blend-mode: multiply;"
        ></canvas>
        <div id="heatmapDots" style="position:absolute; inset:0; pointer-events:none; display:none;">
          <?php foreach ($scaledClicks as $c): ?>
            <span
              class="hot-dot"
              data-sessie="<?= htmlEsc($c['sessie']) ?>"
              data-element="<?= htmlEsc($c['element']) ?>"
              data-tijdstip="<?= htmlEsc($c['tijdstip']) ?>"
              style="left:<?= $c['x'] ?>px; top:<?= $c['y'] ?>px;"
              title="<?= htmlEsc($c['element']) ?> @ <?= htmlEsc($c['tijdstip']) ?>"
            ></span>
          <?php endforeach; ?>
        </div>
      </div>

      <div class="hot-legend" aria-hidden="true">
        <span>laag</span>
        <span class="hot-gradient"></span>
        <span>hoog</span>
      </div>

      <script>
        (function () {
          const frame   = document.getElementById("heatmapFrame");
          const canvas  = document.getElementById("heatmapCanvas");
          const dotsEl  = document.getElementById("heatmapDots");
          const targetWidth = <?= $targetWidth ?>;
          const clicks = <?= json_encode(array_map(function ($c) {
            return ['x' => (int)$c['x'], 'y' => (int)$c['y']];
          }, $scaledClicks)) ?>;

          let radius = parseInt(document.getElementById("hotRadius").value, 10);

          // ——— Canvas-grootte aanpassen aan iframe-hoogte ———
          function resizeCanvas() {
            const cssH = parseInt(frame.style.height, 10) || frame.offsetHeight;
            canvas.height = cssH;
            canvas.width = targetWidth;
            drawHeatmap();
          }

          // ——— Render: radiale gradients met "lighter" composition ———
          function drawHeatmap() {
            const ctx = canvas.getContext("2d");
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (!clicks.length) return;

            // Stap 1: teken grijswaarden-alpha met "lighter" zodat
            // overlappende klikken hun alpha optellen.
            ctx.globalCompositeOperation = "lighter";
            ctx.fillStyle = "rgba(0,0,0,1)"; // kleur wordt later vervangen
            clicks.forEach((c) => {
              const grad = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, radius);
              grad.addColorStop(0, "rgba(0,0,0,0.45)");
              grad.addColorStop(1, "rgba(0,0,0,0)");
              ctx.fillStyle = grad;
              ctx.fillRect(c.x - radius, c.y - radius, radius * 2, radius * 2);
            });

            // Stap 2: lees alpha, map naar jet-colormap (blue → red).
            ctx.globalCompositeOperation = "source-over";
            const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const data = img.data;
            for (let i = 0; i < data.length; i += 4) {
              const a = data[i + 3];
              if (a === 0) continue;
              const t = Math.min(1, a / 255);
              const [r, g, b] = jet(t);
              data[i] = r;
              data[i + 1] = g;
              data[i + 2] = b;
              data[i + 3] = Math.min(220, 60 + a); // licht transparant houden
            }
            ctx.putImageData(img, 0, 0);
          }

          // Jet colormap: 0 = blauw, 0.25 = cyaan, 0.5 = groen,
          // 0.75 = geel, 1.0 = rood.
          function jet(t) {
            const stops = [
              [0.00, [  0,   0, 180]],
              [0.20, [  0, 120, 240]],
              [0.40, [  0, 220, 200]],
              [0.60, [120, 240,   0]],
              [0.80, [255, 200,   0]],
              [1.00, [255,  40,   0]],
            ];
            for (let i = 0; i < stops.length - 1; i++) {
              const [t0, c0] = stops[i];
              const [t1, c1] = stops[i + 1];
              if (t >= t0 && t <= t1) {
                const k = (t - t0) / (t1 - t0);
                return [
                  Math.round(c0[0] + (c1[0] - c0[0]) * k),
                  Math.round(c0[1] + (c1[1] - c0[1]) * k),
                  Math.round(c0[2] + (c1[2] - c0[2]) * k),
                ];
              }
            }
            return [255, 40, 0];
          }

          // Iframe-hoogte staat vast op $maxY (de onderste klik-y), zodat
          // de preview niet onnodig doorgroeit naar pagina-content waar
          // toch geen klikken op vielen. We negeren de postMessage van
          // de iframe-pagina expres.

          // ——— Toggle dots / heatmap / beide ———
          document.querySelectorAll(".hot-toggle-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
              document.querySelectorAll(".hot-toggle-btn").forEach((b) =>
                b.classList.remove("is-active")
              );
              btn.classList.add("is-active");
              const mode = btn.dataset.mode;
              canvas.style.display = mode === "dots" ? "none" : "";
              dotsEl.style.display = mode === "dots" || mode === "both" ? "" : "none";
            });
          });

          // ——— Radius-slider ———
          const slider = document.getElementById("hotRadius");
          const sliderVal = document.getElementById("hotRadiusVal");
          slider.addEventListener("input", () => {
            radius = parseInt(slider.value, 10);
            sliderVal.textContent = radius;
            drawHeatmap();
          });

          // Eerste render
          drawHeatmap();
        })();
      </script>
    <?php endif; ?>
  </div>
<?php else: ?>
  <div class="admin-shell">
    <header style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
      <h1 style="margin:0;">Alfatest dashboard</h1>
      <form method="post" style="margin:0;">
        <button class="btn-primary" type="submit" name="logout" value="1" style="padding:10px 22px; font-size:13pt;">Uitloggen</button>
      </form>
    </header>

    <?php if ($dbError): ?>
      <p style="background:rgba(255,80,40,0.25); padding:12px 16px; border-radius:12px; margin-top:18px;">
        Databasefout: <?= htmlEsc($dbError) ?>
      </p>
    <?php endif; ?>

    <?php if (!empty($flash)): ?>
      <p style="background:rgba(108,217,126,0.18); border:1px solid rgba(108,217,126,0.45); padding:10px 16px; border-radius:12px; margin-top:18px;">
        <?= htmlEsc($flash) ?>
      </p>
    <?php endif; ?>
    <?php if (!empty($flashError)): ?>
      <p style="background:rgba(255,80,40,0.25); padding:10px 16px; border-radius:12px; margin-top:18px;">
        <?= htmlEsc($flashError) ?>
      </p>
    <?php endif; ?>

    <div class="admin-actions" style="margin-top:24px;">
      <a class="btn-primary" href="?export=csv">Download CSV</a>
      <a class="btn-primary" href="?heatmap=" style="background:rgba(255,255,255,0.12);">Hotzones</a>
      <a class="btn-primary" href="admin.php" style="background:rgba(255,255,255,0.12);">Ververs</a>
    </div>

    <section class="admin-grid">
      <div class="admin-card">
        <h3>Totaal aantal sessies</h3>
        <div class="big"><?= htmlEsc($stats['totaalSessies']) ?></div>
      </div>
      <div class="admin-card">
        <h3>Totaal aantal events</h3>
        <div class="big"><?= htmlEsc($stats['totaalEvents']) ?></div>
      </div>
      <div class="admin-card">
        <h3>Algemene feedback</h3>
        <?php $alg = $stats['algemeneScore']; ?>
        <div class="big">
          <?= $alg && $alg['gemiddelde'] !== null ? htmlEsc($alg['gemiddelde']) : '.' ?>
          <span class="badge"><?= $alg ? htmlEsc((int)$alg['aantal']) : 0 ?> reacties</span>
        </div>
      </div>
    </section>

    <h2>Sessies (klik op een rij voor de flowchart)</h2>
    <table class="admin-table">
      <thead>
        <tr>
          <th>Sessie</th>
          <th>Start</th>
          <th class="num">Duur</th>
          <th class="num">Events</th>
          <th class="num">Pagina's</th>
          <th class="num">Taken</th>
          <th class="num">Gem. taakscore</th>
          <th class="num">Feedback</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
      <?php if (!$stats['sessies']): ?>
        <tr><td colspan="9" style="opacity:0.7;">Nog geen sessies geregistreerd.</td></tr>
      <?php else: foreach ($stats['sessies'] as $s):
        $startTs = strtotime($s['start_tijd']);
        $eindTs  = strtotime($s['eind_tijd']);
        $duur    = $eindTs - $startTs;
        $href    = 'admin.php?session=' . urlencode($s['sessie_id']);
        $shortId = shortSession($s['sessie_id']);
      ?>
        <tr class="clickable sessie-row"
            onclick="if(event.target.closest('.del-form'))return; location.href='<?= htmlEsc($href) ?>'">
          <td><a href="<?= htmlEsc($href) ?>"><?= htmlEsc($shortId) ?></a></td>
          <td class="sessie-meta"><?= htmlEsc($s['start_tijd']) ?></td>
          <td class="num"><?= htmlEsc(formatDuration($duur)) ?></td>
          <td class="num"><?= htmlEsc($s['aantal_events']) ?></td>
          <td class="num"><?= htmlEsc($s['aantal_paginas']) ?></td>
          <td class="num"><?= htmlEsc((int)$s['voltooide_taken']) ?></td>
          <td class="num"><?= $s['gem_taak_score'] !== null ? htmlEsc($s['gem_taak_score']) : '.' ?></td>
          <td class="num"><?= htmlEsc((int)$s['algemene_feedback']) ?></td>
          <td>
            <form method="post" class="del-form" style="margin:0;"
                  onsubmit="return confirm('Sessie <?= htmlEsc($shortId) ?> verwijderen?\nDit wist <?= htmlEsc($s['aantal_events']) ?> events en kan niet ongedaan worden gemaakt.');">
              <input type="hidden" name="delete_session" value="1" />
              <input type="hidden" name="sessie_id" value="<?= htmlEsc($s['sessie_id']) ?>" />
              <input type="hidden" name="confirm" value="1" />
              <button type="submit" class="btn-del"
                      aria-label="Sessie verwijderen"
                      title="Sessie verwijderen">×</button>
            </form>
          </td>
        </tr>
      <?php endforeach; endif; ?>
      </tbody>
    </table>

    <h2>Meest bezochte pagina's</h2>
    <table class="admin-table">
      <thead>
        <tr><th>Pagina</th><th class="num">Pageviews</th><th class="num">Unieke sessies</th></tr>
      </thead>
      <tbody>
      <?php if (!$stats['topPaginas']): ?>
        <tr><td colspan="3" style="opacity:0.7;">Nog geen data.</td></tr>
      <?php else: foreach ($stats['topPaginas'] as $r): ?>
        <tr>
          <td><?= htmlEsc($r['pagina']) ?></td>
          <td class="num"><?= htmlEsc($r['bezoeken']) ?></td>
          <td class="num"><?= htmlEsc($r['unieke_sessies']) ?></td>
        </tr>
      <?php endforeach; endif; ?>
      </tbody>
    </table>

    <h2>Meest aangeklikte elementen</h2>
    <table class="admin-table">
      <thead>
        <tr><th>Element</th><th class="num">Klikken</th></tr>
      </thead>
      <tbody>
      <?php if (!$stats['topElementen']): ?>
        <tr><td colspan="2" style="opacity:0.7;">Nog geen data.</td></tr>
      <?php else: foreach ($stats['topElementen'] as $r): ?>
        <tr>
          <td><?= htmlEsc($r['element']) ?></td>
          <td class="num"><?= htmlEsc($r['aantal']) ?></td>
        </tr>
      <?php endforeach; endif; ?>
      </tbody>
    </table>

    <h2>Gemiddelde feedbackscores per taak</h2>
    <table class="admin-table">
      <thead>
        <tr>
          <th>Taak</th>
          <th class="num">Reacties</th>
          <th class="num">Gemiddelde</th>
          <th class="num">Min</th>
          <th class="num">Max</th>
        </tr>
      </thead>
      <tbody>
      <?php if (!$stats['taakScores']): ?>
        <tr><td colspan="5" style="opacity:0.7;">Nog geen taak-feedback ontvangen.</td></tr>
      <?php else: foreach ($stats['taakScores'] as $r): ?>
        <tr>
          <td><?= htmlEsc($r['taak']) ?></td>
          <td class="num"><?= htmlEsc($r['aantal_reacties']) ?></td>
          <td class="num"><?= htmlEsc($r['gemiddelde']) ?></td>
          <td class="num"><?= htmlEsc($r['minimum']) ?></td>
          <td class="num"><?= htmlEsc($r['maximum']) ?></td>
        </tr>
      <?php endforeach; endif; ?>
      </tbody>
    </table>

    <p class="admin-footer">
      Tip: maak na de testdag een back-up van de CSV en truncate eventueel
      de tabel <code>interacties</code> als je opnieuw begint.
    </p>
  </div>
<?php endif; ?>
</body>
</html>
