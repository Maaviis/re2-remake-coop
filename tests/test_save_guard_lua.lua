local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local service_name = 'via.storage.saveService.SaveService'
local hooks, storage, busy, accessible, current_timestamp, current_scenario = {}, {}, false, true, '639300360000000000', 1
local originals = 0
local defs = {}
for _, name in ipairs({manager_name, service_name}) do
    defs[name] = {
        get_full_name = function() return name end,
        get_method = function(_, signature)
            local ret = name == manager_name and signature:match('^save') and 'System.Void' or 'System.Boolean'
            return {name = name .. '.' .. signature, get_return_type = function() return {get_full_name = function() return ret end} end,
                is_static = function() return name == service_name end}
        end,
    }
end
local detail = {call = function(_, method)
    if method == 'get_EmptyData' then return false end
    if method == 'get_Slot' then return 4 end
    if method == 'get_LastUpdateTimeStamp' then return tonumber(current_timestamp) end
    error('unexpected detail call: ' .. method)
end}
local manager = {call = function(_, method, mode, slot)
    if method == 'get_IsBusy' then return busy end
    if method == 'get_IsEnableAccessSaveFileDetailTbl' then return accessible end
    if method == 'getSaveFileDetail' then assert(mode == 1 and slot == 4); return detail end
    if method == 'getScenarioTypeFromDetailString' then return current_scenario end
    error('unexpected manager call: ' .. method)
end}
reframework = {get_game_name = function() return 're2' end}
thread = {get_hook_storage = function() return storage[#storage] end}
sdk = {
    get_tdb_version = function() return 70 end,
    find_type_definition = function(name) return defs[name] end,
    to_ptr = function(value) return value end,
    to_int64 = function(value) assert(type(value) == 'number'); return value end,
    get_managed_singleton = function(name) assert(name == manager_name); return manager end,
    PreHookResult = {CALL_ORIGINAL = 1, SKIP_ORIGINAL = 2},
    hook = function(method, pre, post) hooks[method.name] = {pre = pre, post = post} end,
}
local guard = dofile('reframework/autorun/re2_coop/save_guard.lua').new()
assert(guard.active and guard.hook_count == 26)
local function call(name, args, original)
    storage[#storage + 1] = {}
    local hook = assert(hooks[name])
    local choice = hook.pre(args or {})
    local value = 999
    if choice == sdk.PreHookResult.CALL_ORIGINAL then originals = originals + 1; value = original and original() or 77
    else assert(choice == sdk.PreHookResult.SKIP_ORIGINAL) end
    value = hook.post(value)
    table.remove(storage)
    return value
end
for name in pairs(hooks) do
    if name:find('requestSave', 1, true) or name:find('.save', 1, true)
        or name:find('remove', 1, true) or name:find('Remove', 1, true) or name:find('delete', 1, true) then
        assert(call(name) == 0, 'write entry point did not reject: ' .. name)
    end
end
assert(originals == 0, 'a protected write reached its original body')
local manager_load = manager_name .. '.requestLoadGameData'
local service_load = service_name .. '.loadSingle(System.Int32)'
assert(call(manager_load, {nil, {}, 1, 4}) == 0, 'unarmed scenario load was allowed')
assert(call(service_load, {nil, 4}) == 0, 'low-level load bypassed the manager gate')
assert(call(service_load, {nil, 0xffffffff}) == 77, 'zero-extended signed system slot must remain readable')
local ref = {mode = 1, slot_id = 4, timestamp = current_timestamp, scenario = 1}
guard:allow(ref)
assert(call(manager_load, {nil, {}, 1, 0}) == 0, 'newer slot was allowed')
assert(call(manager_load, {nil, {}, 2, 4}) == 0, 'another save mode was allowed')
assert(call(manager_load, {nil, {}, 'malformed', 4}) == 0, 'malformed native arguments were allowed')
assert(call(service_name .. '.loadSingle()') == 0, 'default-slot load is ambiguous')
assert(call(manager_name .. '.requestLoadLatestGameData') == 0, 'latest-save shortcut bypassed policy')
assert(call(manager_name .. '.requestLoadLastUseGameDataSenario') == 0, 'last-used shortcut bypassed policy')
local before = originals
assert(call(manager_load, {nil, {}, 1, 4}, function()
    assert(call(service_load, {nil, 4}) == 77)
    assert(call(manager_name .. '.requestSaveGameDataAuto') == 0)
    return 123
end) == 123, 'nested hook storage corrupted the allowed return')
assert(originals == before + 2)
busy = true
assert(call(manager_load, {nil, {}, 1, 4}) == 0)
busy = false; current_timestamp = '639300360010000000'
assert(call(manager_load, {nil, {}, 1, 4}) == 0, 'replaced save metadata was allowed')
local ok = pcall(guard.allow, guard, ref)
assert(not ok, 'outdated reference was rearmed')
current_timestamp = ref.timestamp; current_scenario = 0
assert(call(manager_load, {nil, {}, 1, 4}) == 0)
current_scenario = 1; accessible = false
assert(call(manager_load, {nil, {}, 1, 4}) == 0)
assert(not pcall(guard.allow, guard, {mode = 1, slot_id = true, timestamp = ref.timestamp, scenario = 1}))
print('Save guard: writes, explicit slot policy, stale metadata, native int32 and nested calls passed')
