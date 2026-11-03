-- mod-playerbots name tables that live in acore_characters (old MariaDB dump), converted for MySQL 8.4.
-- Absent from the new acore_characters: the module normally creates them on first start.
SET NAMES utf8mb4;
CREATE TABLE IF NOT EXISTS `playerbots_arena_team_names` (
  `name_id` mediumint NOT NULL AUTO_INCREMENT,
  `name` varchar(24) NOT NULL,
  `type` tinyint NOT NULL,
  PRIMARY KEY (`name_id`),
  UNIQUE KEY `name_id` (`name_id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Playerbot arena team names';
CREATE TABLE IF NOT EXISTS `playerbots_guild_names` (
  `name_id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(24) NOT NULL,
  PRIMARY KEY (`name_id`),
  UNIQUE KEY `name_id` (`name_id`),
  UNIQUE KEY `name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Playerbot guild names';
CREATE TABLE IF NOT EXISTS `playerbots_names` (
  `name_id` int NOT NULL,
  `name` varchar(12) DEFAULT NULL,
  `gender` tinyint unsigned NOT NULL,
  `in_use` bit(1) DEFAULT b'0',
  PRIMARY KEY (`name_id`),
  UNIQUE KEY `name_id` (`name_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Playerbot RandomBot names';
