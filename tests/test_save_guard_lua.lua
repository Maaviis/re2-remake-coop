local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local service_name = 'via.storage.saveService.SaveService'
local hooks, storage, busy, accessible, current_timestamp, current_scenario = {}, {}, false, true, '639300360000000000', 1
local originals = 0
local directory, mount, title, save_slot = 'SAVESERVICE-LINE-0-', './win64_save', true, 0
local setter_works, mount_sets = true, 0
local static = {
    hasInstance={'System.Boolean',function() return true end},
    get_SaveState={'via.storage.saveService.SaveState',function() return 1 end},
    get_SaveMountPath={'System.String',function() return mount end},
    get_SaveDirectoryPath={'System.String',function() return directory end},
    set_SaveMountPath={'System.Void',function(_,path)
        mount_sets=mount_sets+1
        if setter_works then mount=path end
    end,'System.String'}
}
local defs = {}
for _, name in ipairs({manager_name, service_name}) do
    defs[name] = {
        get_full_name = function() return name end,
        get_method = function(_, signature)
            local m = name == service_name and static[signature]
            local function named(n) return {get_full_name=function() return n end} end
            if m then return {is_static=function() return true end,call=function(_,...) return m[2](...) end,
                get_param_types=function() return m[3] and {named(m[3])} or {} end,
                get_return_type=function() return named(m[1]) end} end
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
    if method == 'get_IsErrorBusy' then return false end
    if method == 'get_SaveGameDataIndex' then return save_slot end
    if method == 'get_IsEnableAccessSaveFileDetailTbl' then return accessible end
    if method == 'getSaveFileDetail' then assert(mode == 1 and slot == 4); return detail end
    if method == 'getScenarioTypeFromDetailString' then return current_scenario end
    error('unexpected manager call: ' .. method)
end}
function manager:get_address() return 73 end
reframework = {get_game_name = function() return 're2' end}
thread = {get_hook_storage = function() return storage[#storage] end}
sdk = {
    get_tdb_version = function() return 70 end,
    find_type_definition = function(name) return defs[name] end,
    to_ptr = function(value) return value end,
    to_managed_object = function(value) return value end,
    to_int64 = function(value) assert(type(value) == 'number'); return value end,
    get_managed_singleton = function(name)
        if name == manager_name then return manager end
        return {call=function(_,m)
            if m=='get_Title' then return title and {} or nil end
            if m=='get_IsInTitle' or m=='isTitleMenuOpened' then return title end
            if m=='get_CurrentPlayer' then return nil end
            return false
        end}
    end,
    PreHookResult = {CALL_ORIGINAL = 1, SKIP_ORIGINAL = 2},
    hook = function(method, pre, post) hooks[method.name] = {pre = pre, post = post} end,
}
local protected = false
local protection = {current={}, poll = function() return protected end, ready = function() return protected end}
local guard = dofile('reframework/autorun/re2_coop/save_guard.lua').new(protection)
assert(not guard.active and guard.hook_count == 0 and next(hooks) == nil, 'stock save hooks were installed')
assert(not guard:activate() and next(hooks) == nil, 'unverified save hooks were installed')
protected = true
assert(guard:activate() and guard.active and guard.hook_count == 26)
local one_hook = hooks[manager_name .. '.requestSaveGameData']
assert(guard:activate() and hooks[manager_name .. '.requestSaveGameData'] == one_hook, 'duplicate save hooks')
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
accessible = true
guard:allow(ref)
protected = false
assert(not pcall(guard.allow, guard, ref), 'unprotected reference was armed')
assert(call(manager_load, {nil, {}, 1, 4}) == 0, 'previously armed load survived protection loss')
assert(call(service_load, {nil, 4}) == 0, 'lower-level load survived protection loss')
assert(call(service_load, {nil, -1}) == 77, 'read-only system slot must remain readable')
print('Save guard: writes, explicit slot policy, stale metadata, native int32 and nested calls passed')
local namespace = string.rep('e',32)
local binding = {game_pid=24,run_id=string.rep('a',32),campaign_namespace=namespace,runtime=true}
local native_matches = true
protected, protection.current = true,binding
function protection:campaign_matches(v)
    return native_matches and v and self.current and self.current.campaign_namespace == v.campaign_namespace
        and self.current.run_id == v.run_id and self.current.game_pid == v.game_pid
end
guard = dofile('reframework/autorun/re2_coop/save_guard.lua').new(protection)
assert(guard:activate())
assert(type(guard.sync_campaign_mount)=='function','no mount binding')
title=false
assert(not guard:sync_campaign_mount(true) and mount_sets==0)
title=true; busy=true
assert(not guard:sync_campaign_mount(true) and mount_sets==0)
busy=false; directory='unexpected'
assert(not guard:sync_campaign_mount(true) and mount_sets==0)
directory='SAVESERVICE-LINE-0-'; mount='./other'
assert(not guard:sync_campaign_mount(true) and mount_sets==0)
mount='./win64_save'; setter_works=false
assert(not guard:sync_campaign_mount(true) and not guard:campaign_ready(binding),'unconfirmed setter enabled writes')
setter_works=true
assert(guard:sync_campaign_mount(true)==namespace and mount=='./coop-save-'..namespace)
assert(guard:campaign_ready(binding) and not pcall(guard.allow,guard,ref))
local now = 100
os.time=function() return now end
local receiver={nil,manager}
local function system(result)
    return call(manager_name..'.requestSaveSystemData',receiver,function() busy=(result==1);return result end)
end
local function profile_worker() return call(manager_name..'.saveSystemSaveData',receiver) end
local function rogue() return call(manager_name..'.saveRogueSystemSaveData',receiver) end
save_slot=-1
assert(system(1)==1 and profile_worker()==77 and rogue()==0)
assert(guard.events[#guard.events].decision=='skipped_system_companion' and next(guard.writes)==nil,
       'expected rogue-system subcall blocked admission')
busy,save_slot=false,0
local function auto(result)
    busy,save_slot=false,-1
    return call(manager_name..'.requestSaveGameDataAuto',receiver,function() busy=(result==1); return result end)
end
local function worker(args) return call(manager_name..'.saveGameSaveData',args or receiver) end
local function no_icon(result)
    return call(manager_name..'.requestSaveSystemDataNoSaveIcon',receiver,function() busy=(result==1); return result end)
end
assert(auto(1)==1 and worker()==77,'the accepted native autosave uses index -1 while its worker is busy')
busy=false
assert(no_icon(1)==1 and profile_worker()==77 and rogue()==0,
    'the completed autosave did not admit its single silent profile save')
assert(call(service_name..'.saveSingle(System.Int32)',{nil,0})==77)
assert(call(service_name..'.saveSingle(System.Int32)',{nil,0xffffffff})==77)
assert(next(guard.writes)==nil, 'admitted autosave reported as a blocked write')
busy=false
assert(no_icon(1)==0,'an unbound silent profile save was admitted')
assert(auto(1)==1 and no_icon(1)==0,'silent profile save ran before the game-data worker completed')
assert(auto(1)==1)
save_slot=0
assert(worker()==0,'an unrelated slot value opened the payload worker')
assert(auto(1)==1)
busy=false
assert(worker()==0,'idle manager reached the payload worker')
assert(rogue()==0 and guard.writes[manager_name..'.saveRogueSystemSaveData']==1,'rogue block was concealed')
assert(profile_worker()==0,'orphan profile worker accepted')
assert(system(0)==0 and profile_worker()==0,'failed system request opened a worker')
assert(worker()==0,'a second worker reused the previous autosave')
assert(auto(0)==0 and worker()==0,'a rejected request permitted a worker')
assert(auto(1)==1)
assert(worker({nil,{get_address=function() return 74 end}})==0,'foreign save manager consumed an autosave')
assert(auto(1)==1)
assert(call(manager_name..'.requestSaveGameData',{nil,manager,1,8})==0 and worker()==0,
    'a manual request could repurpose the pending autosave')
assert(auto(1)==1)
now=now+10
assert(worker()==0,'late worker reused a stale autosave')
assert(auto(1)==1)
native_matches=false
assert(worker()==0,'revoked grant authorized a pending worker')
native_matches=true
assert(worker()==0,'revoked worker remained eligible')
assert(auto(1)==1)
save_slot=5
assert(worker()==0)
for _,name in ipairs({manager_name..'.requestSaveGameData',manager_name..'.requestRemoveGameData',
    service_name..'.deleteData',service_name..'.saveSlotDialog',service_name..'.saveSingle()'}) do
    assert(call(name)==0,name)
end
assert(call(service_name..'.saveSingle(System.Int32)',{nil,1})==0)
mount='./win64_save'
assert(call(manager_name..'.requestSaveSystemData')==0 and not guard:campaign_ready(binding),'mount drift')
mount='./coop-save-'..namespace
native_matches=false
assert(call(manager_name..'.requestSaveSystemData')==0,'receipt revoked after last update')
protection.current=nil; title=false; busy=false
assert(not guard:sync_campaign_mount(true) and mount=='./coop-save-'..namespace,'restored during gameplay')
title=true
assert(not guard:sync_campaign_mount(false) and mount=='./coop-save-'..namespace,'restored during pending transition')
assert(not guard:sync_campaign_mount(true) and mount=='./win64_save')
assert(call(manager_name..'.requestSaveSystemData')==0,'stale campaign write reached solo mount')
print('Campaign save mount: title, receipt, native readback, write allowlist, loss and restore passed')
