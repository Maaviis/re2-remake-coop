-- Opt-in passive enemy callback export, outside native damage hooks.
if reframework:get_game_name() ~= 're2' then return end
local ok, reader = pcall(function() return require('re2_coop.damage_observer').new() end)
local run_id = string.format('damage-%d-%.6f', os.time(), os.clock())
local frames = 0
if not ok then
    log.info('RE2_COOP_DAMAGE_OBSERVER unavailable: ' .. tostring(reader))
    pcall(json.dump_file, 're2_coop_damage_observer.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        observed_at = os.time(), run_id = run_id, available = false, reason = 'unsupported_interfaces'})
    return
end
re.on_application_entry('UpdateBehavior', function()
    -- Native game getters are deliberately outside the hit hooks.
    local found, player = pcall(function()
        local manager = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        return manager and manager:call('get_CurrentPlayer')
    end)
    reader:set_local_player(found and player or nil)
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    pcall(json.dump_file, 're2_coop_damage_observer.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        observed_at = os.time(), run_id = run_id, available = true, scope = 'enemy_damage_callback', state = reader:snapshot()})
end)
re.on_script_reset(function() reader:stop() end)
