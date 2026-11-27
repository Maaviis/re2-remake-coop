-- Opt-in load policy; active file locks and the native Steam barrier are required.
if reframework:get_game_name() ~= 're2' then return end
local protection = require('re2_coop.save_protection').new({runtime=true})
if not protection.requested then return end
local ok, guard = pcall(function() return require('re2_coop.save_guard').new(protection) end)
if not ok then log.error('RE2_COOP_SAVE_GUARD unavailable: ' .. tostring(guard)); return end
local loader_module = require('re2_coop.readonly_loader')
local fresh_ok, fresh_module = pcall(require, 're2_coop.new_game')
local area_ok, area_module = pcall(require, 're2_coop.campaign_pose_scope')
local read_area = area_ok and area_module.read_area
local primitive_ok, primitive_module = pcall(require, 're2_coop.gameplay_pause')
local pause_ok, pause_module = pcall(require, 're2_coop.prepared_load_pause')
local checkpoint_available, checkpoint_module = pcall(require, 're2_coop.host_checkpoint')
local admission_available, checkpoint_admission = pcall(require, 're2_coop.checkpoint_admission')
local catalog_available, catalog_module = pcall(require, 're2_coop.checkpoint_catalog')
local solo_available, solo_module = pcall(require, 're2_coop.cutscene_test_peer')
local loader, fresh_driver, guard_run_id, host_checkpoint, checkpoint_catalog, solo, load_pause
local generation = 0
local function begin_generation()
    generation = generation + 1
    guard_run_id = string.format('%d:%.6f:%s:%d', os.time(), os.clock(), tostring(guard), generation)
    loader = loader_module.new(guard)
    fresh_driver = nil
    if fresh_ok and area_ok then
        pcall(function()
            if area_module.supports_area() then fresh_driver = fresh_module.new(guard,loader) end
        end)
    end
    host_checkpoint = checkpoint_available and checkpoint_module.new()
    checkpoint_catalog = catalog_available and catalog_module.new()
    solo = solo_available and solo_module.launcher(guard,fresh_driver,loader,guard_run_id)
    local ok, value = pcall(function()
        assert(primitive_ok and pause_ok and area_ok, 'native_load_pause_unavailable')
        return pause_module.new(guard, loader, guard_run_id, {pause=primitive_module.new(),
            read_area=read_area, new_game=fresh_driver and fresh_module,
            read_world=fresh_driver and function() return fresh_driver:world(read_area) end})
    end)
    load_pause = ok and value or nil
    if not ok then log.info('RE2_COOP_LOAD_PAUSE unavailable: '..tostring(value)) end
