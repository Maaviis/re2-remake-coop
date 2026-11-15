-- Native gameplay pause primitive. It does not establish a complete-world hold or release gameplay.
local M = {}
local root = 'app.ropeway.'
local flow_name, gui_name = root .. 'gamemastering.MainFlowManager', root .. 'gui.GUIMaster'
local pause_name, behavior_name = root .. 'gamemastering.PauseFlow', root .. 'gui.PauseBehavior'
local save_name = root .. 'gamemastering.SaveDataManager'

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_pause_build')
    local function method(type_name, name, returns, params, static)
        local def = assert(sdk.find_type_definition(type_name), 'missing_type:' .. type_name)
        local member = assert(def:get_method(name), 'missing_method:' .. name)
        assert(member:is_static() == (static == true) and member:get_return_type():get_full_name() == returns,
            'unsupported_method:' .. name)
        local actual = member:get_param_types()
        assert(#actual == #(params or {}), 'unsupported_parameter_count:' .. name)
        for index, expected in ipairs(params or {}) do
            assert(actual[index]:get_full_name() == expected, 'unsupported_parameter:' .. name)
        end
    end
    method(flow_name, 'goPause', 'System.Void')
    method(flow_name, 'get_Pause', pause_name)
    for _, name in ipairs({'get_IsInTitle', 'get_IsInLoadGameData', 'get_IsFinishedLoadScene',
            'get_IsInPause', 'get_IsInGameNotPause'}) do method(flow_name, name, 'System.Boolean') end
    method(save_name, 'get_IsBusy', 'System.Boolean')
    method(gui_name, 'get_IsOpenPause', 'System.Boolean')
    method(behavior_name, 'get_EnableInput', 'System.Boolean')
    method(behavior_name, 'toReturnGame', 'System.Void')
    method('via.SceneManager', 'get_CurrentScene', 'via.Scene', nil, true)
    method('via.Scene', 'findComponents', 'via.Component[]', {'System.Type'})
    local pause_type = assert(sdk.find_type_definition(pause_name), 'pause_type_unavailable')
    local state = assert(pause_type:get_field('StateValue'), 'pause_state_unavailable')
    assert(not state:is_static() and state:get_type():get_full_name() == pause_name .. '.State', 'unsupported_pause_state')
    local update = assert(sdk.find_type_definition(pause_name .. '.State'):get_field('UPDATE'), 'pause_update_unavailable')
    assert(update:is_static() and update:get_data(nil) == 1, 'unsupported_pause_update')
    local behavior_type = assert(sdk.typeof(behavior_name), 'pause_behavior_type_unavailable')
    local scene_manager_type = assert(sdk.find_type_definition('via.SceneManager'))
    local self = {phase = 'idle', reason = '', verified = false, request_id = ''}
    local owner, retired, retired_count = nil, {}, 0

    local function boolean(value)
        assert(type(value) == 'boolean', 'invalid_pause_boolean')
        return value
    end
    local function read()
        local flow, gui, save = sdk.get_managed_singleton(flow_name), sdk.get_managed_singleton(gui_name),
            sdk.get_managed_singleton(save_name)
        assert(flow and gui and save, 'pause_managers_unavailable')
        local result = {flow = flow, gui = gui, busy = boolean(save:call('get_IsBusy'))}
        for key, name in pairs({title = 'get_IsInTitle', loading = 'get_IsInLoadGameData',
                finished = 'get_IsFinishedLoadScene', paused = 'get_IsInPause', playing = 'get_IsInGameNotPause'}) do
            result[key] = boolean(flow:call(name))
        end
        result.menu = boolean(gui:call('get_IsOpenPause'))
        local manager = sdk.get_native_singleton('via.SceneManager')
        result.scene = manager and sdk.call_native_func(manager, scene_manager_type, 'get_CurrentScene')
        local players = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        result.player = players and players:call('get_CurrentPlayer')
        assert(result.scene and result.player, 'pause_scene_unavailable')
        assert(result.scene:get_type_definition():get_full_name() == 'via.Scene', 'unsupported_pause_scene')
        return result
    end
    local function behavior(scene)
        local list = assert(scene:call('findComponents', behavior_type), 'pause_behavior_list_unavailable')
        assert(list:get_size() == 1, 'pause_behavior_not_unique')
        local object = assert(list:get_element(0), 'pause_behavior_unavailable')
        assert(object:get_type_definition():get_full_name() == behavior_name, 'unsupported_pause_behavior')
        return object
    end
    local function matches(current)
        return current.flow:get_address() == owner.flow and current.scene:get_address() == owner.scene
            and current.player:get_address() == owner.player
    end
    local function lost(reason)
        owner = nil
        self.phase, self.reason, self.verified = 'lost', reason, false
    end

    function self:request(id)
        if type(id) ~= 'string' or #id ~= 32 or not id:match('^[0-9a-f]+$') then return false, 'invalid_pause_id' end
        if owner then return false, 'pause_in_progress' end
        if retired[id] then return false, 'pause_id_already_used' end
        if retired_count >= 256 then return false, 'pause_id_limit' end
        local ok, current = pcall(read)
        if not ok then return false, 'pause_state_unavailable' end
        if current.title or current.loading or not current.finished or current.busy
            or current.paused or current.menu or not current.playing then return false, 'gameplay_not_ready' end
        retired[id], retired_count = true, retired_count + 1
        self.request_id, self.phase, self.reason, self.verified = id, 'requesting', '', false
        owner = {flow = current.flow:get_address(), scene = current.scene:get_address(), player = current.player:get_address()}
        local called = pcall(current.flow.call, current.flow, 'goPause')
        if not called then owner = nil; self.phase, self.reason = 'failed', 'pause_call_failed'; return false, self.reason end
        return true
    end

    function self:poll()
        self.verified = false
        local ok, current = pcall(read)
        if not ok then self.reason = 'pause_state_unavailable'; return false end
        if not owner then
            self.verified = self.phase ~= 'lost' and self.phase ~= 'failed'
                and not current.title and not current.loading and current.finished and not current.busy
            if self.verified then self.reason = '' end
            return self.verified
        end
        if not matches(current) then lost('pause_context_replaced'); return false end
        if current.title or current.loading or not current.finished or current.busy then lost('pause_context_changed'); return false end
        local pause = current.flow:call('get_Pause')
        if pause then
            if pause:get_type_definition():get_full_name() ~= pause_name then lost('unsupported_pause_flow'); return false end
            if owner.pause and pause:get_address() ~= owner.pause then lost('pause_flow_replaced'); return false end
        end
        if self.phase == 'returning' then
            if not current.paused and not current.menu and current.playing then
                owner = nil; self.phase, self.reason, self.verified = 'released', '', true
            end
            return self.verified
        end
        if not current.paused then
            if self.phase == 'held' then lost('pause_ended_externally') end
            return false
        end
        if not pause then self.reason = 'pause_flow_unavailable'; return false end
        owner.pause = owner.pause or pause:get_address()
        if not current.menu or current.playing or pause:get_field('StateValue') ~= 1 then
            if self.phase == 'held' then lost('pause_menu_changed') end
            return false
        end
        local found, object = pcall(behavior, current.scene)
        if not found then self.reason = 'pause_behavior_unavailable'; return false end
        if owner.behavior and object:get_address() ~= owner.behavior then lost('pause_behavior_replaced'); return false end
        if not boolean(object:call('get_EnableInput')) then self.reason = 'pause_menu_not_ready'; return false end
        owner.behavior = object:get_address()
        self.phase, self.reason, self.verified = 'held', '', true
        return true
    end

    function self:release(id)
        if id ~= self.request_id or not owner then return false, 'pause_not_owned' end
        local polled, verified = pcall(self.poll, self)
        if not polled or not verified or self.phase ~= 'held' then return false, 'owned_pause_not_ready' end
        local ok, current = pcall(read)
        if not ok or not matches(current) then return false, 'pause_state_unavailable' end
        local found, object = pcall(behavior, current.scene)
        if not found or object:get_address() ~= owner.behavior then return false, 'pause_behavior_replaced' end
        -- The real menu action closes its UI and delivers RETURN to the native flow.
        -- Calling the flow's result callback alone leaves the native menu open.
        self.phase, self.verified = 'returning', false
        if not pcall(object.call, object, 'toReturnGame') then self.reason = 'pause_return_failed'; return false, self.reason end
        return true
    end

    function self:cleanup()
        return self:release(self.request_id)
    end
    return self
end

return M
