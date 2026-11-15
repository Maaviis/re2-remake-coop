-- Opt-in registered-enemy evidence. Does not write game state or send network events.
local ok, reader = pcall(function() return require('re2_coop.enemy_state').new() end)
local run_id = 'enemy-state-' .. os.time() .. '-' .. tostring({})
local sequence, frames, last_hint = 0, 0, nil
local function publish(state, reason)
    sequence = sequence + 1
    json.dump_file('re2_coop_enemy_state.json', {schema = 1, source = 're2', tdb = sdk.get_tdb_version(),
        run_id = run_id, sequence = sequence, observed_at = os.time(), scope = 'registered_enemy_contexts',
        available = state ~= nil, reason = reason, state = state})
end
if not ok then
    pcall(publish, nil, 'unsupported_interfaces')
    log.info('RE2_COOP_ENEMY_STATE unavailable: ' .. tostring(reader))
    return
end
re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local success, state, reason, hint = pcall(reader.capture)
    if not success then state, reason, hint = nil, 'enemy_read_failed', tostring(state) end
    if hint and hint ~= last_hint then
        last_hint = hint
        pcall(log.info, 'RE2_COOP_ENEMY_STATE ' .. hint)
    end
    pcall(publish, state, reason)
end)
