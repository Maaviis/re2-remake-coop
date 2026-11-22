-- Read-only local readback of verified Steam guest observations.
local M = {}

local max_age, max_enemies, max_integer = 3, 512, 9007199254740991
local max_signed, min_signed = 0x7fffffff, -0x80000000
local max_receipt, max_native, max_guard = 262144, 2097152, 131072
local input_name, output_name = 're2_coop_guest_enemies.json', 're2_coop_guest_enemy_readback.json'
local campaign
local guid_pattern = '^' .. string.rep('%x', 8) .. '%-' .. string.rep('%x', 4) .. '%-'
    .. string.rep('%x', 4) .. '%-' .. string.rep('%x', 4) .. '%-' .. string.rep('%x', 12) .. '$'
local zero_guid = '00000000-0000-0000-0000-000000000000'

local function integer(value, low, high)
    return type(value) == 'number' and value >= low and value <= high and value % 1 == 0
end

local function guid(value)
    return type(value) == 'string' and value ~= zero_guid and value == value:lower()
        and value:match(guid_pattern) ~= nil
end

local function token(value)
    return type(value) == 'string' and #value == 32 and value:match('^[0-9a-f]+$') ~= nil
end

local function fresh(value, now)
    return integer(value, 1, now) and now - value <= max_age
end

local function same_checkpoint(a, b)
    return type(a) == 'table' and type(b) == 'table'
        and guid(a.game_guid) and a.game_guid == b.game_guid
        and guid(a.save_guid) and a.save_guid == b.save_guid
        and integer(a.scenario, 0, max_signed) and a.scenario == b.scenario
        and integer(a.location, 0, max_signed) and a.location == b.location
end

local function read_document(name, size)
    local raw = fs.read(name)
    if type(raw) ~= 'string' or #raw == 0 or #raw > size then return nil end
    local ok, parsed = pcall(json.load_string, raw)
    if ok and type(parsed) == 'table' then return parsed, raw end
end

local function read_receipt(now, tracker, scope)
    local receipt, bytes = read_document(input_name, max_receipt)
    if not receipt then return nil, 'receipt_unavailable' end
    if receipt.schema ~= 1 or receipt.source ~= 'steam_enemy_live' or receipt.tdb ~= 70
        or not token(receipt.session_id) or not fresh(receipt.received_at, now)
        or not integer(receipt.generation, 1, max_integer)
        or receipt.generation // 1000000 > receipt.received_at
        or not integer(receipt.sequence, 1, max_integer)
        or type(receipt.view) ~= 'table' or receipt.view.schema ~= 1
        or receipt.view.scope ~= 'active_enemy_controller_observations'
        or type(receipt.view.available) ~= 'boolean' then
        return nil, 'invalid_or_expired_receipt'
    end
    if scope then
        if not token(receipt.campaign_attempt) or receipt.campaign_attempt ~= scope.attempt_id
            or receipt.session_id ~= scope.session_id then return nil, 'campaign_receipt_required' end
    elseif receipt.campaign_attempt ~= nil then
        return nil, 'diagnostic_receipt_required'
    end
    local last = tracker.last
    if last and (receipt.generation < last.generation or (receipt.generation == last.generation
        and (receipt.session_id ~= last.session_id or receipt.sequence < last.sequence
            or receipt.received_at < last.received_at
            or (receipt.sequence == last.sequence and bytes ~= tracker.last_bytes)))) then
        return nil, 'replayed_receipt'
    end
    tracker.last = {generation=receipt.generation, session_id=receipt.session_id,
        sequence=receipt.sequence, received_at=receipt.received_at}
    tracker.last_bytes = bytes
    if not receipt.view.available then return nil, 'peer_unavailable' end
    if receipt.view.reason ~= 'ok' or type(receipt.view.enemies) ~= 'table'
        or type(receipt.view.continuous) ~= 'boolean'
        or not integer(receipt.view.observer_sequence, 1, max_integer)
        or not integer(receipt.view.observed_at, 1, max_integer)
        or type(receipt.load) ~= 'table' or not token(receipt.load.request_id)
        or (scope and receipt.load.request_id ~= scope.request_id)
        or not integer(receipt.load.slot_id, 0, 20)
        or type(receipt.load.observer_run_id) ~= 'string'
        or #receipt.load.observer_run_id == 0 or #receipt.load.observer_run_id > 128
        or not integer(receipt.load.observer_sequence, 1, max_integer) then
        return nil, 'invalid_receipt_source'
    end
    return receipt
end

local function live_values(row)
    return type(row) == 'table' and integer(row.inherit_id, min_signed, max_signed)
        and integer(row.hp, min_signed, max_signed)
        and type(row.is_live) == 'boolean' and type(row.is_dead) == 'boolean'
end

