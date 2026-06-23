<?php
/**
 * Tracker endpoint voor de alfatest van "De Tastbare Transitie".
 *
 * Verwacht een POST met JSON-body of formdata. Velden:
 *   - sessie_id      (string, UUID die in de browser is gegenereerd)
 *   - pagina         (string, bv. "gevolgen.html")
 *   - actie          (string, bv. "klik", "pageview", "feedback")
 *   - element        (string, optioneel, bv. "btn-primary#tryMapBtn")
 *   - tijdstip       (ISO-string, optioneel — anders server-tijd)
 *   - feedback_tekst (string, optioneel)
 *   - feedback_score (integer 1-5, optioneel)
 *
 * Stuurt JSON terug: {"ok": true} of {"ok": false, "error": "..."}.
 */

define('EHC_TRACKER_ENTRY', true);
$config = require __DIR__ . '/config.php';

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

if (!empty($config['allow_origin'])) {
    header('Access-Control-Allow-Origin: ' . $config['allow_origin']);
    header('Access-Control-Allow-Methods: POST, OPTIONS');
    header('Access-Control-Allow-Headers: Content-Type');
}

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['ok' => false, 'error' => 'Methode niet toegestaan']);
    exit;
}

// Lees body — eerst JSON, anders formdata.
$raw = file_get_contents('php://input');
$data = null;
if ($raw !== '' && $raw !== false) {
    $decoded = json_decode($raw, true);
    if (is_array($decoded)) {
        $data = $decoded;
    }
}
if ($data === null) {
    $data = $_POST;
}

function clean_string($value, $maxLength = 1000) {
    if ($value === null) return null;
    $s = trim((string)$value);
    if ($s === '') return null;
    if (function_exists('mb_substr')) {
        return mb_substr($s, 0, $maxLength);
    }
    return substr($s, 0, $maxLength);
}

$sessie_id = clean_string($data['sessie_id'] ?? null, 64);
$pagina    = clean_string($data['pagina'] ?? null, 191);
$actie     = clean_string($data['actie'] ?? null, 64);
$element   = clean_string($data['element'] ?? null, 500);
$feedback_tekst = clean_string($data['feedback_tekst'] ?? null, 2000);

$feedback_score = $data['feedback_score'] ?? null;
if ($feedback_score !== null && $feedback_score !== '') {
    $feedback_score = (int)$feedback_score;
    if ($feedback_score < 1 || $feedback_score > 5) {
        $feedback_score = null;
    }
} else {
    $feedback_score = null;
}

$tijdstip_raw = clean_string($data['tijdstip'] ?? null, 40);
if ($tijdstip_raw) {
    $ts = strtotime($tijdstip_raw);
    $tijdstip = $ts ? date('Y-m-d H:i:s', $ts) : date('Y-m-d H:i:s');
} else {
    $tijdstip = date('Y-m-d H:i:s');
}

if (!$sessie_id || !$pagina || !$actie) {
    http_response_code(400);
    echo json_encode([
        'ok' => false,
        'error' => 'Verplichte velden ontbreken (sessie_id, pagina, actie).',
    ]);
    exit;
}

try {
    $dsn = sprintf(
        'mysql:host=%s;dbname=%s;charset=%s',
        $config['db_host'],
        $config['db_name'],
        $config['db_charset']
    );
    $pdo = new PDO($dsn, $config['db_user'], $config['db_pass'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
    ]);

    $stmt = $pdo->prepare(
        'INSERT INTO interacties
           (sessie_id, pagina, actie, element, tijdstip, feedback_tekst, feedback_score)
         VALUES
           (:sessie_id, :pagina, :actie, :element, :tijdstip, :feedback_tekst, :feedback_score)'
    );
    $stmt->execute([
        ':sessie_id'      => $sessie_id,
        ':pagina'         => $pagina,
        ':actie'          => $actie,
        ':element'        => $element,
        ':tijdstip'       => $tijdstip,
        ':feedback_tekst' => $feedback_tekst,
        ':feedback_score' => $feedback_score,
    ]);

    echo json_encode(['ok' => true, 'id' => (int)$pdo->lastInsertId()]);
} catch (Throwable $e) {
    http_response_code(500);
    error_log('tracker.php fout: ' . $e->getMessage());
    echo json_encode(['ok' => false, 'error' => 'Opslaan mislukt.']);
}
