-- Opt in only for local save/load tests; copying this file to autorun disables saving.
if reframework:get_game_name() ~= 're2' then return end
local ok, guard = pcall(function() return require('re2_coop.save_guard').new() end)
if not ok then log.error('RE2_COOP_SAVE_GUARD unavailable: ' .. tostring(guard)); return end
local loader = require('re2_coop.readonly_loader').new(guard)
local guard_run_id = string.format('%d:%.6f:%s', os.time(), os.clock(), tostring(guard))
local consumed_attempts = {}
local last_policy, last_report, last_command, prepared_load
local command_error = ''
local trace, cached_snapshot = {}, nil

local function positive_u32(value)
    return type(value) == 'number' and value > 0 and value <= 0xffffffff and value % 1 == 0
end

local function prepared_lobby_reference(value, now)
    local scope = value.lobby_load
    if value.load ~= true or type(scope) ~= 'table' or scope.guard_run_id ~= guard_run_id
        or type(scope.attempt_id) ~= 'string' or #scope.attempt_id ~= 32
        or not scope.attempt_id:match('^[0-9a-f]+$')
        or type(scope.save_digest) ~= 'string' or #scope.save_digest ~= 64
        or not scope.save_digest:match('^[0-9a-f]+$')
        or not positive_u32(scope.game_pid) or type(scope.membership) ~= 'table'
        or not positive_u32(scope.membership.revision)
        or type(scope.membership.session_id) ~= 'string' or #scope.membership.session_id ~= 32
        or type(scope.session_id) ~= 'string' or scope.session_id == ''
        or type(scope.revision) ~= 'number' or type(value.reference) ~= 'table'
        or not guard.active or guard.hook_count ~= 26 or guard.denied_loads ~= 0
        or next(guard.writes) ~= nil then return false end

    local ok, status = pcall(json.load_file, 're2_coop_lobby.json')
    if not ok or type(status) ~= 'table' or status.schema ~= 1
        or type(status.written_at) ~= 'number' or status.written_at % 1 ~= 0
        or now < status.written_at or now - status.written_at > 3
        or status.connected ~= true or status.game_pid ~= scope.game_pid
        or status.role ~= scope.role
        or (not (status.role == 'H' and status.steam_lobby == 'owned')
            and not (status.role == 'G' and status.steam_lobby == 'joined')) then return false end

    local member, message = status.steam_membership, status.lobby
    if type(member) ~= 'table' or member.session_id ~= scope.membership.session_id
        or member.revision ~= scope.membership.revision
        or type(message) ~= 'table' or message.version ~= 1 or message.type ~= 'lobby_state'
        or message.session_id ~= scope.session_id or type(message.data) ~= 'table' then return false end
    local data = message.data
    local check, selected = data.load_check, data.save_ref
    if data.connected ~= true or data.revision ~= scope.revision or type(data.ready) ~= 'table'
        or data.ready[data.host_id] ~= true or data.ready[data.guest_id] ~= true
        or type(check) ~= 'table' or check.phase ~= 'prepared' or check.reason ~= ''
        or check.attempt_id ~= scope.attempt_id
        or check.revision ~= scope.revision or check.save_digest ~= scope.save_digest
        or type(selected) ~= 'table' or selected.available ~= true then return false end
    for _, field in ipairs({'mode', 'slot_id', 'timestamp', 'scenario'}) do
        if selected[field] ~= value.reference[field] then return false end
    end
    return selected
end

local function apply_command(value, now)
    if loader:is_in_progress() then return 'load_in_progress' end
    local prepared_reference
    if value.schema == 2 then
        prepared_reference = prepared_lobby_reference(value, now)
        if not prepared_reference then return 'lobby_load_no_longer_prepared' end
    elseif value.lobby_load ~= nil then
        return 'lobby_load_no_longer_prepared'
    end

    if value.load == true then
        local scope = value.lobby_load
        if scope then
            if consumed_attempts[scope.attempt_id] then return 'lobby_load_attempt_used' end
            consumed_attempts[scope.attempt_id] = true
        end
        local started, reason = loader:start(value.reference, value.id)
        if loader.request_id == value.id then
            last_policy = value.id
            prepared_load = started and scope and {scope=scope, reference=prepared_reference} or nil
        end
        return started and '' or reason
    end
    if not pcall(guard.allow, guard, value.reference) then return 'save_reference_not_available' end
    last_policy = value.id
    log.info('RE2_COOP_SAVE_GUARD reference armed')
    return ''
end

