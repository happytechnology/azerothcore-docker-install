/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.18-MariaDB
--
-- Host: localhost    Database: acore_auth
-- Synthetic fixture for tests/test_changed_tables.py. Not a real account dump.
-- Includes an escaped quote inside a string and an empty INSERT stub.
CREATE TABLE `account` (
  `id` int(10) unsigned NOT NULL AUTO_INCREMENT,
  `username` varchar(32) NOT NULL DEFAULT '',
  `salt` binary(32) NOT NULL, `verifier` binary(32) NOT NULL, `session_key` binary(40) DEFAULT NULL,
  `totp_secret` varbinary(128) DEFAULT NULL, `email` varchar(255) NOT NULL DEFAULT '', `reg_mail` varchar(255) NOT NULL DEFAULT '',
  `joindate` timestamp NOT NULL DEFAULT current_timestamp(), `last_ip` varchar(15) NOT NULL DEFAULT '127.0.0.1',
  `last_attempt_ip` varchar(15) NOT NULL DEFAULT '127.0.0.1', `failed_logins` int(10) unsigned NOT NULL DEFAULT 0,
  `locked` tinyint(3) unsigned NOT NULL DEFAULT 0, `lock_country` varchar(2) NOT NULL DEFAULT '00',
  `last_login` timestamp NULL DEFAULT NULL, `online` int(10) unsigned NOT NULL DEFAULT 0,
  `expansion` tinyint(3) unsigned NOT NULL DEFAULT 2, `mutetime` bigint(20) NOT NULL DEFAULT 0,
  `mutereason` varchar(255) NOT NULL DEFAULT '', `muteby` varchar(50) NOT NULL DEFAULT '',
  `locale` tinyint(3) unsigned NOT NULL DEFAULT 0, `os` varchar(3) NOT NULL DEFAULT '',
  `recruiter` int(10) unsigned NOT NULL DEFAULT 0, `totaltime` int(10) unsigned NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
LOCK TABLES `account` WRITE;
/*!40000 ALTER TABLE `account` DISABLE KEYS */;
INSERT INTO `account` VALUES (1,'OLI',0x01,0x02,NULL,NULL,'a@b','a@b','2020-01-01 00:00:00','1.2.3.4','1.2.3.4',0,0,'00',NULL,0,2,0,'it''s; (x)','',3,'Win',0,100),(2,'BOT',0x03,0x04,NULL,NULL,'','','2020-01-01 00:00:00','127.0.0.1','127.0.0.1',0,0,'00',NULL,0,2,0,'','',8,'',0,0);
INSERT INTO `account` VALUES ;
UNLOCK TABLES;
CREATE TABLE `uptime` (`realmid` int(10) unsigned NOT NULL, `starttime` int(10) unsigned NOT NULL DEFAULT 0, `uptime` int(10) unsigned NOT NULL DEFAULT 0, `maxplayers` smallint(5) unsigned NOT NULL DEFAULT 0, `revision` varchar(255) NOT NULL DEFAULT 'AzerothCore', PRIMARY KEY (`realmid`,`starttime`)) ENGINE=InnoDB;
INSERT INTO `uptime` VALUES (1,1600000000,3600,12,'AzerothCore rev. abc');
CREATE TABLE `motd` (`realmid` int(11) NOT NULL, `text` longtext DEFAULT 'TESTING123', PRIMARY KEY (`realmid`));
INSERT INTO `motd` VALUES (1,'Welcome');
