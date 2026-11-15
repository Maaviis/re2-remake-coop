local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local flow_name = 'app.ropeway.gamemastering.MainFlowManager'
local gui_name = 'app.ropeway.gui.GUIMaster'
local now, manager, flow, gui, title, guard, calls, state = 100
local reference = {mode = 1, slot_id = 4, timestamp = '639300360000000000', scenario = 1}
os.time = function() return now end
reframework = {get_game_name = function() return 're2' end}
sdk = {get_tdb_version = function() return 70 end,
    find_type_definition = function(name)
        if name == flow_name:gsub('MainFlowManager', 'TitleFlow') or name == gui_name then
            return {get_method = function(_, method)
                local setter = method == 'set_StateValue'
                local close = method:match('^close') ~= nil
                return {is_static = function() return false end,
                    get_return_type = function() return {get_full_name = function() return (setter or close) and 'System.Void' or 'System.Boolean' end} end,
                    get_param_types = function()
                        if setter then return {{get_full_name = function() return 'app.ropeway.gamemastering.TitleFlow.State' end}} end
                        if close then
                            local types = {{get_full_name = function() return 'System.Action' end}}
                            if method == 'closeMenuStory' then types[2] = {get_full_name = function() return 'System.Boolean' end} end
                            return types
                        end
                        return {}
                    end}
            end}
        end
        assert(name == 'app.ropeway.gamemastering.TitleFlow.State')
        return {get_field = function(_, field)
            assert(field == 'FINALIZE'); return {get_data = function() return 29 end}
        end}
    end,
    get_managed_singleton = function(name)
        if name == manager_name then return manager end
        if name == flow_name then return flow end
        if name == gui_name then return gui end
        error('unexpected singleton')
    end}
