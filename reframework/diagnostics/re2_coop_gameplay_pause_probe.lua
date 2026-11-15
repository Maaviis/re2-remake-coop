-- Opt-in, bounded developer probe. Not the co-op coordinator's disconnect policy.
local ok, pause = pcall(function() return require('re2_coop.gameplay_pause').new() end)
if not ok then log.info('RE2_COOP_GAMEPLAY_PAUSE unavailable: ' .. tostring(pause)); return end
local run_id = 'gameplay-pause-' .. os.time() .. '-' .. tostring({})
local frames, sequence, command_id, command_error, release_id = 0, 0, '', '', ''
local deadline, previous_time, last_hint
local processed, processed_count = {}, 0
local clock_methods = {'get_SystemElapsedTime', 'get_GameElapsedTime', 'get_ActualPlayingTime',
    'get_ActualRecordTime', 'get_InSceneTime', 'get_PauseSpendingTime'}
local function token(value)
    return type(value) == 'string' and #value == 32 and value:match('^[0-9a-f]+$') ~= nil
end
local function valid_command(value, now)
    if type(value) ~= 'table' or value.schema ~= 1 or math.type(value.schema) ~= 'integer'
        or not token(value.id) or math.type(value.at) ~= 'integer' or now < value.at or now - value.at > 3 then return false end
    local fields = {schema=true, id=true, at=true, action=true}
    if value.action == 'pause' then
        fields.load_request_id, fields.seconds = true, true
        if not token(value.load_request_id) or math.type(value.seconds) ~= 'integer'
            or value.seconds < 2 or value.seconds > 15 then return false end
    elseif value.action == 'return' then
        fields.pause_id = true
        if not token(value.pause_id) then return false end
    else return false end
    local count, expected = 0, 0
    for key in pairs(value) do if not fields[key] then return false end; count = count + 1 end
    for _ in pairs(fields) do expected = expected + 1 end
    return count == expected
end
local function guard_allows(id, now)
    local value = json.load_file('re2_coop_save_guard.json')
    return type(value) == 'table' and value.schema == 1 and value.active == true and value.hooks == 26
        and math.type(value.at) == 'integer' and now >= value.at and now - value.at <= 3
        and value.load_request_id == id and value.policy_id == id and value.load_phase == 'scene_loaded'
        and value.load_error == '' and value.denied_loads == 0 and value.allowed_load_calls >= 1
        and value.writes == nil and value.allowed_slot == value.load_index and value.has_player == true
end
local function clocks()
    local name = 'app.ropeway.GameClock'
    local def = assert(sdk.find_type_definition(name), 'clock_type_unavailable')
    local clock = assert(sdk.get_managed_singleton(name), 'clock_unavailable')
    local values = {}
    for _, method_name in ipairs(clock_methods) do
        local member = assert(def:get_method(method_name), 'clock_method_unavailable')
        assert(not member:is_static() and #member:get_param_types() == 0
            and member:get_return_type():get_full_name() == 'System.UInt64', 'unsupported_clock_method')
        local value = clock:call(method_name)
        assert(math.type(value) == 'integer' and value >= 0, 'unsupported_clock_value')
        values[method_name] = tostring(value)
    end
    return values
end
re.on_pre_application_entry('UpdateBehavior', function()
    local now = os.time()
    local polled, hint = pcall(pause.poll, pause)
    if not polled then pause.verified, pause.reason = false, 'pause_poll_failed' end
    local read, command = pcall(json.load_file, 're2_coop_pause_command.json')
    if read and valid_command(command, now) and not processed[command.id] and processed_count < 256 then
        processed[command.id], processed_count = true, processed_count + 1
        command_id, command_error = command.id, ''
        local accepted, reason
        if command.action == 'pause' then
            local guarded, allowed = pcall(guard_allows, command.load_request_id, now)
            if not guarded or not allowed then command_error = 'matching_native_load_guard_required'
            else
                local called
                called, accepted, reason = pcall(pause.request, pause, command.id)
                if not called then command_error = 'pause_command_failed'
                elseif accepted then deadline, release_id = now + command.seconds, ''
                else command_error = reason end
            end
        else
            local called
            called, accepted, reason = pcall(pause.release, pause, command.pause_id)
            if not called then command_error = 'pause_command_failed'
            elseif accepted then release_id, deadline = command.id, nil
            else command_error = reason end
        end
    end
    if deadline and (now >= deadline or previous_time and now < previous_time) then
        local cleaned, accepted = pcall(pause.cleanup, pause)
        if cleaned and accepted then deadline, release_id = nil, 'deadline' end
        if pause.phase == 'lost' or pause.phase == 'failed' then deadline = nil end
    end
    previous_time = now
    frames = frames + 1
    if frames % 6 ~= 0 then return end
    local measured, values = pcall(clocks)
    local available = polled and pause.verified and measured
    local reason = not polled and 'pause_poll_failed' or not measured and 'clock_unavailable' or pause.reason
    sequence = sequence + 1
    pcall(json.dump_file, 're2_coop_gameplay_pause.json', {schema=1, source='re2', tdb=70,
        scope='native_gameplay_pause', run_id=run_id, sequence=sequence, observed_at=now,
        pause_id=pause.request_id, phase=pause.phase, available=available, reason=reason,
        command_id=command_id, command_error=command_error, release_id=release_id,
        clocks=measured and values or nil})
    if not polled and hint ~= last_hint then last_hint=hint; pcall(log.info, 'RE2_COOP_GAMEPLAY_PAUSE ' .. tostring(hint)) end
end)
re.on_script_reset(function() pcall(pause.cleanup, pause) end)
