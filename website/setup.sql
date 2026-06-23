-- ----------------------------------------------------------------------
-- Tabelopzet voor de alfatest van "De Tastbare Transitie".
-- Importeer dit bestand via Plesk -> Databases -> phpMyAdmin -> Importeren,
-- of voer het uit met een MySQL-client.
-- ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `interacties` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `sessie_id`      VARCHAR(64)     NOT NULL,
  `pagina`         VARCHAR(191)    NOT NULL,
  `actie`          VARCHAR(64)     NOT NULL,
  `element`        VARCHAR(500)        NULL,
  `tijdstip`       DATETIME        NOT NULL,
  `feedback_tekst` TEXT                NULL,
  `feedback_score` TINYINT UNSIGNED    NULL,
  `aangemaakt_op`  TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_sessie`    (`sessie_id`),
  KEY `idx_pagina`    (`pagina`),
  KEY `idx_actie`     (`actie`),
  KEY `idx_tijdstip`  (`tijdstip`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
