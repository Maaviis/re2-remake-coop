-- Read item placement markers, their live objects, and the native save table.
local M = {}
local root = 'app.ropeway.'
local manager = root .. 'gamemastering.ItemManager'
local flow = root .. 'gamemastering.MainFlowManager'
local item = root .. 'gimmick.action.SetItem'
local position = root .. 'item.ItemPositions'
local saved = item .. '.SetItemSaveData'
local behavior = root .. 'RopewayBehaviorRoot'
local list = 'System.Collections.Generic.List`1<' .. saved .. '>'
local enum = root .. 'gamemastering.'
local max_rows = 2048
local zero_guid = '00000000-0000-0000-0000-000000000000'
local item_id, weapon, parts = enum .. 'Item.ID', root .. 'EquipmentDefine.WeaponType',
    root .. 'EquipmentDefine.WeaponParts'
local payload = {
    {'Type','item_id',item_id}, {'Count','count','System.Int32'},
    {'WeaponType','weapon',weapon}, {'WeaponParts','parts',parts}, {'BulletId','bullet',item_id},
    {'AdditionalItemId','extra_item',item_id}, {'AdditionalItemCount','extra_count','System.Int32'},
    {'AdditionalWeaponId','extra_weapon',weapon}, {'AdditionalWeaponParts','extra_parts',parts},
    {'AdditionalBulletId','extra_bullet',item_id},
}

local function def(name)
    return assert(sdk.find_type_definition(name), 'missing_world_item_type:' .. name)
end

local function method(owner, name, returns, parameter)
    local fn = assert(def(owner):get_method(name), 'missing_world_item_method:' .. name)
    local parameters = fn:get_param_types()
    assert(not fn:is_static() and fn:get_return_type():get_full_name() == returns
        and #parameters == (parameter and 1 or 0)
        and (not parameter or parameters[1]:get_full_name() == parameter), 'unsupported_world_item_method:' .. name)
    return fn
end

local function field(owner, name, expected)
    local member = assert(def(owner):get_field(name), 'missing_world_item_field:' .. name)
    assert(not member:is_static() and member:get_type():get_full_name() == expected,
        'unsupported_world_item_field:' .. name)
    return member
end

local function integer(value, low, high)
    assert(math.type(value) == 'integer' and value >= low and value <= high, 'invalid_world_item_integer')
    return value
end

local function number(value) return integer(value, -0x80000000, 0xffffffff) end

local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_world_item_flag')
    return value
end

local function guid(value)
    local bytes = {}
    for index = 0, 7 do bytes[index+1] = integer(value:get_field('mData4_' .. index), 0, 255) end
    return ('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
        integer(value:get_field('mData1'), 0, 0xffffffff), integer(value:get_field('mData2'), 0, 0xffff),
        integer(value:get_field('mData3'), 0, 0xffff), table.unpack(bytes))
end

