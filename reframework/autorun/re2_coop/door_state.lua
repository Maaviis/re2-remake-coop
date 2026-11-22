-- Read the common native state of doors in the loaded scene.
local M = {}
local root = 'app.ropeway.'
local door = root .. 'gimmick.action.GimmickDoorBase'
local body = root .. 'gimmick.action.GimmickBody'
local action = root .. 'gimmick.action.GimmickAction'
local saved = door .. '.DoorSaveData'
local flow = root .. 'gamemastering.MainFlowManager'
local scene_name = 'via.Scene'

local function definition(name)
    return assert(sdk.find_type_definition(name), 'missing_door_type:' .. name)
end

local function getter(owner, name, returns)
    local method = assert(definition(owner):get_method(name), 'missing_door_method:' .. name)
    assert(not method:is_static() and #method:get_param_types() == 0
        and method:get_return_type():get_full_name() == returns, 'unsupported_door_method:' .. name)
    return method
end

local function field(owner, name, expected)
    local member = assert(definition(owner):get_field(name), 'missing_door_field:' .. name)
    assert(not member:is_static() and member:get_type():get_full_name() == expected,
        'unsupported_door_field:' .. name)
    return member
end

local function integer(value, low, high)
    assert(math.type(value) == 'integer' and value >= low and value <= high, 'invalid_door_integer')
    return value
end

local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_door_flag')
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
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_door_build')
    local is_title = getter(flow, 'get_IsInTitle', 'System.Boolean')
    local is_loading = getter(flow, 'get_IsInLoadGameData', 'System.Boolean')
    local is_loaded = getter(flow, 'get_IsFinishedLoadScene', 'System.Boolean')
    local scenario_type = getter(flow, 'get_CurrentScenarioType', flow .. '.ScenarioType')
    local folder = getter(body, 'get_FolderHash', 'System.UInt32')
    local map = field(body, 'AssignMapID', root .. 'gamemastering.Map.ID')
    local saved_loaded = field(action, '_HasSaveDataLoaded', 'System.Boolean')
    local saved_data = field(door, '_SaveData', saved)
    local ever_opened = field(saved, 'HasOpened', 'System.Boolean')
    local opened = getter(door, 'get_IsOpened', 'System.Boolean')
    local locked = getter(door, 'get_IsLocked', 'System.Boolean')
    local locked_by_key = getter(door, 'get_IsLockedByKey', 'System.Boolean')
    local opened_side = getter(door, 'get_OpenedSide', door .. '.SideType')
    local get_object = getter('via.Component', 'get_GameObject', 'via.GameObject')
    local get_name = getter('via.GameObject', 'get_Name', 'System.String')
    local scene_type = definition('via.SceneManager')
    local component_type = assert(sdk.typeof(door), 'native_door_component_unavailable')

    local function read()
        local current = sdk.get_managed_singleton(flow)
        if not current or boolean(is_title:call(current)) or boolean(is_loading:call(current))
            or not boolean(is_loaded:call(current)) then return nil end
        local manager = sdk.get_native_singleton('via.SceneManager')
        local scene = manager and sdk.call_native_func(manager, scene_type, 'get_CurrentScene')
        if not scene or scene:get_type_definition():get_full_name() ~= scene_name then return nil end
        local components = assert(scene:call('findComponents', component_type), 'native_door_list_unavailable')
        local count = integer(components:get_size(), 0, 512)
        local rows, identities = {}, {}
        for index = 0, count - 1 do
            local component = assert(components:get_element(index), 'native_door_unavailable')
            local class = component:get_type_definition()
            assert(class:is_a(door), 'foreign_door_component')
            local object = assert(get_object:call(component), 'native_door_object_unavailable')
            local name = get_name:call(object)
            assert(type(name) == 'string' and #name > 0 and #name <= 192 and not name:find('%c'),
                'invalid_door_object_name')
            local map_id = integer(map:get_data(component), 0, 0xffffffff)
            local hash = integer(folder:call(component), 0, 0xffffffff)
            local id = ('%08x:%08x:%s'):format(map_id, hash, name)
            assert(identities[id] == nil, 'ambiguous_door_identity')
            identities[id] = {component:get_address(), object:get_address()}

            local data = saved_data:get_data(component)
            local record = {id=id, map=map_id, folder_hash=hash, name=name, class=class:get_full_name(),
                opened=boolean(opened:call(component)), locked=boolean(locked:call(component)),
                locked_by_key=boolean(locked_by_key:call(component)),
                saved={loaded=boolean(saved_loaded:get_data(component)), present=data ~= nil}}
            if record.opened then
                record.opened_side = integer(opened_side:call(component), -0x80000000, 0x7fffffff)
            end
            if data then record.saved.has_opened = boolean(ever_opened:get_data(data)) end
            rows[#rows + 1] = record
        end
        assert(components:get_size() == count, 'native_door_set_changed')
        table.sort(rows, function(a, b) return a.id < b.id end)
        return {scenario=integer(scenario_type:call(current), 0, 3), door_count=count, doors=rows},
            scene:get_address(), identities
    end

    return {capture = function()
        local ok, first, scene, ids = pcall(read)
        if not ok then return nil, 'door_read_failed', tostring(first) end
        if not first then return nil, 'door_scene_unavailable' end
        local copied, second, next_scene, next_ids = pcall(read)
        if not copied then return nil, 'door_read_failed', tostring(second) end
        if not second or scene ~= next_scene or not same(ids, next_ids) or not same(first, second) then
            return nil, 'door_state_changed'
        end
        return first, 'ok'
    end}
end

return M
