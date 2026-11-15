-- Read-only registered enemy evidence. Missing controllers never mean death or despawn.
local M = {}
local root = 'app.ropeway.'
local manager_name, record_name = root .. 'EnemyManager', root .. 'EnemyManager.RegisterEnemyInfo'
local context_name, data_name = root .. 'enemy.EmCommonContext', root .. 'enemy.savedata.EmSaveData'
local controller_name, hp_name = root .. 'EnemyController', root .. 'EnemyHitPointController'
local flow_name, save_name = root .. 'gamemastering.MainFlowManager', root .. 'gamemastering.SaveDataManager'
local header_name, kind_name = flow_name .. '.GameHeaderSaveData', root .. 'EnemyDefine.KindID'
local list_name = 'System.Collections.Generic.List`1<' .. record_name .. '>'
local active_list_name = 'System.Collections.Generic.List`1<' .. controller_name .. '>'
local MAX_ENEMIES = 512

local function integer(value, low, high)
    assert(math.type(value) == 'integer' and value >= low and value <= high, 'invalid_enemy_integer')
    return value
end
local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_enemy_boolean')
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
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_enemy_build')
    local function method(type_name, name, returns, params, static)
        local def = assert(sdk.find_type_definition(type_name), 'missing_enemy_type:' .. type_name)
        local member = assert(def:get_method(name), 'missing_enemy_method:' .. name)
        local actual, actual_return = member:get_param_types(), member:get_return_type():get_full_name()
        assert(member:is_static() == (static == true) and #actual == #(params or {})
            and (returns == nil and actual_return ~= 'System.Void' or actual_return == returns),
            'unsupported_enemy_method:' .. name)
        for index, expected in ipairs(params or {}) do
            assert(actual[index]:get_full_name() == expected, 'unsupported_enemy_parameter:' .. name)
        end
    end
    local function field(type_name, name, expected)
        local member = assert(sdk.find_type_definition(type_name):get_field(name), 'missing_enemy_field:' .. name)
        assert(not member:is_static() and member:get_type():get_full_name() == expected,
            'unsupported_enemy_field:' .. name)
    end
    method(manager_name, 'get_EnemyList', list_name)
    method(manager_name, 'get_ActiveEnemyList', active_list_name)
    method(manager_name, 'get_IsPausing', 'System.Boolean')
    field(manager_name, 'TotalEnemyKillCount', 'System.UInt32')
    for _, name in ipairs({list_name, active_list_name}) do
        method(name, 'get_Count', 'System.Int32')
        method(name, 'get_Item(System.Int32)', nil, {'System.Int32'})
    end
    for name, returns in pairs({get_GUID = 'System.Guid', get_KindID = kind_name,
            get_Context = context_name, get_ContextData = data_name, get_Controller = controller_name}) do
        method(record_name, name, returns)
    end
    for name, returns in pairs({get_InheritID = 'System.Int32', get_IsEliminated = 'System.Boolean',
            get_Status = context_name .. '.InstanceStatus', get_ContextPosition = 'via.vec3',
            get_ContextRotation = 'via.Quaternion'}) do method(context_name, name, returns) end
    field(context_name, 'GUID', 'System.Guid')
    for name, returns in pairs({GUID = 'System.Guid', InheritID = 'System.Int32', KindID = kind_name,
            SceneID = root .. 'gamemastering.Map.ID', AreaID = root .. 'gamemastering.Map.Area',
            FlagData = 'System.UInt32'}) do field(data_name, name, returns) end
    for name, returns in pairs({get_DefaultHitPoint = 'System.Int32', get_CurrentHitPoint = 'System.Int32',
            get_Eliminated = 'System.Boolean', get_Position = 'via.vec3', get_Rotation = 'via.Quaternion'}) do
        method(data_name, name, returns)
    end
    field(controller_name, '<ContextGUID>k__BackingField', 'System.Guid')
    field(controller_name, '<HitPoint>k__BackingField', hp_name)
    for name, returns in pairs({get_InheritID = 'System.Int32', get_KindID = kind_name,
            get_IsActiveEnemy = 'System.Boolean', get_IsLive = 'System.Boolean', get_Setupped = 'System.Boolean',
            get_Loading = 'System.Boolean', get_IsStandby = 'System.Boolean',
            get_ConditionBits = 'System.UInt32', get_ConditionBits2 = 'System.UInt32'}) do
        method(controller_name, name, returns)
    end
    for name, returns in pairs({get_CurrentHitPoint = 'System.Int32', get_DefaultHitPoint = 'System.Int32',
            get_IsDead = 'System.Boolean'}) do method(root .. 'HitPointController', name, returns) end
    for _, name in ipairs({'get_IsInTitle', 'get_IsInLoadGameData', 'get_IsFinishedLoadScene'}) do
        method(flow_name, name, 'System.Boolean')
    end
    method(flow_name, 'get_CurrentScenarioType', flow_name .. '.ScenarioType')
    method(flow_name, 'get_LoadLocation', root .. 'gamemastering.Location.ID')
    method(save_name, 'get_IsBusy', 'System.Boolean')
    field(flow_name, 'gameHeaderSaveData', header_name)
    for _, name in ipairs({'GameGUID', 'SaveGUID'}) do field(header_name, name, 'System.Guid') end
    field('System.Guid', 'mData1', 'System.UInt32')
    for _, name in ipairs({'mData2', 'mData3'}) do field('System.Guid', name, 'System.UInt16') end
    for index = 0, 7 do field('System.Guid', 'mData4_' .. index, 'System.Byte') end
    method('via.SceneManager', 'get_CurrentScene', 'via.Scene', nil, true)
    local scene_type = assert(sdk.find_type_definition('via.SceneManager'))

    local function object(value, expected)
        assert(value, 'enemy_object_unavailable:' .. expected)
        local def = value:get_type_definition()
        for _ = 1, 16 do
            if not def then break end
            if def:get_full_name() == expected then return value end
            def = def:get_parent_type()
        end
        error('unsupported_enemy_object:' .. expected)
    end
    local function guid(value)
        object(value, 'System.Guid')
        local bytes = {}
        for index = 0, 7 do bytes[index + 1] = integer(value:get_field('mData4_' .. index), 0, 255) end
        return ('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
            integer(value:get_field('mData1'), 0, 0xffffffff), integer(value:get_field('mData2'), 0, 0xffff),
            integer(value:get_field('mData3'), 0, 0xffff), table.unpack(bytes))
    end
    local function vector(value, rotation)
        assert(value, 'enemy_transform_unavailable')
        local out = {}
        for _, key in ipairs(rotation and {'x', 'y', 'z', 'w'} or {'x', 'y', 'z'}) do
            local n = value[key]
            assert(type(n) == 'number' and n == n and math.abs(n) < math.huge, 'invalid_enemy_transform')
            out[#out + 1] = n
        end
        if rotation then
            local norm = 0
            for _, n in ipairs(out) do norm = norm + n * n end
            assert(norm > 0 and norm < math.huge, 'invalid_enemy_rotation')
        end
        return out
    end
    local function signed(value) return integer(value, -0x80000000, 0x7fffffff) end
    local function unsigned(value) return integer(value, 0, 0xffffffff) end
    local function record(value, identities)
        object(value, record_name)
        local id = guid(value:call('get_GUID'))
        assert(id ~= '00000000-0000-0000-0000-000000000000', 'empty_enemy_guid')
        local kind = signed(value:call('get_KindID'))
        local result = {id = id, kind_id = kind}
        identities[#identities + 1] = tostring(value:get_address())
        local context = value:call('get_Context')
        result.context = {present = context ~= nil}
        if context then
            object(context, context_name)
            assert(guid(context:get_field('GUID')) == id, 'enemy_context_identity_mismatch')
            identities[#identities + 1] = tostring(context:get_address())
            result.context = {present = true, inherit_id = signed(context:call('get_InheritID')),
                eliminated = boolean(context:call('get_IsEliminated')), status = signed(context:call('get_Status')),
                position = vector(context:call('get_ContextPosition')),
                rotation = vector(context:call('get_ContextRotation'), true)}
        end
        local stored = value:call('get_ContextData')
        result.stored = {present = stored ~= nil}
        if stored then
            object(stored, data_name)
            assert(guid(stored:get_field('GUID')) == id and signed(stored:get_field('KindID')) == kind,
                'enemy_stored_identity_mismatch')
            identities[#identities + 1] = tostring(stored:get_address())
            result.stored = {present = true, inherit_id = signed(stored:get_field('InheritID')),
                default_hp = signed(stored:call('get_DefaultHitPoint')), hp = signed(stored:call('get_CurrentHitPoint')),
                eliminated = boolean(stored:call('get_Eliminated')), flags = unsigned(stored:get_field('FlagData')),
                map = signed(stored:get_field('SceneID')), area = signed(stored:get_field('AreaID')),
                position = vector(stored:call('get_Position')), rotation = vector(stored:call('get_Rotation'), true)}
        end
        assert(context or stored, 'enemy_record_without_context')
        local live = value:call('get_Controller')
        result.live = {present = live ~= nil}
        if live then
            object(live, controller_name)
            assert(guid(live:get_field('<ContextGUID>k__BackingField')) == id
                and signed(live:call('get_KindID')) == kind, 'enemy_live_identity_mismatch')
            local hp = object(live:get_field('<HitPoint>k__BackingField'), hp_name)
            identities[#identities + 1] = tostring(live:get_address()) .. ':' .. tostring(hp:get_address())
            result.live = {present = true, inherit_id = signed(live:call('get_InheritID')),
                active = boolean(live:call('get_IsActiveEnemy')), is_live = boolean(live:call('get_IsLive')),
                setup = boolean(live:call('get_Setupped')), loading = boolean(live:call('get_Loading')),
                standby = boolean(live:call('get_IsStandby')), conditions = unsigned(live:call('get_ConditionBits')),
                conditions2 = unsigned(live:call('get_ConditionBits2')),
                default_hp = signed(hp:call('get_DefaultHitPoint')), hp = signed(hp:call('get_CurrentHitPoint')),
                is_dead = boolean(hp:call('get_IsDead'))}
        end
        return result, live and live:get_address()
    end
    local function read()
        local flow, save, enemies = sdk.get_managed_singleton(flow_name), sdk.get_managed_singleton(save_name),
            sdk.get_managed_singleton(manager_name)
        if not flow or not save or not enemies then return nil end
        if boolean(save:call('get_IsBusy')) or boolean(flow:call('get_IsInTitle'))
            or boolean(flow:call('get_IsInLoadGameData')) or not boolean(flow:call('get_IsFinishedLoadScene')) then return nil end
        local players = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        local player = players and players:call('get_CurrentPlayer')
        local native = sdk.get_native_singleton('via.SceneManager')
        local scene = native and sdk.call_native_func(native, scene_type, 'get_CurrentScene')
        if not player or not scene then return nil end
        object(scene, 'via.Scene')
        local header = object(flow:get_field('gameHeaderSaveData'), header_name)
        local registry = object(enemies:call('get_EnemyList'), list_name)
        local active = object(enemies:call('get_ActiveEnemyList'), active_list_name)
        local count = integer(registry:call('get_Count'), 0, MAX_ENEMIES)
        local active_count = integer(active:call('get_Count'), 0, count)
        local result = {checkpoint = {game_guid = guid(header:get_field('GameGUID')),
            save_guid = guid(header:get_field('SaveGUID')), scenario = signed(flow:call('get_CurrentScenarioType')),
            location = signed(flow:call('get_LoadLocation'))}, registered_count = count, active_count = active_count,
            total_kills = unsigned(enemies:get_field('TotalEnemyKillCount')),
            paused = boolean(enemies:call('get_IsPausing')), entries = {}}
        local identities = {tostring(scene:get_address()), tostring(player:get_address()),
            tostring(enemies:get_address()), tostring(registry:get_address()), tostring(active:get_address())}
        local by_id, active_ids, live_objects = {}, {}, {}
        for index = 0, count - 1 do
            local item, live_address = record(registry:call('get_Item(System.Int32)', index), identities)
            assert(not by_id[item.id], 'duplicate_enemy_guid')
            by_id[item.id], result.entries[#result.entries + 1] = item, item
            live_objects[item.id] = live_address
        end
        for index = 0, active_count - 1 do
            local controller = object(active:call('get_Item(System.Int32)', index), controller_name)
            local id = guid(controller:get_field('<ContextGUID>k__BackingField'))
            assert(not active_ids[id] and by_id[id] and by_id[id].live.present and by_id[id].live.active
                and live_objects[id] == controller:get_address(),
                'enemy_active_registry_mismatch')
            active_ids[id] = true
        end
        for id, item in pairs(by_id) do
            assert(not item.live.present or item.live.active == (active_ids[id] == true), 'enemy_active_set_changed')
        end
        assert(registry:call('get_Count') == count and active:call('get_Count') == active_count, 'enemy_registry_changed')
        table.sort(result.entries, function(a, b) return a.id < b.id end)
        return result, table.concat(identities, ':')
    end
    return {capture = function()
        local ok, first, first_objects = pcall(read)
        if not ok then return nil, 'enemy_read_failed', tostring(first) end
        if not first then return nil, 'scene_unavailable' end
        local success, second, second_objects = pcall(read)
        if not success then return nil, 'enemy_read_failed', tostring(second) end
        if not second or first_objects ~= second_objects or not same(first, second) then return nil, 'enemy_state_changed' end
        return first, 'ok'
    end}
end

return M