local function trace_call(method, stage)
    -- Hooks may run during a native save/flow transition. Never re-enter game getters
    -- for diagnostics here; this immutable sample belongs to an earlier update.
    trace[#trace + 1] = {method = method, stage = stage, at = os.clock(),
        cached = cached_snapshot}
    if #trace > 64 then table.remove(trace, 1) end
end
for _, target in ipairs({
        {'app.ropeway.gamemastering.SaveDataManager', 'requestLoadGameData'},
        {'app.ropeway.gamemastering.SaveDataManager', 'loadGameSaveData'},
        {'app.ropeway.gamemastering.SaveDataManager', 'setLoadData'},
        {'app.ropeway.gamemastering.MainFlowManager', 'goLoadGameData'},
        {'app.ropeway.gamemastering.MainFlowManager', 'delayLoadGameSaveData'},
        {'app.ropeway.gamemastering.MainFlowManager', 'setupLoadGameData'},
        {'app.ropeway.gamemastering.LoadGameDataFlow', 'setup'}}) do
    local def = sdk.find_type_definition(target[1])
    local method = def and def:get_method(target[2])
    if method then
        sdk.hook(method, function()
            pcall(trace_call, target[1] .. '.' .. target[2], 'pre')
            return sdk.PreHookResult.CALL_ORIGINAL
        end, function(retval)
            pcall(trace_call, target[1] .. '.' .. target[2], 'post')
            return retval
        end)
    end
end
re.on_pre_application_entry('UpdateBehavior', function()
    local now = os.time()
    if now == last_report then return end
    last_report = now
    local matches = fs.glob('^re2_coop_save_policy\\.json$')
    if matches and #matches > 0 then
        local loaded, value = pcall(json.load_file, 're2_coop_save_policy.json')
        if loaded and type(value) == 'table' and (value.schema == 1 or value.schema == 2)
            and type(value.id) == 'string'
            and value.id ~= '' and value.id ~= last_command
            and type(value.at) == 'number' and now >= value.at and now - value.at <= 5 then
            last_command, command_error = value.id, apply_command(value, now)
        end
    end
    local manager = sdk.get_managed_singleton('app.ropeway.gamemastering.SaveDataManager')
    local flow = sdk.get_managed_singleton('app.ropeway.gamemastering.MainFlowManager')
    local gui = sdk.get_managed_singleton('app.ropeway.gui.GUIMaster')
    local has_player, observation = false, nil
    local observers = fs.glob('^re2_coop_observer\\.json$')
    if observers and #observers > 0 then
        local read, sample = pcall(json.load_file, 're2_coop_observer.json')
        has_player = read and type(sample) == 'table' and sample.source == 're2' and sample.tdb == 70
            and sample.available == true and type(sample.observed_at) == 'number'
            and now >= sample.observed_at and now - sample.observed_at <= 3
        if has_player then observation = sample end
    end
    loader:poll(observation)
    local state = {schema = 1, at = now, active = guard.active, hooks = guard.hook_count,
        guard_run_id = guard_run_id,
        prepared_load = last_policy == loader.request_id and prepared_load or nil,
        command_id = last_command or '', command_error = command_error,
        load_request_id = loader.request_id or '',
        policy_id = last_policy or '', allowed_slot = guard.policy and guard.policy.slot_id or -1,
        writes = guard.writes, allowed_load_calls = guard.allowed_load_calls, denied_loads = guard.denied_loads,
        events = guard.events, trace = trace, busy = manager and manager:call('get_IsBusy') or false,
        loaded_buffer = manager and manager:call('get_IsExistLoadedGameData') or false,
        load_index = manager and manager:call('get_LoadGameDataIndex') or -1,
        scene_finished = flow and flow:call('get_IsFinishedLoadScene') or false,
        loading_flow = flow and flow:call('get_IsInLoadGameData') or false,
        title_environment = flow and flow:call('get_IsTitleSceneEnvironmentLoaded') or false,
        in_title = flow and flow:call('get_IsInTitle') or false,
        gui_available = gui ~= nil,
        title_open = gui and gui:call('isTitleMenuOpened'),
        main_menu_busy = gui and gui:call('isBusyMenuMain'),
        story_menu_busy = gui and gui:call('isBusyMenuStory'),
        load_menu_busy = gui and gui:call('isBusyLoad'),
        load_phase = loader.phase, load_error = loader.error, load_started_at = loader.started_at,
        has_player = has_player}
    cached_snapshot = {at = now, busy = state.busy, buffer = state.loaded_buffer,
        loading_flow = state.loading_flow, load_phase = state.load_phase}
    json.dump_file('re2_coop_save_guard.json', state)
end)
