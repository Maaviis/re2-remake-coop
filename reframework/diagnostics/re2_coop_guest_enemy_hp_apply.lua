-- Opt-in positive-HP application for the isolated, guarded guest test.
if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end
local ok, apply = pcall(function() return require('re2_coop.guest_enemy_hp').new() end)
if not ok then
    log.info('RE2_COOP_GUEST_ENEMY_HP unavailable: ' .. tostring(apply))
    return
end
require('re2_coop.guest_enemy_readback').install(apply)