local function read_host_deaths(view)
    if type(view.death_observations) ~= 'table' then return nil end
    local deaths, count = {}, 0
    for id, row in pairs(view.death_observations) do
        if count >= max_enemies or not guid(id) or type(row) ~= 'table'
            or not integer(row.kind_id, min_signed, max_signed)
            or not integer(row.inherit_id, min_signed, max_signed)
            or not integer(row.hp, min_signed, max_signed)
            or type(row.active) ~= 'boolean' or row.is_dead ~= true
            or not integer(row.observer_sequence, 1, view.observer_sequence)
            or not integer(row.observed_at, 1, view.observed_at) then return nil end
        local active = view.enemies[id]
        if active and (not row.active or active.is_dead ~= true or active.kind_id ~= row.kind_id
            or active.inherit_id ~= row.inherit_id or active.hp ~= row.hp) then return nil end
        deaths[id] = {kind_id=row.kind_id, inherit_id=row.inherit_id, hp=row.hp, active=row.active,
            is_dead=true, observer_sequence=row.observer_sequence, observed_at=row.observed_at}
        count = count + 1
    end
    return deaths
end

local function read_local(receipt, now, previous)
    local load = receipt.load
    local campaign_mode = receipt.campaign_attempt ~= nil
    local name = campaign_mode and 're2_coop_campaign_enemy_state.json' or 're2_coop_enemy_state.json'
    local native = read_document(name, max_native)
    if not native or native.schema ~= 1 or native.source ~= 're2' or native.tdb ~= 70
        or native.scope ~= 'registered_and_stored_enemy_contexts' or native.available ~= true
        or native.reason ~= 'ok' or not fresh(native.observed_at, now)
        or type(native.state) ~= 'table' then
        return nil, 'native_unavailable'
    end
    if native.run_id ~= load.observer_run_id or not integer(native.sequence, load.observer_sequence, max_integer)
        or not same_checkpoint(load.checkpoint, native.state.checkpoint) then
        return nil, 'native_observation_changed'
    end
    if campaign_mode and not campaign.same_area(receipt.view.campaign_area, native.state.campaign_area) then
        return nil, 'native_campaign_area_changed'
    end
    local guard = read_document('re2_coop_save_guard.json', max_guard)
    if not guard or guard.schema ~= 1 or guard.active ~= true or guard.hooks ~= 26 or not fresh(guard.at, now)
        or guard.load_request_id ~= load.request_id or guard.policy_id ~= load.request_id
        or guard.load_phase ~= 'scene_loaded' or guard.load_error ~= '' or guard.denied_loads ~= 0
        or not integer(guard.allowed_load_calls, 1, max_integer)
        or (not campaign_mode and guard.writes ~= nil
            and (type(guard.writes) ~= 'table' or next(guard.writes) ~= nil))
        or guard.load_index ~= load.slot_id or guard.allowed_slot ~= load.slot_id
        or not integer(guard.load_started_at, 1, native.observed_at - 1) then
        return nil, 'guard_unavailable'
    end

    local binding = {request_id=load.request_id, slot_id=load.slot_id, run_id=native.run_id,
        started_at=guard.load_started_at, load_calls=guard.allowed_load_calls,
        checkpoint={game_guid=load.checkpoint.game_guid, save_guid=load.checkpoint.save_guid,
            scenario=load.checkpoint.scenario, location=load.checkpoint.location},
        sequence=native.sequence, observed_at=native.observed_at}
    if previous then
        if binding.request_id ~= previous.request_id or binding.slot_id ~= previous.slot_id
            or binding.run_id ~= previous.run_id or binding.started_at ~= previous.started_at
            or binding.load_calls ~= previous.load_calls or not same_checkpoint(binding.checkpoint, previous.checkpoint) then
            return nil, 'native_load_changed'
        end
        if binding.sequence < previous.sequence or binding.observed_at < previous.observed_at then
            return nil, 'native_observation_changed'
        end
    elseif not campaign_mode and now - guard.load_started_at > 120 then
        return nil, 'guard_unavailable'
    end

    local count, active_count, entries = native.state.registered_count, native.state.active_count, native.state.entries
    if not integer(count, 0, max_enemies) or not integer(active_count, 0, count) then
        return nil, 'invalid_native_entries'
    end
    if count == 0 and entries == nil then entries = {} end
    if type(entries) ~= 'table' then return nil, 'invalid_native_entries' end
    local seen, active, total, active_total = {}, {}, 0, 0
    for i, row in pairs(entries) do
        if not integer(i, 1, count) or type(row) ~= 'table' or not guid(row.id) or seen[row.id]
            or not integer(row.kind_id, min_signed, max_signed) or type(row.live) ~= 'table'
            or type(row.live.present) ~= 'boolean' then
            return nil, 'invalid_native_entries'
        end
        total, seen[row.id] = total + 1, true
        local live = row.live
        if live.present then
            if type(live.active) ~= 'boolean' or not live_values(live) then return nil, 'invalid_native_entries' end
            if live.active then active[row.id], active_total = row, active_total + 1 end
        end
    end
    if total ~= count or active_total ~= active_count then return nil, 'invalid_native_entries' end
    return active, nil, binding
