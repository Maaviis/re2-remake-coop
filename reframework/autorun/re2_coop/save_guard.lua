-- RE2 TDB70. Default deny, with native readback for isolated campaign autosaves.
local M = {}
-- REFramework supplies the autorun module search context during initialization.
-- Retain the module; a later native callback may only see Lua's default paths.
local admission_available,checkpoint_admission=pcall(require,'re2_coop.checkpoint_admission')
local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local service_name = 'via.storage.saveService.SaveService'
local solo_mount, standard_directory = './win64_save', 'SAVESERVICE-LINE-0-'
local reference_fields = {mode = true, slot_id = true, timestamp = true, scenario = true}

local function valid_reference(ref)
    if type(ref) ~= 'table' then return false end
    local count = 0
    for field in pairs(ref) do if not reference_fields[field] then return false end; count = count + 1 end
    local ticks = type(ref.timestamp) == 'string' and ref.timestamp:match('^[0-9]+$') and tonumber(ref.timestamp)
    return count == 4 and ref.mode == 1 and math.type(ref.mode) == 'integer'
        and math.type(ref.slot_id) == 'integer' and ref.slot_id >= 0 and ref.slot_id <= 20
        and math.type(ref.scenario) == 'integer' and ref.scenario >= 0 and ref.scenario <= 3
        and ticks and math.type(ticks) == 'integer' and ticks > 0 and tostring(ticks) == ref.timestamp
end

local function signed32(value)
    local integer = sdk.to_int64(value) & 0xffffffff
    return integer >= 0x80000000 and integer - 0x100000000 or integer
end

