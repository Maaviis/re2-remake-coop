-- Request RE2's regular slot-0 autosave on the protected, released host.
local M = {}

local function slot_stamp(manager)
    if manager:call('get_IsEnableAccessSaveFileDetailTbl') ~= true then error('slot_catalog_unavailable') end
    local detail = manager:call('getSaveFileDetail', 1, 0)
    if not detail or detail:call('get_EmptyData') then return nil end
    if detail:call('get_Slot') ~= 0 then error('slot_identity_changed') end
    local stamp = tostring(detail:call('get_LastUpdateTimeStamp'))
    if not stamp:match('^[1-9]%d*$') or #stamp > 19 then error('slot_timestamp_invalid') end
    return stamp, manager:call('getScenarioTypeFromDetailString', detail)
end

function M.new()
    local active, proof, before, started
    local function update(request, state, manager, flow, now)
        local hold, binding = state.load_hold or {}, state.protection or {}
        local campaign, release = hold.campaign or {}, hold.release or {}
        local function bound(r)
            return state.runtime_protection and state.protection_active and state.active and state.hooks == 26
                and state.in_title == false and state.loading_flow == false and state.scene_finished and state.has_player
                and hold.phase == 'released' and hold.native_phase == 'released' and campaign.role == 'H'
                and hold.load_request_id == r.load_request_id and hold.pause_id == r.load_request_id
                and campaign.game_pid == r.game_pid and binding.game_pid == r.game_pid
                and binding.run_id == campaign.protection_run_id and binding.campaign_namespace == r.namespace
                and state.campaign_mount_ready == r.namespace and release.id == r.release_id
                and release.snapshot_epoch == r.snapshot_epoch and campaign.snapshot_epoch == r.snapshot_epoch
        end
        if active then
            if not bound(active) then error('checkpoint_release_lost') end
            if now < started or now - started > 30 then
                if proof.phase == 'complete' then active = nil; return end
                error('native_autosave_timeout')
            end
            if manager:call('get_IsErrorBusy') then error('native_save_manager_error') end
            if manager:call('get_IsBusy') or now <= started then
                if proof.phase == 'complete' then error('another_native_save_started') end
                return
            end
            local service = sdk.find_type_definition('via.storage.saveService.SaveService')
            if service:get_method('get_LastSaveFailed'):call(nil) ~= false
                or service:get_method('get_LastErrorCode'):call(nil) ~= 0 then error('native_autosave_failed') end
            local stamp, scenario = slot_stamp(manager)
            if proof.phase == 'complete' and stamp ~= proof.timestamp then error('slot_changed_after_save') end
            if stamp and (not before or #stamp > #before or #stamp == #before and stamp > before) then
                if scenario ~= proof.scenario then error('saved_slot_scenario_changed') end
                proof.phase, proof.timestamp = 'complete', stamp
            end
            if proof.phase ~= 'complete' or not request or request.id == active.id then return end
        end
        if type(request) ~= 'table' or type(request.id) ~= 'string' or #request.id ~= 32
            or not request.id:match('^[0-9a-f]+$') or proof and proof.id == request.id
            or math.type(request.at) ~= 'integer' or now < request.at or now - request.at > 4
            or type(request.namespace) ~= 'string' or #request.namespace ~= 32 or not bound(request) then return end
        active, started = request, now
        proof = {id=request.id, phase='saving', slot=0, scenario=campaign.scenario}
        proof.difficulty = flow:call('get_CurrentDifficulty')
        if manager:call('get_IsBusy') ~= false or manager:call('get_IsErrorBusy') ~= false then
            error('native_save_manager_busy')
        end
        if flow:call('get_CurrentScenarioType') ~= proof.scenario then error('checkpoint_scenario_changed') end
        before = slot_stamp(manager)
        if manager:call('requestSaveGameDataAuto') ~= true then error('requestSaveGameDataAuto_rejected') end
    end

    return function(request, state, manager, flow, now)
        local ok, reason = pcall(update, request, state, manager, flow, now)
        if not ok and active then
            proof.phase, proof.reason = 'failed', tostring(reason):match('([^:%s]+)$') or 'native_save_failed'
            active = nil
        end
        return proof
    end
end
return M
