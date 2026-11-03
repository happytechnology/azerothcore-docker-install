-- Synthetic fixture for tests/test_changed_tables.py. Not a real character dump.
-- Host: localhost    Database: acore_characters
CREATE TABLE `bugreport` (`id` int(10) unsigned NOT NULL AUTO_INCREMENT, `type` longtext NOT NULL, `content` longtext NOT NULL, PRIMARY KEY (`id`));
INSERT INTO `bugreport` VALUES (1,'Bug','x, y; z');
CREATE TABLE `character_homebind` (`guid` int(10) unsigned NOT NULL DEFAULT 0,`mapId` smallint(5) unsigned NOT NULL DEFAULT 0,`zoneId` smallint(5) unsigned NOT NULL DEFAULT 0,`posX` float NOT NULL DEFAULT 0,`posY` float NOT NULL DEFAULT 0,`posZ` float NOT NULL DEFAULT 0,`posO` float NOT NULL DEFAULT 0, PRIMARY KEY (`guid`));
INSERT INTO `character_homebind` VALUES (5,0,12,-8949.95,-132.493,83.5312,0.5);
CREATE TABLE `mail_server_template` (`id` int(10) unsigned NOT NULL AUTO_INCREMENT,`reqLevel` tinyint(3) unsigned NOT NULL DEFAULT 0,`reqPlayTime` int(10) unsigned NOT NULL DEFAULT 0,`moneyA` int(10) unsigned NOT NULL DEFAULT 0,`moneyH` int(10) unsigned NOT NULL DEFAULT 0,`itemA` int(10) unsigned NOT NULL DEFAULT 0,`itemCountA` int(10) unsigned NOT NULL DEFAULT 0,`itemH` int(10) unsigned NOT NULL DEFAULT 0,`itemCountH` int(10) unsigned NOT NULL DEFAULT 0,`subject` text NOT NULL,`body` text NOT NULL,`active` tinyint(3) unsigned NOT NULL DEFAULT 1, PRIMARY KEY (`id`));
INSERT INTO `mail_server_template` VALUES (1,10,0,100,100,6948,1,6948,2,'Hi','Body',1),(2,0,3600000,0,0,0,0,0,0,'S','B',1);
CREATE TABLE `petition` (`ownerguid` int(10) unsigned NOT NULL,`petitionguid` int(10) unsigned DEFAULT 0,`name` varchar(24) NOT NULL,`type` tinyint(3) unsigned NOT NULL DEFAULT 0, PRIMARY KEY (`ownerguid`,`type`));
INSERT INTO `petition` VALUES (5,777,'Guild',9),(6,3000000000,'Big',2);
CREATE TABLE `petition_sign` (`ownerguid` int(10) unsigned NOT NULL,`petitionguid` int(10) unsigned NOT NULL DEFAULT 0,`playerguid` int(10) unsigned NOT NULL DEFAULT 0,`player_account` int(10) unsigned NOT NULL DEFAULT 0,`type` tinyint(3) unsigned NOT NULL DEFAULT 0, PRIMARY KEY (`petitionguid`,`playerguid`));
INSERT INTO `petition_sign` VALUES (5,777,8,2,9);
CREATE TABLE `recovery_item` (`Id` int(10) unsigned NOT NULL AUTO_INCREMENT,`Guid` int(10) unsigned NOT NULL DEFAULT 0,`ItemEntry` mediumint(8) unsigned NOT NULL DEFAULT 0,`Count` int(10) unsigned NOT NULL DEFAULT 0, PRIMARY KEY (`Id`));
INSERT INTO `recovery_item` VALUES (1,5,6948,1);
CREATE TABLE `quest_tracker` (`id` mediumint(8) unsigned DEFAULT NULL,`character_guid` int(10) unsigned NOT NULL DEFAULT 0,`quest_accept_time` datetime NOT NULL,`quest_complete_time` datetime DEFAULT NULL,`quest_abandon_time` datetime DEFAULT NULL,`completed_by_gm` tinyint(1) NOT NULL DEFAULT 0,`core_hash` varchar(120) NOT NULL DEFAULT '0',`core_revision` varchar(120) NOT NULL DEFAULT '0');
INSERT INTO `quest_tracker` VALUES (NULL,5,'2024-01-01 00:00:00',NULL,NULL,0,'h','r');
CREATE TABLE `playerbots_names` (`name_id` int(10) unsigned NOT NULL AUTO_INCREMENT,`name` varchar(13) NOT NULL,`gender` tinyint(3) unsigned NOT NULL,`in_use` bit(1) NOT NULL DEFAULT b'0', PRIMARY KEY (`name_id`)) ENGINE=MyISAM ROW_FORMAT=FIXED;
INSERT INTO `playerbots_names` VALUES (1,'Aaron',0,'\0');
CREATE TABLE `character_addon` (`guid` int(10) unsigned NOT NULL, `name` varchar(64) NOT NULL);
