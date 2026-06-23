<?php
/**
 * Diagnostisch script — verwijderen na gebruik!
 * Toont WAAR het misgaat met de DB-verbinding zonder het echte
 * wachtwoord aan de bezoeker te tonen.
 */

header('Content-Type: text/plain; charset=utf-8');

echo "=== DB-verbindings-diagnose ===\n\n";

// 1) Lees config.php in
define('EHC_TRACKER_ENTRY', true);
$configPath = __DIR__ . '/config.php';
if (!file_exists($configPath)) {
    echo "FOUT: config.php niet gevonden op {$configPath}\n";
    exit;
}
$cfg = require $configPath;
if (!is_array($cfg)) {
    echo "FOUT: config.php geeft geen array terug. Inhoud:\n";
    var_dump($cfg);
    exit;
}

echo "config.php geladen.\n";
echo "  db_host          : " . ($cfg['db_host'] ?? '<<ONTBREEKT>>') . "\n";
echo "  db_name          : " . ($cfg['db_name'] ?? '<<ONTBREEKT>>') . "\n";
echo "  db_user          : " . ($cfg['db_user'] ?? '<<ONTBREEKT>>') . "\n";
echo "  db_pass lengte   : " . (isset($cfg['db_pass']) ? strlen($cfg['db_pass']) : '<<ONTBREEKT>>') . " tekens\n";
echo "  db_pass eerste 2 : " . (isset($cfg['db_pass']) ? substr($cfg['db_pass'], 0, 2) : '<<ONTBREEKT>>') . "...\n";
echo "  db_pass laatste 2: " . (isset($cfg['db_pass']) ? '...' . substr($cfg['db_pass'], -2) : '<<ONTBREEKT>>') . "\n";
echo "  db_pass bevat tab/spatie/nieuwe regel? : " .
    (isset($cfg['db_pass']) && preg_match('/[\s]/', $cfg['db_pass']) ? "JA (probleem!)" : "Nee") . "\n";
echo "\n";

// 2) Probeer te verbinden
echo "=== Connectiepoging ===\n";
try {
    $dsn = sprintf('mysql:host=%s;dbname=%s;charset=%s',
        $cfg['db_host'], $cfg['db_name'], $cfg['db_charset'] ?? 'utf8mb4'
    );
    $pdo = new PDO($dsn, $cfg['db_user'], $cfg['db_pass'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
    ]);
    echo "VERBINDING GELUKT.\n\n";

    // 3) Tel rijen in interacties-tabel
    $aantal = $pdo->query("SELECT COUNT(*) FROM interacties")->fetchColumn();
    echo "Rijen in 'interacties': {$aantal}\n";

    echo "\n=> Alles werkt. Verwijder nu dbtest.php weer (veiligheid)!\n";
} catch (Throwable $e) {
    echo "CONNECTIE MISLUKT.\n";
    echo "Foutmelding: " . $e->getMessage() . "\n";
    echo "\nMogelijke oorzaken:\n";
    echo "  - db_pass in config.php komt niet overeen met MySQL-wachtwoord\n";
    echo "  - db_user typo (controleer hoofd/kleine letters)\n";
    echo "  - Gebruiker bestaat niet meer in MySQL (re-create in Plesk)\n";
}
