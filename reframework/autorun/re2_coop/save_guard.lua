-- Opt-in RE2 test guard. Does not load a game, change a slot, or write save data.
local M = {}
local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local service_name = 'via.storage.saveService.SaveService'
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

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_save_guard_build')
    local manager_type = assert(sdk.find_type_definition(manager_name), 'save_manager_type_unavailable')
    local service_type = assert(sdk.find_type_definition(service_name), 'save_service_type_unavailable')
    local skip, original = sdk.PreHookResult.SKIP_ORIGINAL, sdk.PreHookResult.CALL_ORIGINAL
    local zero = sdk.to_ptr(0)
    assert(skip ~= nil and original ~= nil and thread and type(thread.get_hook_storage) == 'function')
    local self = {active = false, policy = nil, writes = {}, denied_loads = 0, allowed_load_calls = 0, events = {}}
    local prepared, permitted_slot = {}, nil

    local function event(name, mode, slot)
        self.events[#self.events + 1] = {method = name, mode = mode, slot = slot}
        if #self.events > 32 then table.remove(self.events, 1) end
    end

    local function prepare(def, signature, returns, static, kind)
        local method = assert(def:get_method(signature), 'missing_save_guard_method:' .. signature)
        assert(method:get_return_type():get_full_name() == returns and method:is_static() == static,
            'unexpected_save_guard_signature:' .. signature)
        prepared[#prepared + 1] = {method = method, name = def:get_full_name() .. '.' .. signature,
            kind = kind, returns = returns}
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
        assert(self.active and valid_reference(ref) and matches_native(ref), 'save_reference_not_available')
        self.policy = {mode = 1, slot_id = ref.slot_id, timestamp = ref.timestamp, scenario = ref.scenario}
        permitted_slot = nil
    end

    for _, spec in ipairs(prepared) do
        sdk.hook(spec.method, function(args)
            local allowed, mode, slot = false, nil, nil
            if spec.kind == 'manager_load' then
                local ok = pcall(function()
                    mode, slot = signed32(args[3]), signed32(args[4])
                    allowed = self.active and self.policy ~= nil and mode == 1 and slot == self.policy.slot_id
                        and matches_native(self.policy)
                    if allowed then permitted_slot = slot end
                end)
                allowed = ok and allowed
            elseif spec.kind == 'service_load' then
                local ok = pcall(function()
                    slot = signed32(args[2])
                    -- -1 is RE2's system/profile slot, confirmed by getSaveDataIndex(SYSTEM, 0).
                    allowed = slot == -1 or self.active and self.policy ~= nil
                        and slot == self.policy.slot_id and permitted_slot == slot
                end)
                allowed = ok and allowed
            end
            thread.get_hook_storage().re2_coop_save_blocked = not allowed
            if spec.kind == 'write' then self.writes[spec.name] = (self.writes[spec.name] or 0) + 1
            elseif not allowed then self.denied_loads = self.denied_loads + 1
            else self.allowed_load_calls = self.allowed_load_calls + 1 end
            event(spec.name, mode, slot)
            return allowed and original or skip
        end, function(retval)
            if thread.get_hook_storage().re2_coop_save_blocked then return zero end
            return retval
        end)
    end
    self.hook_count, self.active = #prepared, true
    return self
end

return M