function M.new(protection)
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_save_guard_build')
    local manager_type = assert(sdk.find_type_definition(manager_name), 'save_manager_type_unavailable')
    local service_type = assert(sdk.find_type_definition(service_name), 'save_service_type_unavailable')
    local skip, original = sdk.PreHookResult.SKIP_ORIGINAL, sdk.PreHookResult.CALL_ORIGINAL
    local zero = sdk.to_ptr(0)
    assert(skip ~= nil and original ~= nil and thread and type(thread.get_hook_storage) == 'function')
    local self = {active = false, hook_count = 0, policy = nil, writes = {}, denied_loads = 0, allowed_load_calls = 0, events = {},
        protection = protection or require('re2_coop.save_protection').new()}
    local prepared, permitted_slot = {}, nil
    local mount_api, mounted, pending_save, previous_mount
    local checkpoint, checkpoint_ids, checkpoint_count = nil, {}, 0

    local function mount_methods()
        local function resolve(name, result, parameter)
            local method = assert(service_type:get_method(name))
            local params = method:get_param_types()
            assert(method:is_static() and method:get_return_type():get_full_name() == result
                and #params == (parameter and 1 or 0) and (not parameter or params[1]:get_full_name()==parameter))
            return method
        end
        return {instance=resolve('hasInstance','System.Boolean'),
            path=resolve('get_SaveMountPath','System.String'), directory=resolve('get_SaveDirectoryPath','System.String'),
            state=resolve('get_SaveState','via.storage.saveService.SaveState'),
            set=resolve('set_SaveMountPath','System.Void','System.String')}
    end

    local function current_path()
        if mount_api.instance:call(nil) == true and mount_api.directory:call(nil) == standard_directory then
            return mount_api.path:call(nil)
        end
    end

    local function idle_title(allow_title_screen)
        local flow = sdk.get_managed_singleton('app.ropeway.gamemastering.MainFlowManager')
        local gui = sdk.get_managed_singleton('app.ropeway.gui.GUIMaster')
        local manager = sdk.get_managed_singleton(manager_name)
        local players = sdk.get_managed_singleton('app.ropeway.PlayerManager')
        return flow and manager and gui and flow:call('get_IsInTitle') == true and flow:call('get_Title') ~= nil
            and flow:call('get_IsInLoadGameData') == false and manager:call('get_IsBusy') == false
            and manager:call('get_IsErrorBusy') == false and mount_api.state:call(nil) == 1
            and (not players or players:call('get_CurrentPlayer') == nil)
            and gui:call('isBusyLoad') == false and gui:call('isBusyMenuStory') == false
            and gui:call('isBusyMenuScenario') == false and gui:call('isBusySelectDifficulty') == false
            and (gui:call('isTitleMenuOpened') == true or gui:call('isBusyMenuMain') == true
                or allow_title_screen and flow:call('get_IsTitleSceneEnvironmentLoaded') == true)
    end

    function self:campaign_ready(binding, cached)
        if not self.active or not mounted or mounted.retired or not binding or mounted.run_id ~= binding.run_id
            or mounted.game_pid ~= binding.game_pid or mounted.campaign_namespace ~= binding.campaign_namespace
            then return false end
        if cached then
            if not self.protection:matches(mounted) then return false end
        elseif not self.protection:campaign_matches(mounted) then return false end
        local ok, path = pcall(current_path)
        return ok and path == './coop-save-'..mounted.campaign_namespace
    end

    local function sync_mount(can_switch)
        local current = self.protection.current
        local token = current and current.campaign_namespace
        if token then self.campaign_mode = true end
        if not self.active or not self.campaign_mode then return end
        if self:campaign_ready(current) then return token end
        pending_save = nil
        if not can_switch then return end
        mount_api = mount_api or mount_methods()
        if not idle_title() then return end
        local path = current_path()
        if not path then return end
        if mounted and (mounted.retired or not self.protection:campaign_matches(mounted)) then
            if path == './coop-save-'..mounted.campaign_namespace then
                mount_api.set:call(nil,solo_mount)
                path = current_path()
            end
            if path == solo_mount then previous_mount, mounted = mounted, nil end
            return
        end
        if not token or path ~= solo_mount or not self.protection:campaign_matches(current) then return end
        -- Record ownership before the setter, which may apply and then throw.
        previous_mount = nil
        mounted = {game_pid=current.game_pid,run_id=current.run_id,campaign_namespace=token}
        mount_api.set:call(nil,'./coop-save-'..token)
        if self:campaign_ready(current) then return token end
    end

    function self:sync_campaign_mount(can_switch)
        local ok, token = pcall(sync_mount,can_switch)
        if ok then return token end
    end

    -- Native revocation ends the old authority. Mount changes and new admissions
    -- still wait for the interactive title menu.
    -- All 26 native hooks stay active. An unrelated denial still requires recovery.
    function self:retire_campaign(world, peer, now)
        local current = self.protection.current
        local old_mount = mounted or previous_mount
        if not old_mount or old_mount.retired or not self.active or self.hook_count ~= 26
            or not self.protection:ready() or not current or not current.runtime or current.campaign_namespace
            or old_mount.campaign_namespace ~= world.namespace or current.game_pid ~= world.game_pid
            or current.run_id ~= world.run_id or old_mount.run_id ~= current.run_id
            or old_mount.game_pid ~= current.game_pid or type(peer) ~= 'table' or peer.schema ~= 1
            or peer.game_pid ~= current.game_pid or math.type(peer.revision) ~= 'integer'
            or peer.revision <= 0 or peer.revision == world.revision or math.type(peer.at) ~= 'integer'
            or now < peer.at or now-peer.at > 3 or self.denied_loads ~= 0
            or self.allowed_load_calls ~= world.allowed_load_calls then return end
        for name in pairs(self.writes) do
            if name ~= manager_name..'.saveGameSaveData'
                and name ~= manager_name..'.requestSaveSystemDataNoSaveIcon' then return end
        end
        local expected_mount = mounted and './coop-save-'..world.namespace or solo_mount
        if current_path() ~= expected_mount or not idle_title(true) then return end
        local history = {writes=self.writes, allowed_load_calls=self.allowed_load_calls,
            denied_loads=self.denied_loads, revision=world.revision, next_revision=peer.revision}
        old_mount.retired = true
        previous_mount, pending_save, checkpoint, permitted_slot, self.policy = nil, nil, nil, nil, nil
        self.writes, self.allowed_load_calls = {}, 0
        return history
    end

    local function event(name, mode, slot, decision)
        self.events[#self.events + 1] = {method = name, mode = mode, slot = slot, decision = decision}
        if #self.events > 32 then table.remove(self.events, 1) end
    end

    local function prepare(def, signature, returns, static, kind)
        local method = assert(def:get_method(signature), 'missing_save_guard_method:' .. signature)
        assert(method:get_return_type():get_full_name() == returns and method:is_static() == static,
            'unexpected_save_guard_signature:' .. signature)
        prepared[#prepared + 1] = {method = method, name = def:get_full_name() .. '.' .. signature,
            kind = kind, signature = signature, returns = returns}
    end

    -- Validate the complete set before queuing any hook.
    for _, signature in ipairs({'requestSaveSystemData', 'requestSaveSystemDataNoSaveIcon',
            'requestSaveGameData', 'requestSaveRogueSystemData', 'requestSaveRogueSystemDataNoSaveIcon',
            'requestSaveGameDataAuto', 'requestSaveGameDataRogueAuto', 'requestRemoveGameData',
            'requestRemoveAllGameData'}) do
        prepare(manager_type, signature, 'System.Boolean', false, 'write')
    end
    for _, signature in ipairs({'saveSystemSaveData', 'saveGameSaveData', 'saveRogueSystemSaveData'}) do
        prepare(manager_type, signature, 'System.Void', false, 'write')
    end
    for _, signature in ipairs({'saveSingle()', 'saveSingle(System.Int32)', 'saveSlotDialog',
            'removeAllSlot', 'removeSingle()', 'removeSingle(System.Int32)', 'removeSlotDialog', 'deleteData'}) do
        prepare(service_type, signature, 'System.Boolean', true, 'write')
    end
    prepare(manager_type, 'requestLoadGameData', 'System.Boolean', false, 'manager_load')
    for _, signature in ipairs({'requestLoadLatestGameData', 'requestLoadLastUseGameDataSenario'}) do
        prepare(manager_type, signature, 'System.Boolean', false, 'ambiguous_load')
    end
    prepare(service_type, 'loadSingle(System.Int32)', 'System.Boolean', true, 'service_load')
    prepare(service_type, 'loadSingle()', 'System.Boolean', true, 'ambiguous_load')
    prepare(service_type, 'loadSlotDialog', 'System.Boolean', true, 'ambiguous_load')

    local function matches_native(ref)
        local manager = sdk.get_managed_singleton(manager_name)
        if not manager or manager:call('get_IsBusy') or not manager:call('get_IsEnableAccessSaveFileDetailTbl') then return false end
        local detail = manager:call('getSaveFileDetail', 1, ref.slot_id)
        return detail ~= nil and not detail:call('get_EmptyData')
            and detail:call('get_Slot') == ref.slot_id
            and tostring(detail:call('get_LastUpdateTimeStamp')) == ref.timestamp
            and manager:call('getScenarioTypeFromDetailString', detail) == ref.scenario
    end

    function self:allow(ref)
        assert(self.protection:poll(), 'protected_launch_required')
        assert(not self.campaign_mode and not self.protection.current.campaign_namespace, 'isolated_new_game_required')
        assert(self.active and valid_reference(ref) and matches_native(ref), 'save_reference_not_available')
        self.policy = {mode = 1, slot_id = ref.slot_id, timestamp = ref.timestamp, scenario = ref.scenario}
        permitted_slot = nil
    end

    function self:allow_checkpoint(ref, preparation_id, guard_run_id)
        assert(self.protection:poll() and self.active and self.hook_count==26, 'protected_launch_required')
        assert(self.campaign_mode and self.allowed_load_calls==0 and self.denied_loads==0
            and self.policy==nil and next(self.writes)==nil and checkpoint_count<128,
            'checkpoint_admission_not_pristine')
        assert(valid_reference(ref) and ref.slot_id==0 and idle_title() and matches_native(ref),
            'checkpoint_reference_not_available')
        assert(not checkpoint_ids[preparation_id], 'checkpoint_preparation_already_used')
        assert(admission_available,'checkpoint_admission_module_unavailable')
        local binding=checkpoint_admission.read(self,ref,preparation_id,guard_run_id,os.time())
        checkpoint_ids[preparation_id],checkpoint_count=true,checkpoint_count+1
        local original_ref={mode=ref.mode,slot_id=ref.slot_id,timestamp=ref.timestamp,scenario=ref.scenario}
        checkpoint={id=preparation_id,binding=binding,reference=original_ref,phase='armed',at=os.time(),before=os.time()+10}
        self.policy={mode=ref.mode,slot_id=ref.slot_id,timestamp=ref.timestamp,scenario=ref.scenario}
        permitted_slot=nil
    end

    function self:revoke_checkpoint(preparation_id)
        if not checkpoint or checkpoint.id~=preparation_id then return false end
        checkpoint,self.policy,permitted_slot=nil,nil,nil
        return true
    end

    local function checkpoint_current()
        if not checkpoint then return false end
        local now=os.time()
        if not self.policy or now<checkpoint.at or now>=checkpoint.before or self.denied_loads~=0
            or not self:campaign_ready(checkpoint.binding) or self.policy.mode~=1 or self.policy.slot_id~=0
            or self.policy.timestamp~=checkpoint.reference.timestamp or self.policy.scenario~=checkpoint.reference.scenario then
            self:revoke_checkpoint(checkpoint.id)
            return false
        end
        return true
    end

    local activation_started = false
    local function request_receiver(args)
        local receiver = sdk.to_managed_object(args[2])
        local manager = sdk.get_managed_singleton(manager_name)
        if receiver and manager and receiver:get_address() == manager:get_address() then return receiver end
    end
    local function current_request(ticket)
        if not ticket or ticket.binding ~= mounted then return false end
        local age = os.time() - ticket.at
        return age >= 0 and age <= 3
    end
    local function save_queue(manager, queued, slot)
        return manager:get_field('SaveRequest') == queued and manager:call('get_saveLoadStep') == 1
            and manager:get_field('LoadRequest') == false and manager:get_field('RemoveRequest') == false
            and manager:get_field('RemoveAllRequest') == false and manager:call('get_IsErrorBusy') == false
            and (not queued or manager:get_field('SlotId') == slot)
    end

    -- The native gas-station action queues slot 0 directly. Observe the edge inside
    -- its original call. A busy manager or a worker alone cannot create permission.
    local function observe_checkpoint_queue()
        local def = sdk.find_type_definition('app.ropeway.fsmv2.SaveCheckpointForce')
        local method = def and def:get_method('update')
        if not method or method:is_static() or method:get_return_type():get_full_name() ~= 'System.Void' then return end
        local params = method:get_param_types()
        if #params ~= 1 or params[1]:get_full_name() ~= 'via.behaviortree.ActionArg' then return end
        sdk.hook(method, function()
            if pending_save and not current_request(pending_save) then pending_save = nil end
            if mounted and not mounted.retired and not pending_save and self.protection:matches(mounted) then
                pcall(function()
                    local manager = sdk.get_managed_singleton(manager_name)
                    if manager and manager:call('get_IsBusy') == false and save_queue(manager,false) then
                        thread.get_hook_storage().re2_coop_queue = {binding=mounted,receiver=manager:get_address()}
                    end
                end)
            end
            return original
        end, function(retval)
            local ticket = thread.get_hook_storage().re2_coop_queue
            if ticket and not pending_save and ticket.binding == mounted then
                pcall(function()
                    local manager = sdk.get_managed_singleton(manager_name)
                    if manager and manager:get_address() == ticket.receiver and save_queue(manager,true,0)
                        and self:campaign_ready(mounted) then
                        ticket.at, ticket.phase, ticket.native_queue = os.time(), 'saveGameSaveData', true
                        pending_save = ticket
                    end
                end)
            end
            return retval
        end)
    end

    local function campaign_write(signature, args)
        if not mounted or not self:campaign_ready(mounted) then
            pending_save = nil
            return false
        end
        if signature == 'saveSingle(System.Int32)' then
            local slot = signed32(args[2])
            if slot == -1 or slot == 0 then return true end
        end
        local ticket = pending_save
        pending_save = nil
        if signature == 'requestSaveGameDataAuto' or signature == 'requestSaveSystemData' then
            local receiver = request_receiver(args)
            if not receiver or receiver:call('get_IsBusy') ~= false then return false end
            local expected = signature == 'requestSaveGameDataAuto' and 'saveGameSaveData' or 'saveSystemSaveData'
            pending_save = {binding=mounted, receiver=receiver:get_address(), at=os.time(), next_method=expected}
            if signature == 'requestSaveSystemData' and checkpoint and self.policy and self.policy.slot_id == 0
                and (checkpoint.phase == 'requested' or checkpoint.phase == 'read')
                and self.allowed_load_calls > 0 and self.denied_loads == 0
                and receiver:call('get_SaveGameDataIndex') == 0 then
                pending_save.loaded_profile = checkpoint
            end
            thread.get_hook_storage().re2_coop_save_request = pending_save
            return true
        end
        if not current_request(ticket) or ticket.phase ~= signature then return false end
        local receiver = request_receiver(args)
        if not receiver or receiver:get_address() ~= ticket.receiver then return false end
        if ticket.native_queue then
            if not save_queue(receiver,true,0) then return false end
            ticket.native_queue = nil
        end
        local busy = receiver:call('get_IsBusy')
        local index = receiver:call('get_SaveGameDataIndex')
        -- After loading checkpoint 0 the scenario index stays 0 while the
        -- profile writer targets -1, followed by the skipped rogue slot 21.
        local loaded_profile = index == 0 and checkpoint and ticket.loaded_profile == checkpoint
        if busy == true and (signature == 'saveGameSaveData' and index == -1
            or signature == 'saveSystemSaveData' and (index == -1 or loaded_profile and save_queue(receiver,true,-1))) then
            -- TDB70 reports -1 inside the busy autosave worker. The scenario
            -- slot 0 is visible later in metadata. The accepted request
            -- above distinguishes this worker from a manual or rogue save.
            ticket.phase = nil
            ticket.next_method = signature == 'saveGameSaveData' and 'requestSaveSystemDataNoSaveIcon' or 'saveRogueSystemSaveData'
            pending_save = ticket
            thread.get_hook_storage().re2_coop_save_worker = ticket
            return true
        end
        if signature == 'requestSaveSystemDataNoSaveIcon' and busy == false and index == -1 then
            ticket.phase, ticket.next_method = nil, 'saveSystemSaveData'
            pending_save = ticket
            thread.get_hook_storage().re2_coop_save_request = ticket
            return true
        end
        if signature == 'saveRogueSystemSaveData' and busy == true
            and (index == -1 or loaded_profile and save_queue(receiver,true,21)) then
            return false, 'skipped_system_companion'
        end
        return false
    end
    function self:activate()
        if self.active then return true end
        if activation_started or not self.protection:ready() then return false end
        activation_started = true
        for _, spec in ipairs(prepared) do
            sdk.hook(spec.method, function(args)
                local allowed, mode, slot, decision = false, nil, nil, nil
                if spec.kind == 'write' then
                    local ok, result, reason = pcall(campaign_write, spec.signature, args)
                    allowed = ok and result
                    decision = ok and reason or nil
                elseif spec.kind == 'manager_load' then
                    local ok = pcall(function()
                        mode, slot = signed32(args[3]), signed32(args[4])
                        if checkpoint then
                            allowed=self.active and checkpoint_current() and checkpoint.phase=='armed'
                                and request_receiver(args)~=nil and mode==1 and slot==0 and matches_native(self.policy)
                            if allowed then
                                checkpoint.phase='manager'
                                thread.get_hook_storage().re2_coop_checkpoint_load=checkpoint
                            end
                        else
                            allowed = self.active and not self.campaign_mode and self.protection:ready() and self.policy ~= nil and mode == 1 and slot == self.policy.slot_id
                                and matches_native(self.policy)
                        end
                        if allowed then permitted_slot = slot end
                    end)
                    allowed = ok and allowed
                elseif spec.kind == 'service_load' then
                    local ok = pcall(function()
                        slot = signed32(args[2])
                        -- -1 is RE2's system/profile slot, confirmed by getSaveDataIndex(SYSTEM, 0).
                        if checkpoint and slot~=-1 then
                            allowed=self.active and checkpoint_current() and slot==0 and permitted_slot==0
                                and (checkpoint.phase=='manager' or checkpoint.phase=='requested')
                            if allowed then checkpoint.phase='read';permitted_slot=nil end
                        else
                            allowed = slot == -1 or self.active and not self.campaign_mode and self.protection:ready() and self.policy ~= nil
                                and slot == self.policy.slot_id and permitted_slot == slot
                        end
                    end)
                    allowed = ok and allowed
                end
                thread.get_hook_storage().re2_coop_save_blocked = not allowed
                if spec.kind == 'write' then
                    if not allowed and not decision then self.writes[spec.name] = (self.writes[spec.name] or 0) + 1 end
                elseif not allowed then self.denied_loads = self.denied_loads + 1
                else self.allowed_load_calls = self.allowed_load_calls + 1 end
                event(spec.name, mode, slot, decision)
                return allowed and original or skip
            end, function(retval)
                local invocation = thread.get_hook_storage()
                if invocation.re2_coop_save_blocked then return zero end
                local load_ticket=invocation.re2_coop_checkpoint_load
                if load_ticket and checkpoint==load_ticket then
                    local ok,result=pcall(sdk.to_int64,retval)
                    if not ok or math.type(result)~='integer' or (result & 0xff)~=1 then
                        self:revoke_checkpoint(load_ticket.id)
                    elseif checkpoint.phase=='manager' then checkpoint.phase='requested' end
                end
                local ticket = invocation.re2_coop_save_request
                if ticket and pending_save == ticket then
                    local ok, result = pcall(sdk.to_int64, retval)
                    if ok and math.type(result) == 'integer' and (result & 0xff) == 1 then
                        ticket.phase = ticket.next_method
                    else
                        pending_save = nil
                    end
                end
                local worker = invocation.re2_coop_save_worker
                if worker and pending_save == worker then worker.phase = worker.next_method end
                return retval
            end)
        end
        observe_checkpoint_queue()
        self.hook_count, self.active = #prepared, true
        return true
    end
    return self
end

return M