end

local function observe(now, tracker, scope)
    if tracker.newest_clock and now < tracker.newest_clock then return nil, 'clock_moved_backwards' end
    tracker.newest_clock = now
    local receipt, reason = read_receipt(now, tracker, scope)
    if not receipt then return nil, reason end
    local active, local_reason, binding = read_local(receipt, now, tracker.load_binding)
    if not active then return nil, local_reason end
    local rows, eligible, skipped = {}, 0, 0
    for id, host in pairs(receipt.view.enemies) do
        if eligible + skipped >= max_enemies or not guid(id) or not live_values(host)
            or not integer(host.kind_id, min_signed, max_signed)
            or not integer(host.default_hp, min_signed, max_signed) then
            return nil, 'invalid_host_entries'
        end
        local candidate = active[id]
        if candidate and candidate.kind_id == host.kind_id and candidate.live.inherit_id == host.inherit_id then
            local current = candidate.live
            rows[id] = {kind_id=host.kind_id, inherit_id=host.inherit_id, host_hp=host.hp, local_hp=current.hp,
                host_is_live=host.is_live, local_is_live=current.is_live,
                host_is_dead=host.is_dead, local_is_dead=current.is_dead}
            eligible = eligible + 1
        else
            skipped = skipped + 1
        end
    end
    local state = {session_id=receipt.session_id, sequence=receipt.sequence,
        eligible=eligible, skipped=skipped, enemies=rows}
    if receipt.view.death_observations ~= nil then
        state.host_death_observations = read_host_deaths(receipt.view)
        if not state.host_death_observations then return nil, 'invalid_host_death_observations' end
    end
    tracker.load_binding = binding
    return state, 'ok', receipt
end

local function publish(state, reason, now, last_application, campaign_mode)
    local name = campaign_mode and 're2_coop_campaign_enemy_readback.json' or output_name
    pcall(json.dump_file, name, {schema=1, source='re2', tdb=70,
        scope='guest_enemy_readback', observed_at=now, available=state ~= nil, reason=reason, state=state,
        last_application=last_application})
end

local installed = {}

function M.install(applier, options)
    if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end
    local campaign_mode = options and options.campaign == true or false
    local registration = installed[campaign_mode]
    if registration then
        if applier then registration.apply = applier end
        return
    end
    if campaign_mode then campaign = require('re2_coop.campaign_pose_scope') end
    local application_failed
    registration = {apply=applier}
    installed[campaign_mode] = registration
    local tracker, frames = {}, 0
    re.on_pre_application_entry('UpdateBehavior', function()
        frames = frames + 1
        if frames % 6 ~= 0 then return end
        local now = os.time()
        local scope
        if campaign_mode then
            scope = campaign.read_release()
            if not scope or scope.role ~= 'G' or not campaign.peer_matches(scope) then
                if tracker.attempt then
                    publish(nil, 'campaign_scope_unavailable', now, tracker.last_application, true)
                    tracker = {}
                end
                return
            end
            if tracker.attempt ~= scope.attempt_id then tracker = {attempt=scope.attempt_id} end
        end
        local ok, state, reason, receipt = pcall(observe, now, tracker, scope)
        if not ok then state, reason = nil, 'readback_failed' end
        if state and registration.apply then
            if not application_failed then
                local function record_write(id, values)
                    local evidence = tracker.last_application
                    local host_sequence = receipt.view.observer_sequence
                    if not evidence or evidence.session_id ~= receipt.session_id
                        or evidence.generation ~= receipt.generation
                        or evidence.host_observer_sequence ~= host_sequence then
                        evidence = {session_id=receipt.session_id, generation=receipt.generation,
                            host_observer_sequence=host_sequence, applied=0, enemies={}}
                        tracker.last_application = evidence
                    end
                    evidence.receipt_sequence, evidence.applied_at = receipt.sequence, os.time()
                    values.receipt_sequence, values.applied_at = evidence.receipt_sequence, evidence.applied_at
                    if not evidence.enemies[id] then evidence.applied = evidence.applied + 1 end
                    evidence.enemies[id] = values
                end
                local applied, result = pcall(registration.apply, state, receipt, record_write)
                if applied then state.application = result else application_failed = true end
            end
            if application_failed then state.application = {reason='disabled_after_error'} end
        end
        publish(state, reason, now, tracker.last_application, campaign_mode)
    end)
    re.on_script_reset(function() publish(nil, 'script_reset', os.time(), tracker.last_application, campaign_mode) end)
end

M.same_checkpoint = same_checkpoint
M.fresh = fresh
return M
