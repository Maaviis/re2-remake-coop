-- Only the guest's current native inventory is writable, after both games have released the campaign.
if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end
local campaign = require('re2_coop.campaign_pose_scope')
local equipment = require('re2_coop.guest_equipment')
local reader_run = string.format('equipment-%d-%.6f', os.time(), os.clock())
local reader, applied_lease, failed_lease, active_request
local deferred_state
local last_check, last_state, last_reason, last_write = 0, nil, nil, nil
local local_file = 're2_coop_equipment_local.json'
local restore_file = 're2_coop_equipment_restore.json'

local function report(reason)
    if reason ~= last_reason then
        last_reason = reason
        if reason then log.info('RE2_COOP_GUEST_EQUIPMENT ' .. tostring(reason)) end
    end
end

local function current_scope()
    local scope = campaign.read_release()
    if not scope or not scope.equipment_namespace or not campaign.peer_matches(scope) then return end
    local observed = campaign.observed_context(scope)
    if not observed then return end
    local players = sdk.get_managed_singleton('app.ropeway.PlayerManager')
    local player = players and players:call('get_CurrentPlayer')
    if player and observed.player_address == player:get_address() and observed.scene_address == campaign.scene_address()
        and campaign.same_area(observed.area, campaign.read_area()) then return scope end
end

local function command_for(scope, now, state)
    local ok, bytes = pcall(fs.read, restore_file)
    if not ok or type(bytes) ~= 'string' or #bytes == 0 or #bytes > 20480 then return end
    local decoded, c = pcall(json.load_string, bytes)
    if decoded and type(c) == 'table' and c.schema == 1 and c.pid == scope.game_pid and c.role == 'G'
        and c.reader_run == reader_run
        and c.session == scope.session_id and c.attempt == scope.attempt_id and c.request == scope.request_id
        and c.snapshot_epoch == scope.snapshot_epoch and c.revision == scope.revision
        and c.namespace == scope.equipment_namespace and math.type(c.at) == 'integer' and c.at <= now and now-c.at <= 2
        and type(c.lease) == 'string' and #c.lease == 32 and c.lease:match('^[a-f0-9]+$')
        and c.lease ~= applied_lease and (c.lease ~= failed_lease or deferred_state and deferred_state ~= state)
        and equipment.valid(c.equipment) then return c end
end

local function tick()
    local scope = current_scope()
    local now = os.time()
    if not scope then
        failed_lease, deferred_state = nil, nil
        if last_state then
            json.dump_file(local_file, {schema=1, at=now, available=false})
            last_state = nil
        end
        return
    end
    if scope.request_id ~= active_request then
        active_request, applied_lease, failed_lease, deferred_state, last_state = scope.request_id, nil, nil, nil, nil
    end
    if not reader then reader = equipment.new() end
    local state, reason = reader.capture()
    if not state then report(reason); return end
    if scope.role == 'G' then
        local command = command_for(scope, now, state)
        if command then
            local applied, why = reader.apply(command.equipment)
            if not applied then
                failed_lease = command.lease
                deferred_state = tostring(why):find('equipment_layout_requires_campaign_load',1,true) and state or nil
                report(why)
                return
            end
            -- The native backend compares the full readback before returning success.
            applied_lease, state, last_state = command.lease, command.equipment, nil
            failed_lease, deferred_state = nil, nil
            report('guest_restore_verified')
        end
    end
    if state == last_state and last_write == now then return end
    if json.dump_file(local_file, {schema=1, at=now, pid=scope.game_pid, role=scope.role,
            session=scope.session_id, attempt=scope.attempt_id, request=scope.request_id, revision=scope.revision,
            namespace=scope.equipment_namespace, snapshot_epoch=scope.snapshot_epoch, lease=applied_lease,
            reader_run=reader_run, equipment=state}) ~= false then
        last_state, last_write = state, now
    end
end

re.on_pre_application_entry('UpdateBehavior', function()
    local clock = os.clock()
    if clock >= last_check and clock-last_check < .5 then return end
    last_check = clock
    local ok, err = pcall(tick)
    if not ok then report(err) end
end)

if re.on_frame then
    re.on_frame(function()
        if failed_lease then
            local message = deferred_state and 'Gastinventar wartet auf passende Inventarplätze im Koop-Spielstand.'
                or 'Gastinventar konnte nicht geladen werden. Details im REFramework-Log.'
            draw.text(message,
                20, 160, 0xFFFFFFFF)
        end
    end)
end
