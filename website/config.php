<?php
/**
 * Database-instellingen voor de alfatest-tracking.
 *
 * Vul de waardes hieronder in via je Plesk-paneel:
 *   Databases  ->  Selecteer database  ->  Verbindingsgegevens.
 *
 * Tip: zet dit bestand bij voorkeur BUITEN de publieke webroot,
 * of bescherm het via een .htaccess regel. Werkt dat niet binnen jouw
 * Plesk-omgeving, dan voorkomt de "if (!defined ...)" guard hieronder
 * dat de inhoud per ongeluk uitvoerbaar blijft als iemand het bestand
 * rechtstreeks opvraagt.
 */

if (!defined('EHC_TRACKER_ENTRY')) {
    http_response_code(403);
    exit('Forbidden');
}

return [
    // Databasegegevens (Plesk -> Databases -> Verbindingsgegevens)
	'db_host'        => 'localhost',
	'db_name'        => 'h_0009f7bb_tp1',
	'db_user'        => 'h_0009f7bb_tp1user',
	'db_pass'        => 'tp1test2026',
	'db_charset'     => 'utf8mb4',

    // Wachtwoord voor admin.php
    'admin_password' => 'tp1test2026',

    // Mag het tracker-endpoint vanaf elke origin worden aangeroepen?
    // Voor lokaal testen op file:// staat dit standaard op '*'.
    // In productie kun je dit beperken tot bv. 'https://jouwdomein.nl'.
    'allow_origin' => '*',
];
