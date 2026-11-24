-- TDB70 native first-run campaigns. No save reference or load permission is created.
local M = {}
local root = 'app.ropeway.'
local flow_name, title_name = root..'gamemastering.MainFlowManager', root..'gamemastering.TitleFlow'
local gui_name, manager_name = root..'gui.GUIMaster', root..'gamemastering.SaveDataManager'
local scenarios, difficulties = {LEON_A=0, CLAIRE_A=1}, {EASY=0, NORMAL=1, HARD=2}

function M.selection(value)
    if type(value) ~= 'table' or scenarios[value.scenario] == nil or difficulties[value.difficulty] == nil then return false end
    for key in pairs(value) do if key ~= 'scenario' and key ~= 'difficulty' then return false end end
    return true
end

function M.matches(data, value)
    return M.selection(value) and type(data) == 'table' and data.save_slot == nil and data.save_ref == nil
        and M.selection(data.new_game) and data.new_game.scenario == value.scenario and data.new_game.difficulty == value.difficulty
end

function M.scenario(value) return scenarios[value] end

function M.new(guard, loader)
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70)
    local function method(type_name, name, result, arg)
        local def = assert(sdk.find_type_definition(type_name))
        local m = assert(def:get_method(name))
        local args = m:get_param_types()
        assert(not m:is_static() and m:get_return_type():get_full_name() == result
            and #args == (arg and 1 or 0) and (not arg or args[1]:get_full_name() == arg), name)
        return m
    end
    local function enum(type_name, entries)
        local def = assert(sdk.find_type_definition(type_name))
        for key, expected in pairs(entries) do
            local field = assert(def:get_field(key))
            assert(field:is_static() and field:get_data(nil) == expected, key)
        end
    end
    enum(flow_name..'.ScenarioType', scenarios)
    enum(flow_name..'.Difficulty', difficulties)
    enum(title_name..'.State', {FINALIZE=29})
    local setup = method(flow_name,'setupNewGame','System.Void',flow_name..'.ScenarioType')
    local difficulty = method(flow_name,'setDifficulty','System.Void',flow_name..'.Difficulty')
    local get_difficulty = method(flow_name,'get_CurrentDifficulty',flow_name..'.Difficulty')
    local get_scenario = method(flow_name,'get_CurrentScenarioType',flow_name..'.ScenarioType')
    local finalize = method(title_name,'set_StateValue','System.Void',title_name..'.State')
    local close_title = method(gui_name,'closeTitleMenu','System.Void','System.Action')
    local close_main = method(gui_name,'closeMenuMain','System.Void','System.Action')
    method(flow_name,'get_Title',title_name)
    method(root..'PlayerManager','get_CurrentPlayer','via.GameObject')
    for _, name in ipairs({'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene'}) do
        method(flow_name,name,'System.Boolean')
    end
    for _, name in ipairs({'get_IsBusy','get_IsErrorBusy'}) do method(manager_name,name,'System.Boolean') end
    for _, name in ipairs({'isTitleMenuOpened','isBusyMenuMain','isBusyMenuStory','isBusyMenuScenario','isBusySelectDifficulty','isBusyLoad'}) do
        method(gui_name, name, 'System.Boolean')
    end
    local active, title_address, binding, world_player
    local self = {}
    local function protected(receipt)
        return guard.protection:matches(receipt) and guard.active == true and guard.hook_count == 26
            and guard.policy == nil and guard.allowed_load_calls == 0 and guard.denied_loads == 0
    end
    local function native()
        return assert(sdk.get_managed_singleton(flow_name)), assert(sdk.get_managed_singleton(gui_name)),
            assert(sdk.get_managed_singleton(manager_name)), sdk.get_managed_singleton(root..'PlayerManager')
    end
    local function no_other_menu(gui)
        return gui:call('isBusyMenuStory') == false and gui:call('isBusyMenuScenario') == false
            and gui:call('isBusySelectDifficulty') == false and gui:call('isBusyLoad') == false
    end
    local function at_title(flow, manager, players)
        return flow:call('get_IsInTitle') == true and flow:call('get_IsInLoadGameData') == false
            and manager:call('get_IsBusy') == false and manager:call('get_IsErrorBusy') == false
            and (not players or players:call('get_CurrentPlayer') == nil)
    end
    local function ready(selection, receipt)
        if active or not M.selection(selection) or not protected(receipt) or next(guard.writes) then return false end
        local flow, gui, manager, players = native()
        return at_title(flow,manager,players) and flow:call('get_Title') ~= nil and no_other_menu(gui)
            and (gui:call('isTitleMenuOpened') == true or gui:call('isBusyMenuMain') == true)
    end
    function self:ready(selection, receipt)
        local ok, result = pcall(ready, selection, receipt)
        if ok and result then return true end
        return false, 'new_game_title_not_ready'
    end
    local function fail(reason)
        loader.phase, loader.error = 'failed', reason
        return false, reason
    end
    function self:start(selection, id, receipt)
        if not self:ready(selection, receipt) then return false, 'new_game_title_not_ready' end
        active = {scenario=selection.scenario, difficulty=selection.difficulty}
        binding = {game_pid=receipt.game_pid,run_id=receipt.run_id}
        loader.new_game, loader.request_id, loader.started_at = active, id, os.time()
        loader.phase, loader.error = 'closing_menu', ''
        local ok = pcall(function()
            local flow, gui = native()
            title_address = assert(flow:call('get_Title')):get_address()
            difficulty:call(flow, difficulties[active.difficulty])
            setup:call(flow, scenarios[active.scenario])
            if gui:call('isTitleMenuOpened') then close_title:call(gui,nil) end
            if gui:call('isBusyMenuMain') then close_main:call(gui,nil) end
        end)
        if not ok then return fail('new_game_setup_failed') end
        return true
    end
    local function current_player(flow, gui, manager, players)
        if manager:call('get_IsBusy') ~= false or manager:call('get_IsErrorBusy') ~= false
            or flow:call('get_IsInTitle') ~= false or flow:call('get_IsInLoadGameData') ~= false
            or flow:call('get_IsFinishedLoadScene') ~= true or gui:call('isTitleMenuOpened') ~= false
            or gui:call('isBusyMenuMain') ~= false or not no_other_menu(gui) then return nil end
        return players and players:call('get_CurrentPlayer')
    end
    function self:poll(admitted, recheck)
        if not active or (loader.phase ~= 'closing_menu' and loader.phase ~= 'loading') then return end
        if not protected(binding) then return fail('new_game_protection_lost') end
        if admitted ~= true then return fail('new_game_lobby_changed') end
        local now = os.time()
        if now < loader.started_at or now - loader.started_at > (loader.phase == 'closing_menu' and 8 or 120) then
            return fail('new_game_transition_timeout')
        end
        local ok = pcall(function()
            local flow, gui, manager, players = native()
            if loader.phase == 'closing_menu' then
                local title = flow:call('get_Title')
                if not title or title:get_address() ~= title_address or not at_title(flow,manager,players)
                    or not no_other_menu(gui) then return fail('new_game_title_changed') end
                if gui:call('isTitleMenuOpened') == false and gui:call('isBusyMenuMain') == false then
                    if not recheck() or not protected(binding) then return fail('new_game_admission_lost') end
                    loader.phase = 'loading'
                    finalize:call(title,29)
                end
                return
            end
            local player = current_player(flow,gui,manager,players)
            if player then
                if get_scenario:call(flow) ~= scenarios[active.scenario]
                    or get_difficulty:call(flow) ~= difficulties[active.difficulty] then return fail('new_game_selection_mismatch') end
                world_player, loader.phase = player:get_address(), 'scene_loaded'
            end
        end)
        if not ok then return fail('new_game_transition_failed') end
    end
    function self:world(read_area)
        if not active or loader.phase ~= 'scene_loaded' or not protected(binding) then return nil end
        local flow, gui, manager, players = native()
        local player = current_player(flow,gui,manager,players)
        if not player or player:get_address() ~= world_player then return nil end
        local area = read_area()
        local scenario, level = get_scenario:call(flow), get_difficulty:call(flow)
        if type(area) ~= 'table' or scenario ~= scenarios[active.scenario] or area.scenario ~= scenario
            or level ~= difficulties[active.difficulty] or math.type(area.map) ~= 'integer'
            or math.type(area.area) ~= 'integer' or area.map < 1 or area.map >= 435
            or area.area < 0 or area.area >= 6 then return nil end
        return {request_id=loader.request_id,observed_at=os.time(),scenario=scenario,difficulty=level,map=area.map,area=area.area}
    end
    return self
end
return M