end
begin_generation()
local previous_world, previous_guard_history
local interrupted_reader = require('re2_coop.interrupted_state')
local observations = {}
local function add_observation(module, options, scope, filename)
    local ok, reader = pcall(function() return require(module).new(options) end)
    if ok then
        observations[#observations + 1] = {capture=interrupted_reader.new(reader.capture, scope), filename=filename}
    end
end
add_observation('re2_coop.enemy_state', {held_pause=true}, 'registered_and_stored_enemy_contexts',
    're2_coop_interrupted_enemy_state.json')
add_observation('re2_coop.door_state', nil, 'loaded_scene_door_state', 're2_coop_interrupted_door_state.json')
add_observation('re2_coop.world_item_state', nil, 'native_world_item_placements', 're2_coop_interrupted_world_items.json')
local cached_lobby, cached_peer, cached_peer_release
local consumed_attempts = {}
local last_policy, last_report, last_command, prepared_load
local staged_load
local staged_load_age = 20
local command_error = ''
local trace, cached_snapshot = {}, nil

local function positive_u32(value)
    return type(value) == 'number' and value > 0 and value <= 0xffffffff and value % 1 == 0
end

local function checkpoint_identity(value)
    if type(value) ~= 'table' or type(value.namespace) ~= 'string' or #value.namespace ~= 32
        or not value.namespace:match('^[0-9a-f]+$') or type(value.digest) ~= 'string'
        or #value.digest ~= 64 or not value.digest:match('^[0-9a-f]+$') then return false end
    for key in pairs(value) do if key ~= 'namespace' and key ~= 'digest' then return false end end
    return true
end
local function checkpoint_supported()
    return admission_available and type(checkpoint_admission.read) == 'function'
        and type(guard.allow_checkpoint) == 'function' and type(guard.revoke_checkpoint) == 'function'
        and loader.supports_checkpoint == true and load_pause ~= nil
end

local function prepared_lobby_reference(value, now)
    local scope = value.lobby_load
    local new, checkpoint = value.schema == 4, value.schema == 5
    if value.load ~= true or type(scope) ~= 'table' or scope.guard_run_id ~= guard_run_id
        or type(scope.attempt_id) ~= 'string' or #scope.attempt_id ~= 32
        or not scope.attempt_id:match('^[0-9a-f]+$')
        or type(scope.save_digest) ~= 'string' or #scope.save_digest ~= 64
        or not scope.save_digest:match('^[0-9a-f]+$')
        or not positive_u32(scope.game_pid) or type(scope.membership) ~= 'table'
        or scope.game_pid ~= value.protection.game_pid
        or not positive_u32(scope.membership.revision)
        or type(scope.membership.session_id) ~= 'string' or #scope.membership.session_id ~= 32
        or type(scope.session_id) ~= 'string' or scope.session_id == ''
        or type(scope.revision) ~= 'number'
        or (new and (value.reference ~= nil or not fresh_driver or not fresh_module.selection(value.new_game)
            or guard.policy ~= nil or guard.allowed_load_calls ~= 0))
        or (not new and (type(value.reference) ~= 'table' or value.new_game ~= nil))
        or (checkpoint and (not checkpoint_supported() or not checkpoint_identity(value.checkpoint)
            or type(value.preparation_id) ~= 'string' or #value.preparation_id ~= 32
            or not value.preparation_id:match('^[0-9a-f]+$') or guard.policy ~= nil
            or guard.allowed_load_calls ~= 0 or scope.save_digest ~= value.checkpoint.digest))
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
    local check, selected, checkpoint_choice = data.load_check, data.save_ref, nil
    if data.connected ~= true or data.revision ~= scope.revision or type(data.ready) ~= 'table'
        or data.ready[data.host_id] ~= true or data.ready[data.guest_id] ~= true
        or type(check) ~= 'table' or check.admission ~= 1 or check.reason ~= ''
        or (new or guard.protection.current.runtime == true) and check.campaign_start ~= true
        or (check.phase ~= 'prepared' and check.phase ~= 'starting')
        or check.attempt_id ~= scope.attempt_id
        or check.revision ~= scope.revision or check.save_digest ~= scope.save_digest then return false end
    if new then
        if not fresh_module.matches(data, value.new_game) then return false end
        selected = {scenario=data.new_game.scenario,difficulty=data.new_game.difficulty}
    elseif checkpoint then
        local choice = type(data.settings) == 'table' and data.settings.coop_checkpoint
        if data.new_game ~= nil or data.save_ref ~= nil or data.save_slot ~= nil
            or check.checkpoint_version ~= 1 or check.campaign_start ~= true
            or type(choice) ~= 'table' or choice.namespace ~= value.checkpoint.namespace
            or choice.digest ~= value.checkpoint.digest or choice.scenario ~= value.reference.scenario
            or (choice.difficulty ~= 0 and choice.difficulty ~= 1 and choice.difficulty ~= 2)
            or type(choice.saved_at) ~= 'string' then return false end
        local valid = pcall(checkpoint_admission.read, guard, value.reference,
            value.preparation_id, guard_run_id, now)
        if not valid then return false end
        selected, checkpoint_choice = value.reference, choice
    else
        local slot = type(value.reference.slot_id) == 'number' and math.tointeger(value.reference.slot_id)
        if data.new_game ~= nil or not slot or data.save_slot ~= 'scenario:' .. slot
            or type(selected) ~= 'table' or selected.available ~= true then return false end
        for _, field in ipairs({'mode', 'slot_id', 'timestamp', 'scenario'}) do
            if selected[field] ~= value.reference[field] then return false end
        end
    end
    local starting = check.phase == 'starting'
    if starting and (type(check.start) ~= 'table' or check.start[scope.role] ~= value.id) then return false end
    local permit = status.prepared_start
    -- The admission read can be newer than this update's cached lobby heartbeat.
    cached_lobby = status
    return selected, starting, starting and type(permit) == 'table' and permit.id == value.id
        and type(permit.before) == 'number' and now < permit.before, checkpoint_choice
end

local function apply_command(value, now, previous_stage)
    if not guard.protection:matches(value.protection) then return 'protected_launch_required' end
    local new, checkpoint = value.schema == 4, value.schema == 5
    if guard.campaign_mode and ((not new and not checkpoint) or not guard:campaign_ready(value.protection)) then
        return 'campaign_mount_not_ready'
    end
    if guard.protection.current.runtime == true and value.schema ~= 3 and not new and not checkpoint then return 'runtime_campaign_required' end
    if value.new_game ~= nil and not new then return 'lobby_load_no_longer_prepared' end
    if (value.checkpoint ~= nil or value.preparation_id ~= nil) and not checkpoint then return 'lobby_load_no_longer_prepared' end
    if loader:is_in_progress() then return 'load_in_progress' end
    if load_pause and load_pause:in_progress() then return 'load_pause_in_progress' end
    local prepared_reference
    if value.schema == 3 or new or checkpoint then
        local starting, permitted, checkpoint_choice
        prepared_reference, starting, permitted, checkpoint_choice = prepared_lobby_reference(value, now)
        if not prepared_reference then return 'lobby_load_no_longer_prepared' end
        if not load_pause then return 'native_load_pause_unavailable' end
        if consumed_attempts[value.lobby_load.attempt_id] then return 'lobby_load_attempt_used' end
        if starting and (not previous_stage or previous_stage.id ~= value.id
                         or previous_stage.requested_at ~= value.at) then return 'prepared_load_not_staged' end
        local staged_selection
        if new then
            local s = value.lobby_load
            staged_selection = {scenario=value.new_game.scenario,difficulty=value.new_game.difficulty,
                role=s.role, game_pid=s.game_pid, session_id=s.session_id, revision=s.revision,
                attempt_id=s.attempt_id, save_digest=s.save_digest, membership=s.membership.session_id,
                membership_revision=s.membership.revision, protection_run_id=value.protection.run_id,
                campaign_namespace=value.protection.campaign_namespace}
        elseif checkpoint then
            local scope = value.lobby_load
            staged_selection = {namespace=value.checkpoint.namespace,digest=value.checkpoint.digest,
                preparation_id=value.preparation_id, mode=value.reference.mode, slot_id=value.reference.slot_id,
                timestamp=value.reference.timestamp, scenario=value.reference.scenario,
                difficulty=checkpoint_choice.difficulty,saved_at=checkpoint_choice.saved_at,
                role=scope.role,game_pid=scope.game_pid,session_id=scope.session_id,revision=scope.revision,
                attempt_id=scope.attempt_id,save_digest=scope.save_digest,membership=scope.membership.session_id,
                membership_revision=scope.membership.revision,protection_run_id=value.protection.run_id,
                campaign_namespace=value.protection.campaign_namespace}
        end
        if previous_stage and previous_stage.id == value.id then
            if (previous_stage.selection == nil) ~= (staged_selection == nil) then return 'prepared_load_not_staged' end
            for key, field in pairs(staged_selection or {}) do
                if field ~= previous_stage.selection[key] then return 'prepared_load_not_staged' end
            end
        end
        if not permitted then
            local ready, reason
            if new then ready, reason = fresh_driver:ready(value.new_game,value.protection)
            else ready, reason = loader:ready() end
            if not ready then return reason end
            return '', {id=value.id, requested_at=value.at,selection=staged_selection}
        end
    elseif value.schema == 2 then
        return 'prepared_load_requires_staging'
    elseif value.lobby_load ~= nil then
        return 'lobby_load_no_longer_prepared'
    end

    if value.load == true then
        local scope = value.lobby_load
        if scope then
            local armed, reason = load_pause:arm(value.id, scope, value.reference, value.new_game, checkpoint and value.checkpoint or nil)
            if not armed then return reason end
            consumed_attempts[scope.attempt_id] = true
        end
        local started, reason
        if new then started,reason = fresh_driver:start(prepared_reference,value.id,value.protection)
        elseif checkpoint then
            started,reason = loader:start(value.reference,value.id,
                {preparation_id=value.preparation_id,guard_run_id=guard_run_id})
        else started,reason = loader:start(value.reference,value.id) end
        if not started and scope and (not new or loader.request_id ~= value.id) then load_pause:cancel(value.id) end
        if loader.request_id == value.id then
            last_policy = value.id
            prepared_load = started and scope and {scope=scope, [new and 'new_game' or 'reference']=prepared_reference} or nil
            if prepared_load and checkpoint then
                prepared_load.checkpoint = {namespace=value.checkpoint.namespace,digest=value.checkpoint.digest}
                prepared_load.preparation_id = value.preparation_id
            end
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
local function register_trace_hooks()
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
end
local frames, activation_frame, activation_poll = 0, nil, nil
local installing_logged, active_logged, reported_mount
re.on_frame(function() frames = frames + 1 end)
re.on_pre_application_entry('UpdateBehavior', function()
    local now = os.time()
    if not activation_frame then
        if activation_poll == now then return end
        activation_poll = now
        if not protection:poll() then return end
        if not installing_logged then
            log.info('RE2_COOP_SAVE_GUARD prepare=installing_hooks')
            installing_logged = true
        end
        if not guard:activate() then return end
        register_trace_hooks()
        activation_frame = frames
        log.info('RE2_COOP_SAVE_GUARD prepare=hooks_queued')
        return
    end
    -- REFramework installs queued Lua hooks after on_frame. Wait until an
    -- entire frame has completed before publishing readiness or acting on a policy.
    if frames <= activation_frame + 1 then return end
    if not active_logged then
        log.info('RE2_COOP_SAVE_GUARD prepare=hooks_active')
        active_logged = true
    end
    if now ~= last_report then
        local loaded, value = pcall(json.load_file, 're2_coop_lobby.json')
        cached_lobby = loaded and value or nil
        if load_pause and load_pause:in_progress() then
            local observed, peer = pcall(json.load_file, 're2_coop_native_peer.json')
            if observed and type(peer) == 'table' then cached_peer = peer end
            if load_pause.phase == 'released' then
                local read, evidence = pcall(json.load_file, 're2_coop_campaign_peer_release.json')
                if read and type(evidence) == 'table' then cached_peer_release = evidence end
            end
        else
            cached_peer, cached_peer_release = nil, nil
        end
    end
    if load_pause then
        local polled = pcall(load_pause.poll, load_pause, cached_lobby, cached_peer, cached_peer_release)
        if not polled then load_pause.available, load_pause.reason = false, 'native_load_pause_poll_failed' end
    end
    -- Process previously admitted work BEFORE reading this update's start command.
    -- Menu closure can therefore finalize on the next UpdateBehavior, including in the same second.
    if solo then solo:update() end
    if loader.new_game and (loader.phase == 'closing_menu' or loader.phase == 'loading' and now ~= last_report) then
        if solo and solo:owns_start() then
            fresh_driver:poll(solo:admitted(),function() return guard.protection:poll() and solo:admitted() end)
        else
            fresh_driver:poll(load_pause:new_game_admitted(cached_lobby),function()
                if not guard.protection:poll() then return false end
                local ok, status = pcall(json.load_file, 're2_coop_lobby.json')
                return ok and load_pause:new_game_admitted(status)
            end)
        end
    end
    if now == last_report then return end
    last_report = now
    guard.protection:poll()
    local mount = guard:sync_campaign_mount(not loader:is_in_progress())
    if previous_world and not mount and loader.phase == 'scene_loaded' then
        local read, peer = pcall(json.load_file, 're2_coop_native_peer.json')
        local ok, history = pcall(guard.retire_campaign,guard,previous_world,read and peer,now)
        if ok and history then
            history.guard_run_id = guard_run_id
            previous_guard_history, previous_world = history, nil
            staged_load, prepared_load, last_policy = nil, nil, nil
            command_error, cached_peer, cached_peer_release = '', nil, nil
            begin_generation()
            log.info('RE2_COOP_SAVE_GUARD previous campaign retired at protected title')
        end
    end
    local previous_stage = staged_load
    staged_load = nil
    local matches = fs.glob('^re2_coop_save_policy\\.json$')
    if matches and #matches > 0 then
        local loaded, value = pcall(json.load_file, 're2_coop_save_policy.json')
        if loaded and type(value) == 'table' and (value.schema == 1 or value.schema == 2 or value.schema == 3 or value.schema == 4 or value.schema == 5)
            and type(value.id) == 'string'
            and value.id ~= '' and value.id ~= last_command
            and type(value.at) == 'number' and now >= value.at then
            local age = now - value.at
            if age <= ((value.schema == 3 or value.schema == 4 or value.schema == 5) and staged_load_age or 5) then
                local reason
                reason, staged_load = apply_command(value, now, previous_stage)
                if not staged_load then last_command, command_error = value.id, reason end
            elseif previous_stage and previous_stage.id == value.id then
                last_command, command_error = value.id, 'staged_load_expired'
            end
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
    if not loader.new_game then loader:poll(observation) end
    if load_pause then
        local polled = pcall(load_pause.poll, load_pause, cached_lobby, cached_peer, cached_peer_release)
        if not polled then load_pause.available, load_pause.reason = false, 'native_load_pause_poll_failed' end
        if load_pause.available then
            local read, command = pcall(json.load_file, 're2_coop_campaign_resume.json')
            if read and type(command) == 'table' then load_pause:resume(cached_lobby, command, cached_peer) end
        end
    end
    local bound = guard.protection:ready() and guard.protection.current
    local state = {schema = 1, at = now, active = guard.active, hooks = guard.hook_count,
        protection_active = guard.protection:ready(),
        runtime_protection = not not (bound and bound.runtime),
        protection_error = guard.protection.reason,
        protection = bound and {game_pid = bound.game_pid, run_id = bound.run_id,
            campaign_namespace = bound.campaign_namespace} or nil,
        campaign_mount_ready = mount and bound and guard:campaign_ready(bound) and mount or nil,
        guard_run_id = guard_run_id,
        load_hold = load_pause and load_pause:snapshot() or nil,
        new_game_supported = fresh_driver ~= nil and load_pause ~= nil and (not guard.campaign_mode or mount ~= nil),
        checkpoint_supported = checkpoint_supported() and guard.campaign_mode == true and mount ~= nil,
        staged_load = staged_load and {id=staged_load.id,requested_at=staged_load.requested_at},
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
    if state.campaign_mount_ready ~= reported_mount then
        reported_mount = state.campaign_mount_ready
        if reported_mount then log.info('RE2_COOP_SAVE_GUARD prepare=mount_confirmed') end
    end
    state.previous_campaign = previous_guard_history
    if bound and bound.runtime and state.campaign_mount_ready and state.load_phase == 'scene_loaded'
        and state.has_player and state.scene_finished and not state.in_title and not state.loading_flow
        and cached_lobby and cached_lobby.game_pid == bound.game_pid and cached_lobby.steam_membership
        and math.type(cached_lobby.written_at) == 'integer' and now >= cached_lobby.written_at
        and now-cached_lobby.written_at <= 3 and positive_u32(cached_lobby.steam_membership.revision)
        and (not previous_world or previous_world.namespace == mount
            and previous_world.revision == cached_lobby.steam_membership.revision) then
        previous_world = {namespace=mount, game_pid=bound.game_pid, run_id=bound.run_id,
            revision=cached_lobby.steam_membership.revision, allowed_load_calls=guard.allowed_load_calls}
    end
    state.campaign_world_revision = previous_world and previous_world.revision or nil
    if state.staged_load and staged_load.selection and staged_load.selection.preparation_id then
        local selection=staged_load.selection
        state.staged_load.checkpoint={namespace=selection.namespace,digest=selection.digest}
        state.staged_load.preparation_id=selection.preparation_id
        state.staged_load.reference={mode=selection.mode,slot_id=selection.slot_id,
            timestamp=selection.timestamp,scenario=selection.scenario}
    end
    cached_snapshot = {at = now, busy = state.busy, buffer = state.loaded_buffer,
        loading_flow = state.loading_flow, load_phase = state.load_phase}
    local function read_hold()
        load_pause:poll(cached_lobby, cached_peer, cached_peer_release)
        state.load_hold = load_pause:snapshot()
        return state.load_hold
    end
    if loader.new_game and state.load_hold and state.load_hold.available and state.load_hold.phase == 'held' then
        local ok, world = pcall(fresh_driver.world,fresh_driver,read_area)
        local checked, hold = pcall(read_hold)
        if ok and world and checked and hold.available and hold.phase == 'held'
            and hold.load_request_id == world.request_id then state.new_game_world = world end
    end
    local evidence = {}
    for index, observation in ipairs(observations) do
        if not state.load_hold or not state.load_hold.interruption then break end
        local captured, report = pcall(observation.capture, state.load_hold, read_hold)
        if captured then evidence[index] = report else state.load_hold = nil end
    end
    if host_checkpoint and state.campaign_mount_ready then
        local read, request = pcall(json.load_file, 're2_coop_checkpoint_request.json')
        state.host_checkpoint = host_checkpoint(read and request, state, manager, flow, now)
    end
    if checkpoint_catalog then
        local read, native = pcall(json.load_file, 're2_coop_native_save_guard.json')
        local receipt = checkpoint_catalog(read and native, state, manager, flow, gui, now)
        if receipt then json.dump_file('re2_coop_checkpoint_catalog.json', receipt) end
    end
    json.dump_file('re2_coop_save_guard.json', state)
    if state.load_hold and state.load_hold.interruption then
        for index, report in pairs(evidence) do
            pcall(json.dump_file, observations[index].filename, report)
        end
    end
end)