local module = dofile('reframework/autorun/re2_coop/readonly_loader.lua')
local function setup()
    calls = {}
    state = {get_IsBusy = false, get_IsInLoadGameData = false, get_IsTitleSceneEnvironmentLoaded = true,
        get_IsFinishedLoadScene = false, get_IsErrorBusy = false, get_LoadGameDataIndex = -1,
        get_CurrentScenarioType = 1, accepted = true, get_IsInTitle = true,
        get_IsExistLoadedGameData = false, isNoErrorLoad = true,
        isTitleMenuOpened = true, isBusyMenuMain = false, isBusyMenuStory = false, isBusyLoad = false}
    title = {get_address = function() return 123 end, call = function(_, method, value)
        assert(method == 'set_StateValue' and value == 29)
        calls[#calls + 1] = 'finalize'
        if state.throw_flow then error('unavailable') end
    end}
    gui = {call = function(_, method, callback, kill_effect)
        if method:match('^close') then
            assert(callback == nil and (method ~= 'closeMenuStory' or kill_effect == true))
            calls[#calls + 1] = method
            if state.throw_close then error('unavailable') end
            local names = {closeTitleMenu = 'isTitleMenuOpened', closeMenuMain = 'isBusyMenuMain', closeMenuStory = 'isBusyMenuStory'}
            if not state.keep_menu_open then state[assert(names[method])] = false end
            return
        end
        assert(method:match('^is'), 'unexpected GUI mutation: ' .. method)
        return state[method]
    end}
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
        if method == 'get_Title' then return title end
        assert(method:match('^get_'), 'unexpected mutation: ' .. method)
        if state.throw_status then error('unavailable') end
        return state[method]
    end}
    guard = {active = true, denied_loads = 0, allow = function(_, ref)
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
    state.isTitleMenuOpened = false
end
local function finish_read(loader)
    state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
    loader:poll(nil)
    assert(loader.phase == 'closing_menu')
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
assert(table.concat(calls, ',') == 'allow,request,closeTitleMenu,finalize')
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
state.isTitleMenuOpened = true; loader:poll(actor()); assert(loader.phase == 'loading', 'visible title menu completed load')
state.isTitleMenuOpened = false; state.isBusyMenuMain = true; loader:poll(actor()); assert(loader.phase == 'loading')
state.isBusyMenuMain = false; state.isBusyMenuStory = true; loader:poll(actor()); assert(loader.phase == 'loading')
state.isBusyMenuStory = false
state.isBusyLoad = true; loader:poll(actor()); assert(loader.phase == 'loading', 'native slot dialog completed load')
state.isBusyLoad = false
loader:poll(actor())
assert(loader.phase == 'scene_loaded' and loader.error == '')

for _, condition in ipairs({'get_IsBusy', 'get_IsInLoadGameData', 'isBusyLoad', 'not_title', 'no_title_menu', 'throw_status', 'deny_reference', 'missing_manager'}) do
    loader = setup()
    if condition == 'not_title' then state.get_IsInTitle = false
    elseif condition == 'no_title_menu' then state.isTitleMenuOpened = false
    elseif condition == 'missing_manager' then manager = nil
    else state[condition] = true end
    assert(not loader:start(reference), 'unsafe start allowed: ' .. condition)
    assert(loader.error ~= '' and loader.phase == 'idle')
    assert(not table.concat(calls, ','):find('request', 1, true))
end
loader = setup(); state.accepted = false
assert(not loader:start(reference, 'native-attempt'))
assert(loader.phase == 'failed' and loader.error == 'load_request_rejected')
assert(loader.request_id == 'native-attempt')
assert(table.concat(calls, ',') == 'allow,request', 'flow started after rejected native request')
state.get_IsInTitle = false
local accepted, reason = loader:start(reference, 'rejected-before-request')
assert(not accepted and reason == 'title_not_ready')
assert(loader.request_id == 'native-attempt' and loader.error == 'load_request_rejected',
    'preflight error replaced the previous native result')
loader = setup(); state.throw_flow = true
assert(loader:start(reference))
state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
loader:poll(actor()); loader:poll(actor()); assert(loader.phase == 'failed' and loader.error == 'load_flow_start_failed')
loader = setup(); assert(loader:start(reference)); manager = nil
loader:poll(actor()); assert(loader.phase == 'reading_save' and loader.error == 'load_status_unavailable')
assert(not loader:start(reference), 'missing status caused a second load')
loader = setup(); assert(loader:start(reference)); title = {get_address = function() return 456 end}
loader:poll(actor()); assert(loader.phase == 'failed' and loader.error == 'title_flow_replaced')
loader = setup(); assert(loader:start(reference)); state.get_IsErrorBusy = true
loader:poll(actor()); assert(loader.phase == 'failed' and loader.error == 'native_load_error')
loader = setup(); assert(loader:start(reference)); finish_read(loader); completed_scene(); now = 110
loader:poll(actor(101)); assert(loader.phase == 'loading', 'expired observer completed load')
loader:poll(actor()); assert(loader.phase == 'scene_loaded')
loader = setup(); state.keep_menu_open = true; assert(loader:start(reference))
state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
loader:poll(nil); loader:poll(nil)
assert(loader.phase == 'closing_menu' and not table.concat(calls, ','):find('finalize', 1, true))
assert(not loader:start(reference), 'closing menu caused a duplicate request')
state.isTitleMenuOpened = false; loader:poll(nil); assert(loader.phase == 'loading')
loader = setup(); state.throw_close = true; assert(loader:start(reference))
state.get_IsExistLoadedGameData, state.get_LoadGameDataIndex = true, 4
loader:poll(nil); assert(loader.phase == 'failed' and loader.error == 'title_menu_close_failed')
loader = setup(); state.isTitleMenuOpened, state.isBusyMenuStory = false, true
assert(loader:start(reference)); finish_read(loader)
assert(table.concat(calls, ',') == 'allow,request,closeMenuStory,finalize')
loader = setup(); guard.denied_loads = 1
assert(not loader:start(reference) and loader.error == 'native_load_state_requires_reset' and #calls == 0,
    'a guard-denied native load was followed by another request in an unvalidated error state')
loader = setup(); assert(loader:start(reference)); guard.denied_loads = 1; loader:poll(actor())
assert(loader.phase == 'failed' and loader.error == 'native_load_state_requires_reset'
    and table.concat(calls, ',') == 'allow,request', 'denied load during a request triggered menu/scene writes')
print('Read-only loader: native call order, title gate, failure handling and fresh actor witness passed')