local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= 'table' then return a == b end
    for key, value in pairs(a) do if not same(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_world_item_build')
    local title = method(flow, 'get_IsInTitle', 'System.Boolean')
    local loading = method(flow, 'get_IsInLoadGameData', 'System.Boolean')
    local loaded = method(flow, 'get_IsFinishedLoadScene', 'System.Boolean')
    local scenario = method(flow, 'get_CurrentScenarioType', flow .. '.ScenarioType')
    local pos_guid = field(position, 'MyGuid', 'System.Guid')
    local pos_location = method(position, 'get_MyLocation', enum .. 'Location.ID')
    local pos_map = method(position, 'get_MyMap', enum .. 'Map.ID')
    local location_lists = field(manager .. '.SaveData', 'SetItemsList', manager .. '.SetItems[]')
    local manager_save = field(manager, 'GameSaveData', manager .. '.SaveData')
    local stored_rows = field(manager .. '.SetItems', 'Items', list)
    local list_count = method(list, 'get_Count', 'System.Int32')
    local list_item = method(list, 'get_Item', saved, 'System.Int32')
    local attached = method(item, 'get_SaveData', saved)
    local started = field(behavior, '<isStarted>k__BackingField', 'System.Boolean')
    local interacted = method(item, 'get_DisableInteract', 'System.Boolean')
    local asleep = method(item, 'get_ColliderSleep', 'System.Boolean')
    local stored_enabled = field(saved, 'Enable', 'System.Boolean')
    local stored_colliders = field(saved, 'EnableColliders', 'System.Boolean')
    local position_type, item_type = assert(sdk.typeof(position)), assert(sdk.typeof(item))
    local scene_type = def('via.SceneManager')

    local function row_reader(owner)
        local id = field(owner, 'ItemPositionGuid', 'System.Guid')
        local location = field(owner, 'Location', enum .. 'Location.ID')
        local map = field(owner, 'Map', enum .. 'MapParts.ID')
        local fields = {}
        for _, row in ipairs(payload) do fields[row[2]] = field(owner, row[1], row[3]) end
        return function(object)
            local row = {id=guid(id:get_data(object)), location=number(location:get_data(object)),
                map=number(map:get_data(object)), payload={}}
            for key, value in pairs(fields) do row.payload[key] = number(value:get_data(object)) end
            return row
        end
    end
    local live_row, saved_row = row_reader(item), row_reader(saved)

    local function stored_row(object)
        local row = saved_row(object)
        row.enabled = boolean(stored_enabled:get_data(object))
        row.colliders = boolean(stored_colliders:get_data(object))
        return row
    end

    local function read()
        local current = sdk.get_managed_singleton(flow)
        if not current or boolean(title:call(current)) or boolean(loading:call(current))
            or not boolean(loaded:call(current)) then return nil end
        local scene_manager = sdk.get_native_singleton('via.SceneManager')
        local scene = scene_manager and sdk.call_native_func(scene_manager, scene_type, 'get_CurrentScene')
        local item_manager = sdk.get_managed_singleton(manager)
        if not scene or not item_manager then return nil end
        local save = assert(manager_save:get_data(item_manager), 'missing_world_item_save')
        local buckets = assert(location_lists:get_data(save), 'missing_world_item_buckets')
        local marker_list = assert(scene:call('findComponents', position_type), 'world_item_positions_unavailable')
        local live_list = assert(scene:call('findComponents', item_type), 'world_item_objects_unavailable')
        local marker_count = integer(marker_list:get_size(), 0, max_rows)
        local live_count = integer(live_list:get_size(), 0, max_rows)
        local bucket_count = integer(buckets:get_size(), 1, 128)
        local rows = {positions={}, live={}, storage={}}
        local ids, seen = {scene:get_address(),save:get_address(),buckets:get_address()}, {}
        for index = 0, marker_count - 1 do
            local marker = assert(marker_list:get_element(index))
            local id = guid(pos_guid:get_data(marker))
            assert(id ~= zero_guid and not seen[id], 'invalid_or_duplicate_world_item_position')
            seen[id] = true
            rows.positions[#rows.positions + 1] = {id=id, map=number(pos_map:call(marker)),
                location=number(pos_location:call(marker))}
            ids[#ids+1] = marker:get_address()
        end
        local unbound = 0
        for index = 0, live_count - 1 do
            local object = assert(live_list:get_element(index))
            local row = live_row(object)
            ids[#ids+1] = object:get_address()
            if row.id == zero_guid then
                unbound = unbound + 1
            else
                row.started = boolean(started:get_data(object))
                row.interaction_disabled = boolean(interacted:call(object))
                row.collider_asleep = boolean(asleep:call(object))
                local data = attached:call(object)
                if data then
                    row.saved = stored_row(data)
                    assert(row.saved.id == row.id, 'world_item_attached_to_another_position')
                    ids[#ids+1] = data:get_address()
                end
                rows.live[#rows.live + 1] = row
            end
        end
        for index = 0, bucket_count - 1 do
            local bucket = assert(buckets:get_element(index))
            local records = assert(stored_rows:get_data(bucket))
            local count = integer(list_count:call(records), 0, max_rows - #rows.storage)
            ids[#ids+1] = records:get_address()
            for row_index = 0, count - 1 do
                local record = assert(list_item:call(records, row_index))
                local row = stored_row(record)
                row.bucket = index
                rows.storage[#rows.storage + 1] = row
                ids[#ids+1] = record:get_address()
            end
            assert(list_count:call(records) == count, 'world_item_storage_changed')
        end
        assert(marker_list:get_size() == marker_count and live_list:get_size() == live_count
            and buckets:get_size() == bucket_count, 'world_item_set_changed')
        for key, value in pairs(rows) do rows[key] = {count=#value, records=value} end
        return {scenario=integer(scenario:call(current), 0, 3), unbound=unbound, groups=rows}, ids
    end

    return {capture=function()
        local ok, state, locals = pcall(read)
        if not ok then return nil, 'world_item_read_failed', tostring(state) end
        if not state then return nil, 'world_item_scene_unavailable' end
        local copied, second, next_locals = pcall(read)
        if not copied then return nil, 'world_item_read_failed', tostring(second) end
        if not same(locals, next_locals) or not same(state, second) then return nil, 'world_item_state_changed' end
        return state, 'ok'
    end}
end

return M
