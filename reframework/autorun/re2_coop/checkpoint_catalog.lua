-- Refresh metadata after a verified import. This component never requests a game load.
local M = {}
local function hex(value, size)
    return type(value) == 'string' and #value == size and value:match('^[0-9a-f]+$') ~= nil
end
local function equal(a, b)
    return a and b and a.mode == b.mode and a.slot_id == b.slot_id
        and a.timestamp == b.timestamp and a.scenario == b.scenario
end

function M.new()
    local proof, requested, previous
    local update_table, update_pending
    local function methods()
        if update_table then return end
        assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_checkpoint_catalog')
        local service = assert(sdk.find_type_definition('via.storage.saveService.SaveService'))
        local update = assert(service:get_method('updateSaveFileDetailTbl'))
        local args = update:get_param_types()
        assert(update:is_static() and update:get_return_type():get_full_name() == 'System.Void'
            and #args == 1 and args[1]:get_full_name() == 'via.UserIndex', 'unsupported_checkpoint_catalog_update')
        local pending = assert(service:get_method('get_SaveFileDetailUpdateRequest'))
        assert(pending:is_static() and #pending:get_param_types() == 0
            and pending:get_return_type():get_full_name() == 'System.Boolean', 'unsupported_checkpoint_catalog_request')
        update_table, update_pending = update, pending
    end
    local function bound(native, state, now)
        local job = type(native) == 'table' and native.checkpoint_import
        local binding = state.protection or {}
        return type(job) == 'table' and hex(job.request_id, 32) and hex(job.workspace, 32)
            and hex(job.archive_namespace, 32) and hex(job.generation, 64)
            and job.phase == 'ready' and job.file_index == 3 and job.native_result == 1
            and native.schema == 1 and native.source == 'steam_storage_guard' and native.active == true
            and native.reason == 'ok' and native.app_id == 883710 and native.build_id == 11636119
            and native.guarded_methods == 10 and native.interface == '014'
            and math.type(native.at) == 'integer' and now >= native.at and now - native.at <= 3
            and native.game_pid == binding.game_pid and native.run_id == binding.run_id
            and native.campaign_namespace == job.workspace and binding.campaign_namespace == job.workspace
            and state.active == true and state.hooks == 26 and state.protection_active == true
            and state.runtime_protection == true and state.campaign_mount_ready == job.workspace
            and type(state.guard_run_id) == 'string' and state.guard_run_id ~= ''
            and state.in_title == true and state.has_player == false and state.loading_flow == false
            and state.busy == false and state.allowed_load_calls == 0 and state.denied_loads == 0
            and (state.writes == nil or type(state.writes) == 'table' and next(state.writes) == nil)
            and (state.title_open == true or state.main_menu_busy == true)
    end
    local function reference(manager)
        if manager:call('get_IsEnableAccessSaveFileDetailTbl') ~= true then return end
        local detail = manager:call('getSaveFileDetail', 1, 0)
        if not detail or detail:call('get_EmptyData') ~= false then return end
        local stamp = detail:call('get_LastUpdateTimeStamp')
        local scenario = manager:call('getScenarioTypeFromDetailString', detail)
        assert(detail:call('get_Slot') == 0 and math.type(stamp) == 'integer' and stamp > 0
            and (scenario == 0 or scenario == 1), 'checkpoint_catalog_reference_invalid')
        return {mode=1,slot_id=0,timestamp=tostring(stamp),scenario=scenario}
    end
    local function update(native, state, manager, flow, gui, now)
        local valid = bound(native, state, now)
        local job = valid and native.checkpoint_import
        if proof and proof.phase == 'failed' and (not job or job.request_id == proof.request_id) then return end
        if proof and (not valid or job.request_id == proof.request_id and (
            job.workspace ~= proof.workspace or job.archive_namespace ~= proof.archive_namespace
            or job.generation ~= proof.generation or state.guard_run_id ~= proof.guard_run_id
            or state.protection.run_id ~= proof.run_id or state.protection.game_pid ~= proof.game_pid)) then
            error('checkpoint_catalog_binding_changed')
        end
        if not valid then return end
        assert(manager and flow and gui and flow:call('get_IsInTitle') == true
            and flow:call('get_IsInLoadGameData') == false and manager:call('get_IsBusy') == false
            and manager:call('get_IsErrorBusy') == false and gui:call('isBusyLoad') == false
            and gui:call('isBusyMenuStory') == false
            and (gui:call('isTitleMenuOpened') == true or gui:call('isBusyMenuMain') == true),
            'checkpoint_catalog_title_changed')
        local players = sdk.get_managed_singleton('app.ropeway.PlayerManager')
        assert(not players or players:call('get_CurrentPlayer') == nil, 'checkpoint_catalog_player_present')
        if not proof or job.request_id ~= proof.request_id then
            proof = {schema=1,request_id=job.request_id,workspace=job.workspace,archive_namespace=job.archive_namespace,
                generation=job.generation,game_pid=state.protection.game_pid,run_id=state.protection.run_id,
                guard_run_id=state.guard_run_id,phase='refreshing'}
            requested, previous = now, nil
            methods()
            assert(update_pending:call(nil) == false, 'checkpoint_catalog_already_updating')
            update_table:call(nil, 0)
            return
        end
        if proof.phase ~= 'ready' and (now < requested or now - requested > 8) then error('checkpoint_catalog_timeout') end
        local pending = update_pending:call(nil)
        assert(type(pending) == 'boolean', 'checkpoint_catalog_request_invalid')
        if pending then
            assert(proof.phase ~= 'ready', 'checkpoint_catalog_changed_after_confirmation')
            previous = nil
            return
        end
        local current = reference(manager)
        if proof.phase == 'ready' then
            assert(equal(current, proof.reference), 'checkpoint_catalog_changed_after_confirmation')
        elseif current and now > requested then
            if previous and now > previous.at and equal(current, previous.reference) then
                proof.phase, proof.reference = 'ready', current
            end
            previous = {at=now,reference=current}
        else previous = nil end
    end
    return function(native, state, manager, flow, gui, now)
        local ok, reason = pcall(update, native, state, manager, flow, gui, now)
        if not ok and proof then
            proof.phase, proof.reason = 'failed', tostring(reason):match('([^:%s]+)$') or 'checkpoint_catalog_failed'
        end
        if not proof then return end
        -- Copy the result: an old JSON export must never mutate when this job changes.
        local result = {}
        for key, value in pairs(proof) do result[key] = value end
        if proof.reference then
            result.reference = {}
            for key, value in pairs(proof.reference) do result.reference[key] = value end
        end
        result.at = now
        return result
    end
end
return M
