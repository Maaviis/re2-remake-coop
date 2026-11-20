-- Native RE2 load primitive for the opt-in read-only test probe; no save calls.
local M = {}
local manager_name = 'app.ropeway.gamemastering.SaveDataManager'
local flow_name = 'app.ropeway.gamemastering.MainFlowManager'
local gui_name = 'app.ropeway.gui.GUIMaster'
local title_enum_name = 'app.ropeway.gamemastering.TitleFlow.State'
local title_name = 'app.ropeway.gamemastering.TitleFlow'

function M.new(guard)
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70)
    assert(guard and guard.active and type(guard.allow) == 'function')
    local title_enum = assert(sdk.find_type_definition(title_enum_name), 'title_states_unavailable')
    local finalize_field = assert(title_enum:get_field('FINALIZE'), 'title_finalize_unavailable')
    local finalize = finalize_field:get_data(nil)
    assert(math.type(finalize) == 'integer' and finalize == 29, 'unsupported_title_finalize_state')
    local title_type = assert(sdk.find_type_definition(title_name), 'title_type_unavailable')
    local setter = assert(title_type:get_method('set_StateValue'), 'title_state_setter_unavailable')
    local parameters = setter:get_param_types()
    assert(not setter:is_static() and setter:get_return_type():get_full_name() == 'System.Void'
        and #parameters == 1 and parameters[1]:get_full_name() == title_enum_name, 'unsupported_title_state_setter')
    local gui_type = assert(sdk.find_type_definition(gui_name), 'gui_type_unavailable')
    for _, name in ipairs({'isTitleMenuOpened', 'isBusyMenuMain', 'isBusyMenuStory', 'isBusyLoad'}) do
        local getter = assert(gui_type:get_method(name), 'gui_query_unavailable:' .. name)
        assert(not getter:is_static() and getter:get_return_type():get_full_name() == 'System.Boolean'
            and #getter:get_param_types() == 0, 'unsupported_gui_query:' .. name)
    end
    for _, name in ipairs({'closeTitleMenu', 'closeMenuMain', 'closeMenuStory'}) do
        local close = assert(gui_type:get_method(name), 'gui_close_unavailable:' .. name)
        local params = close:get_param_types()
        assert(not close:is_static() and close:get_return_type():get_full_name() == 'System.Void'
            and #params == (name == 'closeMenuStory' and 2 or 1)
            and params[1]:get_full_name() == 'System.Action'
            and (name ~= 'closeMenuStory' or params[2]:get_full_name() == 'System.Boolean'),
            'unsupported_gui_close:' .. name)
    end
    local self = {phase = 'idle', error = '', reference = nil, started_at = nil}
    local title_address

    local function reject(reason)
        if self.request_id == nil then self.error = reason end
        return false, reason
    end

    function self:is_in_progress()
        return self.phase == 'reading_save' or self.phase == 'closing_menu' or self.phase == 'loading'
    end

    local function title_load_target()
        if self:is_in_progress() then return nil, nil, 'load_in_progress' end
        -- Recovery after a guard-denied stock load is not validated. Do not issue another request.
        if guard.denied_loads ~= 0 then return nil, nil, 'native_load_state_requires_reset' end
        local manager, flow, gui = sdk.get_managed_singleton(manager_name), sdk.get_managed_singleton(flow_name),
            sdk.get_managed_singleton(gui_name)
        if not manager or not flow or not gui then return nil, nil, 'load_managers_unavailable' end
        local title, candidate_address
        local inspected, title_ready = pcall(function()
            title = flow:call('get_Title')
            candidate_address = title and title:get_address()
            return manager:call('get_IsBusy') == false and flow:call('get_IsInLoadGameData') == false
                and flow:call('get_IsInTitle') == true and title ~= nil
                and gui:call('isBusyLoad') == false
                and (gui:call('isTitleMenuOpened') == true or gui:call('isBusyMenuMain') == true
                    or gui:call('isBusyMenuStory') == true)
        end)
        if not inspected then return nil, nil, 'load_status_unavailable' end
        if not title_ready then return nil, nil, 'title_not_ready' end
        return manager, candidate_address
    end

    function self:ready()
        local manager, _, reason = title_load_target()
        return manager ~= nil, reason
    end

    function self:start(reference, request_id)
        local manager, candidate_address, reason = title_load_target()
        if not manager then return reject(reason) end
        local authorized = pcall(guard.allow, guard, reference)
        if not authorized then return reject('save_reference_not_available') end
        self.reference = {mode = reference.mode, slot_id = reference.slot_id,
            timestamp = reference.timestamp, scenario = reference.scenario}
        title_address = candidate_address
        self.error, self.phase, self.started_at = '', 'reading_save', os.time()
        self.request_id = request_id
        local ok, accepted = pcall(manager.call, manager, 'requestLoadGameData', 1, reference.slot_id)
        if not ok or accepted ~= true then
            self.phase, self.error = 'failed', 'load_request_rejected'
            return false, self.error
        end
        return true
    end

    function self:poll(observation)
        if not self:is_in_progress() then return end
        if guard.denied_loads ~= 0 then self.phase, self.error = 'failed', 'native_load_state_requires_reset'; return end
        local now = os.time()
        local has_player = type(observation) == 'table' and observation.source == 're2' and observation.tdb == 70
            and observation.available == true and type(observation.observed_at) == 'number'
            and observation.observed_at > self.started_at and observation.observed_at <= now
            and now - observation.observed_at <= 3
        local ok = pcall(function()
            local manager, flow, gui = sdk.get_managed_singleton(manager_name), sdk.get_managed_singleton(flow_name),
                sdk.get_managed_singleton(gui_name)
            if not manager or not flow or not gui then self.error = 'load_status_unavailable'; return end
            if manager:call('get_IsErrorBusy') then self.phase, self.error = 'failed', 'native_load_error'; return end
            self.error = ''
            if self.phase == 'reading_save' or self.phase == 'closing_menu' then
                local title = flow:call('get_Title')
                if not title or title:get_address() ~= title_address then
                    self.phase, self.error = 'failed', 'title_flow_replaced'; return
                end
                if manager:call('get_IsBusy') == false and manager:call('get_IsExistLoadedGameData') == true
                    and manager:call('get_LoadGameDataIndex') == self.reference.slot_id
                    and manager:call('isNoErrorLoad') == true and flow:call('get_IsInTitle') == true
                    and flow:call('get_IsInLoadGameData') == false then
                    if self.phase == 'reading_save' then
                        self.phase = 'closing_menu'
                        -- Use the owning native menu APIs, including their shared guide/effect cleanup.
                        local closed = pcall(function()
                            if gui:call('isTitleMenuOpened') then gui:call('closeTitleMenu', nil) end
                            if gui:call('isBusyMenuMain') then gui:call('closeMenuMain', nil) end
                            if gui:call('isBusyMenuStory') then gui:call('closeMenuStory', nil, true) end
                        end)
                        if not closed then self.phase, self.error = 'failed', 'title_menu_close_failed' end
                    elseif gui:call('isTitleMenuOpened') == false and gui:call('isBusyMenuMain') == false
                        and gui:call('isBusyMenuStory') == false and gui:call('isBusyLoad') == false then
                        self.phase = 'loading'
                        -- Let the native main flow perform the ensuing scene transition.
                        local started = pcall(title.call, title, 'set_StateValue', finalize)
                        if not started then self.phase, self.error = 'failed', 'load_flow_start_failed' end
                    end
                end
                return
            end
            if has_player and manager:call('get_IsBusy') == false and flow:call('get_IsInLoadGameData') == false
                and flow:call('get_IsInTitle') == false and flow:call('get_IsFinishedLoadScene') == true
                and manager:call('get_LoadGameDataIndex') == self.reference.slot_id
                and flow:call('get_CurrentScenarioType') == self.reference.scenario
                and gui:call('isTitleMenuOpened') == false and gui:call('isBusyMenuMain') == false
                and gui:call('isBusyMenuStory') == false and gui:call('isBusyLoad') == false then
                self.phase, self.error = 'scene_loaded', ''
            end
        end)
        if not ok then self.error = 'load_status_unavailable' end
    end
    return self
end

return M
