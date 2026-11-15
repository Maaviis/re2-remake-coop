local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local flow_name = 'app.ropeway.gamemastering.MainFlowManager'
local now, manager, flow, guard, calls, state = 100
local reference = {mode = 1, slot_id = 4, timestamp = '639300365010000000', scenario = 1}
os.time = function() return now end
reframework = {get_game_name = function() return 're2' end}
sdk = {get_tdb_version = function() return 70 end,
    get_managed_singleton = function(name)
        if name == manager_name then return manager end
        if name == flow_name then return flow end
        error('unexpected singleton')
    end}
local module = dofile('reframework/autorun/re2_coop/readonly_loader.lua')
local function setup()
    calls = {}
    state = {get_IsBusy = false, get_IsInLoadGameData = false, get_IsTitleSceneEnvironmentLoaded = true,
        get_IsFinishedLoadScene = false, get_IsErrorBusy = false, get_LoadGameDataIndex = -1,
        get_CurrentScenarioType = 1, accepted = true, get_IsInTitle = true,
        get_IsExistLoadedGameData = false, isNoErrorLoad = true}
    manager = {call = function(_, method, mode, slot)
        if method == 'requestLoadGameData' then
            assert(mode == 1 and slot == 4)
            calls[#calls + 1] = 'request'
            return state.accepted
        end
        assert(method:match('^get_') or method == 'isNoErrorLoad', 'unexpected mutation: ' .. method)
        if state.throw_status then error('unavailable') end
        return state[method]
    end}
    flow = {call = function(_, method)
        if method == 'goLoadGameData' then calls[#calls + 1] = 'flow'; if state.throw_flow then error('unavailable') end; return end
        assert(method:match('^get_'), 'unexpected mutation: ' .. method)
        if state.throw_status then error('unavailable') end
        return state[method]
    end}
    guard = {active = true, allow = function(_, ref)
        calls[#calls + 1] = 'allow'
        assert(ref == reference and not state.deny_reference)
    end}
    now = 100
    return module.new(guard)
end
local function actor(at)
    return {source = 're2', tdb = 70, available = true, observed_at = at or now}
end
local function completed_scene()
    state.get_IsInTitle, state.get_IsFinishedLoadScene = false, true
    state.get_LoadGameDataIndex = 4
end
local function finish_read(loader)
    state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
    loader:poll(nil)
    assert(loader.phase == 'loading')
    state.get_IsExistLoadedGameData = false
end
local loader = setup()
assert(loader:start(reference))
assert(table.concat(calls, ',') == 'allow,request' and loader.phase == 'reading_save')
loader:poll(actor()); assert(loader.phase == 'reading_save', 'flow started before async read finished')
state.get_IsExistLoadedGameData = true; state.get_LoadGameDataIndex = 4; state.get_IsBusy = true
loader:poll(actor()); assert(loader.phase == 'reading_save', 'flow started during async read')
state.get_IsBusy = false; state.isNoErrorLoad = false
loader:poll(actor()); assert(loader.phase == 'reading_save', 'flow started after failed read')
state.isNoErrorLoad = true
finish_read(loader)
assert(table.concat(calls, ',') == 'allow,request,flow')
reference.slot_id = 8
assert(loader.reference.slot_id == 4, 'reference was not copied')
reference.slot_id = 4
local count = #calls
assert(not loader:start(reference) and #calls == count, 'in-flight request retried')
completed_scene()
loader:poll(actor(100))
assert(loader.phase == 'loading', 'pre-request observer sample completed load')
now = 102
for _, observation in ipairs({actor(99), actor(103), {available = true, observed_at = 102},
        {source = 're2', tdb = 70, available = false, observed_at = 102}}) do
    loader:poll(observation)
    assert(loader.phase == 'loading', 'invalid actor witness completed load')
end
state.get_LoadGameDataIndex = 0; loader:poll(actor()); assert(loader.phase == 'loading')
state.get_LoadGameDataIndex = 4; state.get_CurrentScenarioType = 0; loader:poll(actor()); assert(loader.phase == 'loading')
state.get_CurrentScenarioType = 1; state.get_IsBusy = true; loader:poll(actor()); assert(loader.phase == 'loading')
state.get_IsBusy = false; state.get_IsInLoadGameData = true; loader:poll(actor()); assert(loader.phase == 'loading')
state.get_IsInLoadGameData = false
loader:poll(actor())
assert(loader.phase == 'scene_loaded' and loader.error == '')

for _, condition in ipairs({'get_IsBusy', 'get_IsInLoadGameData', 'not_title', 'throw_status', 'deny_reference', 'missing_manager'}) do
    loader = setup()
    if condition == 'not_title' then state.get_IsInTitle = false
    elseif condition == 'missing_manager' then manager = nil
    else state[condition] = true end
    assert(not loader:start(reference), 'unsafe start allowed: ' .. condition)
    assert(loader.error ~= '' and loader.phase == 'idle')
    assert(not table.concat(calls, ','):find('request', 1, true))
end
loader = setup(); state.accepted = false
assert(not loader:start(reference) and loader.phase == 'failed' and loader.error == 'load_request_rejected')
assert(table.concat(calls, ',') == 'allow,request', 'flow started after rejected native request')
loader = setup(); state.throw_flow = true
assert(loader:start(reference))
state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
loader:poll(actor()); assert(loader.phase == 'failed' and loader.error == 'load_flow_start_failed')
loader = setup(); assert(loader:start(reference)); manager = nil
loader:poll(actor()); assert(loader.phase == 'reading_save' and loader.error == 'load_status_unavailable')
assert(not loader:start(reference), 'missing status caused a second load')
loader = setup(); assert(loader:start(reference)); state.get_IsErrorBusy = true
loader:poll(actor()); assert(loader.phase == 'failed' and loader.error == 'native_load_error')
loader = setup(); assert(loader:start(reference)); finish_read(loader); completed_scene(); now = 110
loader:poll(actor(101)); assert(loader.phase == 'loading', 'expired observer completed load')
loader:poll(actor()); assert(loader.phase == 'scene_loaded')
print('Read-only loader: native call order, title gate, failure handling and fresh actor witness passed')
