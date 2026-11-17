-- Read-only native timeline activity. No event orders, skips, pause or world-state application.
local M = {}
local root = 'app.ropeway.'
local manager_name = root .. 'gamemastering.TimelineEventManager'
local flow_name, save_name = root .. 'gamemastering.MainFlowManager', root .. 'gamemastering.SaveDataManager'
local content_name, performance_name = root .. 'timeline.TimelineContents', root .. 'timeline.PerformanceInfo'
local movie_name, event_name = root .. 'gamemastering.MovieManager', root .. 'timeline.TimelineDefine.EventID'
local camera_getters = {in_event='get_InCameraEvent', standby='get_CameraEventStandby',
    playing='get_CameraEventPlay', skip_enabled='get_CameraEventEnableSkip',
    skipped='get_CameraEventSkiped', no_subtitle='get_CameraEventNoSubtitle'}
local content_booleans = {paused='get_IsPause', standby='get_IsCameraEventStandby',
    skip_enabled='get_EnableSkip', active='get_IsActive'}

local function integer(value)
    assert(math.type(value) == 'integer' and value >= -0x80000000 and value <= 0x7fffffff, 'invalid_timeline_integer')
    return value
end
local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_timeline_boolean')
    return value
end
local function finite(value)
    assert(type(value) == 'number' and value == value and value > -math.huge and value < math.huge,
        'invalid_timeline_number')
    return value
