-- Opt-in read-only timeline samples. No event hooks, network messages or gameplay commands.
local ok, reader = pcall(function() return require('re2_coop.timeline_state').new() end)
local run_id = 'timeline-state-' .. os.time() .. '-' .. tostring({})
local frames, sequence, last_hint = 0, 0, nil
local function publish(state, reason)
    sequence = sequence + 1
    json.dump_file('re2_coop_timeline_state.json', {schema=1, source='re2', tdb=sdk.get_tdb_version(),
        scope='native_timeline_activity', run_id=run_id, sequence=sequence, observed_at=os.time(),
        available=state ~= nil, reason=reason, state=state})
end
if not ok then
    pcall(publish, nil, 'unsupported_interfaces')
    pcall(log.info, 'RE2_COOP_TIMELINE_STATE ' .. tostring(reader))
    return
end
re.on_pre_application_entry('UpdateBehavior', function()
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local success, state, reason, hint = pcall(reader.capture)
    if not success then hint, state, reason = tostring(state), nil, 'state_read_failed' end
    if hint and hint ~= last_hint then
        last_hint = hint
        pcall(log.info, 'RE2_COOP_TIMELINE_STATE ' .. hint)
    end
    pcall(publish, state, reason)
end)
