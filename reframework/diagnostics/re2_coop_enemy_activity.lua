-- Opt-in native AI flags. Enabled flags do not prove executed AI decisions.
if reframework:get_game_name() ~= 're2' then return end
local ok, reader = pcall(function() return require('re2_coop.enemy_state').new({include_activity = true}) end)
local run_id = string.format('enemy-activity-%d-%.6f', os.time(), os.clock())
local frames, sequence, stopped = 0, 0, false
local function publish(state, reason)
    sequence = sequence + 1
    pcall(json.dump_file, 're2_coop_enemy_activity.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        scope = 'native_enemy_ai_flags', run_id = run_id, sequence = sequence, observed_at = os.time(),
        available = state ~= nil, reason = reason, state = state})
end
if not ok then
    publish(nil, 'unsupported_interfaces')
    pcall(log.info, 'RE2_COOP_ENEMY_ACTIVITY unavailable: ' .. tostring(reader))
    return
end
re.on_application_entry('UpdateBehavior', function()
    if stopped then return end
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local state, reason = reader.capture()
    publish(state, reason)
end)
re.on_script_reset(function() stopped = true; publish(nil, 'script_reset') end)