end
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= 'table' then return a == b end
    for key, value in pairs(a) do if not same(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_timeline_build')
    local function method(type_name, name, returns, static)
        local def = assert(sdk.find_type_definition(type_name), 'missing_timeline_type:' .. type_name)
        local member = assert(def:get_method(name), 'missing_timeline_method:' .. name)
        assert(member:is_static() == (static == true) and #member:get_param_types() == 0
            and member:get_return_type():get_full_name() == returns, 'unsupported_timeline_method:' .. name)
    end
    local function field(type_name, name, expected)
        local member = assert(sdk.find_type_definition(type_name):get_field(name), 'missing_timeline_field:' .. name)
        assert(not member:is_static() and member:get_type():get_full_name() == expected, 'unsupported_timeline_field:' .. name)
    end
    for _, name in pairs(camera_getters) do method(manager_name, name, 'System.Boolean') end
    method(manager_name, 'get_CurrentFrameForWwise', 'System.Single')
    method(manager_name, 'get_ActivateContentsList', content_name .. '[]')
    field(manager_name, '_ActiveCameraEventInfo', performance_name)
    field(manager_name, '_CurrentPauseState', manager_name .. '.CameraEventPauseState')
    for _, name in ipairs({'_PauseEvent', '_ExecPause'}) do field(manager_name, name, 'System.Boolean') end
    method(movie_name, 'get_IsPlayingMovie', 'System.Boolean')
    for _, name in ipairs({'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene'}) do
        method(flow_name, name, 'System.Boolean')
    end
    method(save_name, 'get_IsBusy', 'System.Boolean')
    method('via.SceneManager', 'get_CurrentScene', 'via.Scene', true)
    for _, name in pairs(content_booleans) do method(content_name, name, 'System.Boolean') end
    method(content_name, 'get_EventID', event_name)
    method(content_name, 'get_CurrentState', content_name .. '.ProcessState')
    method(content_name, 'get_CurrentOrder', manager_name .. '.EventOrder')
    method(content_name, 'get_CurrentMovieFrame', 'System.Single')
    method(performance_name, 'get_ID', event_name)
    method(performance_name, 'get_FlowID', 'System.String')
    method(performance_name, 'get_State', performance_name .. '.EventState')
    method(performance_name, 'get_RefTimeline', 'via.timeline.Timeline')
    for _, name in ipairs({'get_IsCameraEvent', 'get_EnableSkip', 'get_Skiped'}) do
        method(performance_name, name, 'System.Boolean')
    end
    method('via.timeline.Timeline', 'get_Frame', 'System.Single')
    method('via.timeline.Timeline', 'get_PlaySpeed', 'System.Single')
    method('via.timeline.Timeline', 'get_PlayState', 'via.timeline.PlayState')
    method('via.timeline.Timeline', 'get_ValidTimeline', 'System.Boolean')
    local scene_type = sdk.find_type_definition('via.SceneManager')

    local function object(value, expected, identities)
        assert(value and value:get_type_definition():get_full_name() == expected, 'unsupported_timeline_object:' .. expected)
        identities[#identities + 1] = tostring(value:get_address())
        return value
    end
    local function read()
        local flow, save = sdk.get_managed_singleton(flow_name), sdk.get_managed_singleton(save_name)
        if not flow or not save then return nil end
        if boolean(flow:call('get_IsInTitle')) or boolean(flow:call('get_IsInLoadGameData'))
            or not boolean(flow:call('get_IsFinishedLoadScene')) or boolean(save:call('get_IsBusy')) then return nil end
        local manager = sdk.get_managed_singleton(manager_name)
        local movies = sdk.get_managed_singleton(movie_name)
        local native = sdk.get_native_singleton('via.SceneManager')
        local scene = native and sdk.call_native_func(native, scene_type, 'get_CurrentScene')
        if not manager or not movies or not scene then return nil end
        local identities = {}
        object(flow, flow_name, identities); object(save, save_name, identities)
        object(manager, manager_name, identities); object(movies, movie_name, identities); object(scene, 'via.Scene', identities)
        local camera = {}
        for key, name in pairs(camera_getters) do camera[key] = boolean(manager:call(name)) end
        -- An audio-related frame is not substituted for the actual timeline frame.
        camera.wwise_frame = finite(manager:call('get_CurrentFrameForWwise'))
        camera.pause_state = integer(manager:get_field('_CurrentPauseState'))
        camera.pause_requested = boolean(manager:get_field('_PauseEvent'))
        camera.pause_executed = boolean(manager:get_field('_ExecPause'))
        local list = assert(manager:call('get_ActivateContentsList'), 'timeline_contents_unavailable')
        local count = integer(list:get_size())
        assert(count >= 0 and count <= 64, 'timeline_contents_limit')
        local contents, event_ids = {}, {}
        for index = 0, count - 1 do
            local item = object(list:get_element(index), content_name, identities)
            local event_id = integer(item:call('get_EventID'))
            assert(not event_ids[event_id], 'duplicate_timeline_event')
            event_ids[event_id] = true
            local value = {event_id=event_id, process_state=integer(item:call('get_CurrentState')),
                order=integer(item:call('get_CurrentOrder')), movie_frame=finite(item:call('get_CurrentMovieFrame'))}
            for key, name in pairs(content_booleans) do value[key] = boolean(item:call(name)) end
            contents[#contents + 1] = value
        end
        assert(list:get_size() == count, 'timeline_contents_changed')
        table.sort(contents, function(a,b) return a.event_id < b.event_id end)
        local performance = {present=false}
        local active = manager:get_field('_ActiveCameraEventInfo')
        if active then
            object(active, performance_name, identities)
            local flow_id = active:call('get_FlowID')
            assert(type(flow_id) == 'string' and #flow_id <= 256, 'invalid_timeline_flow_id')
            performance = {present=true, event_id=integer(active:call('get_ID')), flow_id=flow_id,
                event_state=integer(active:call('get_State')), camera=boolean(active:call('get_IsCameraEvent')),
                skip_enabled=boolean(active:call('get_EnableSkip')), skipped=boolean(active:call('get_Skiped')),
                timeline={present=false}}
            local timeline = active:call('get_RefTimeline')
            if timeline then
                object(timeline, 'via.timeline.Timeline', identities)
                performance.timeline = {present=true, frame=finite(timeline:call('get_Frame')),
                    play_state=integer(timeline:call('get_PlayState')), speed=finite(timeline:call('get_PlaySpeed')),
                    valid=boolean(timeline:call('get_ValidTimeline'))}
            end
        end
        return {camera=camera, active_count=count, contents=contents, camera_performance=performance,
            movie_playing=boolean(movies:call('get_IsPlayingMovie'))}, table.concat(identities, ':')
    end
    return {capture=function()
        local ok, first, first_objects = pcall(read)
        if not ok then return nil, 'state_read_failed', tostring(first) end
        if not first then return nil, 'scene_unavailable' end
        local success, second, second_objects = pcall(read)
        if not success then return nil, 'state_read_failed', tostring(second) end
        if not second or first_objects ~= second_objects or not same(first, second) then return nil, 'state_changed' end
        return first, 'ok'
    end}
end
return M
