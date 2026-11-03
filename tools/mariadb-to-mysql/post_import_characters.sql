-- Run on the NEW acore_characters AFTER importing converted data.
-- From AzerothCore rev_1756841669142726711.sql (PR #22774): charter items must carry petition_id
-- in the first enchantment slot. The converter already filled petition.petition_id / petition_sign.petition_id
-- with the same formula. Only touches item_instance rows that are charters (joined to petition).
UPDATE `item_instance` AS `ii` JOIN `petition` AS `p` ON `p`.`petitionguid` = `ii`.`guid`
SET `ii`.`enchantments` = CONCAT(`p`.`petition_id`, SUBSTRING(`ii`.`enchantments`, LOCATE(' ', `ii`.`enchantments`)))
WHERE `ii`.`enchantments` IS NOT NULL AND `ii`.`enchantments` <> '' AND `p`.`petition_id` <> `p`.`petitionguid`;
