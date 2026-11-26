-- Read-only RE2 load-header/inventory evidence, with opt-in details. Never releases gameplay.
local M = {}
local root = 'app.ropeway.'
local flow_name = root .. 'gamemastering.MainFlowManager'
local save_name = root .. 'gamemastering.SaveDataManager'
local gui_name = root .. 'gui.GUIMaster'
local inventory_name = root .. 'survivor.Inventory'
local slot_name = root .. 'inventory.Slot'
local manager_name = root .. 'gamemastering.InventoryManager'
local primitive_name, extra_name, stock_name = manager_name .. '.PrimitiveItem', manager_name .. '.ItemExData', manager_name .. '.StockItem'
local shortcut_name = root .. 'EquipmentDefine.Shortcut'
local dictionary_name = 'System.Collections.Generic.Dictionary`2<' .. shortcut_name .. ',' .. slot_name .. '>'
local header_name = flow_name .. '.GameHeaderSaveData'
local list_name = 'System.Collections.Generic.List`1<' .. slot_name .. '>'
local item_type = root .. 'gamemastering.Item.ID'
local weapon_type = root .. 'EquipmentDefine.WeaponType'
local survivor_type = root .. 'SurvivorDefine.SurvivorType'
-- These are payload fields, not computed slot getters. AdditionalItem is distinct from DefaultItem.
local primitive_fields = {item_id = {'ItemId', item_type}, weapon_type = {'WeaponId', weapon_type},
    weapon_parts = {'WeaponParts', root .. 'EquipmentDefine.WeaponParts'}, bullet_id = {'BulletId', item_type},
    number = {'Count', 'System.Int32'}}
local extra_fields = {uint_data = {'ExUintData', 'System.UInt32'}, item_id = {'ExItemID', item_type},
    rogue_weapon_level = {'RogueWeaponLevel', 'System.Int32'}, initial_set = {'IsInitialSet', 'System.Boolean'},
    initial_count = {'InitialCount', 'System.Int32'}}
local header_fields = {scenario = {'ScenarioTypeValue', flow_name .. '.ScenarioType'},
    survivor = {'SurvivorTypeValue', survivor_type}, difficulty = {'CurrentDifficulty', flow_name .. '.Difficulty'},
    location = {'LocationId', root .. 'gamemastering.Location.ID'}, saved_map = {'AreaId', root .. 'gamemastering.Map.ID'}}
local slot_fields = {stock_index = {'get_Index', 'System.Int32'}, slot_type = {'get_Type', root .. 'inventory.SlotType'},
    item_id = {'get_ItemID', item_type}, weapon_type = {'get_WeaponType', weapon_type},
    weapon_parts = {'get_WeaponParts', root .. 'EquipmentDefine.WeaponParts'}, bullet_id = {'get_BulletID', item_type},
    number = {'get_Number', 'System.Int32'}, has_stock = {'get_HasStock', 'System.Boolean'},
    blank = {'get_IsBlank', 'System.Boolean'}, force_blank = {'get_IsForceBlank', 'System.Boolean'},
    fat_slot = {'get_IsFatSlot', 'System.Boolean'}, dead_slot = {'get_IsDeadSlot', 'System.Boolean'},
    infinite = {'get_Infinity', 'System.Boolean'}}

local function integer(value, minimum, maximum)
    assert(math.type(value) == 'integer' and value >= minimum and value <= maximum, 'invalid_native_integer')
    return value
end
local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_native_boolean')
    return value
end
local function same(a, b)
    if type(a) ~= type(b) then return false end
    if type(a) ~= 'table' then return a == b end
    for key, value in pairs(a) do if not same(value, b[key]) then return false end end
    for key in pairs(b) do if a[key] == nil then return false end end
    return true
end

M.same_state = same

function M.new(options)
    options = options or {}
    assert(options.details == nil or type(options.details) == 'boolean', 'invalid_load_state_options')
    local details = options.details == true
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_load_state_build')
    local function method(type_name, name, returns, params)
        local def = assert(sdk.find_type_definition(type_name), 'missing_type:' .. type_name)
        local member = assert(def:get_method(name), 'missing_method:' .. name)
        local actual = member:get_param_types()
        local actual_return = member:get_return_type():get_full_name()
        assert(not member:is_static() and (returns == nil and actual_return ~= 'System.Void' or actual_return == returns)
            and #actual == #(params or {}), 'unsupported_method:' .. name)
        for i, expected in ipairs(params or {}) do
            assert(actual[i]:get_full_name() == expected, 'unsupported_parameter:' .. name)
        end
    end
    local function field(type_name, name, expected)
        local def = assert(sdk.find_type_definition(type_name), 'missing_type:' .. type_name)
        local member = assert(def:get_field(name), 'missing_field:' .. name)
        assert(not member:is_static() and member:get_type():get_full_name() == expected, 'unsupported_field:' .. name)
    end
    for _, spec in pairs(slot_fields) do method(slot_name, spec[1], spec[2]) end
    method(inventory_name, 'get_CurrentSlotSize', 'System.Int32')
    method(inventory_name, 'get_Slots', list_name)
    method(inventory_name, 'get_SurvivorType', survivor_type)
    method(inventory_name, 'get_RoleType', root .. 'SurvivorDefine.RoleType')
    for _, role in ipairs({'Main', 'Sub', 'Personal'}) do method(inventory_name, 'get_' .. role .. 'Slot', slot_name) end
    method(list_name, 'get_Count', 'System.Int32')
    -- Closed generic return metadata can be erased; each returned object's type is checked below.
    method(list_name, 'get_Item(System.Int32)', nil, {'System.Int32'})
    for _, name in ipairs({'get_IsInTitle', 'get_IsInLoadGameData', 'get_IsFinishedLoadScene'}) do
        method(flow_name, name, 'System.Boolean')
    end
    method(flow_name, 'get_CurrentScenarioType', flow_name .. '.ScenarioType')
    method(flow_name, 'get_LoadLocation', root .. 'gamemastering.Location.ID')
    method(save_name, 'get_IsBusy', 'System.Boolean')
    for _, name in ipairs({'isTitleMenuOpened', 'isBusyMenuMain', 'isBusyMenuStory', 'isBusyLoad'}) do
        method(gui_name, name, 'System.Boolean')
    end
    field(flow_name, 'gameHeaderSaveData', header_name)
    for _, spec in pairs(header_fields) do field(header_name, spec[1], spec[2]) end
    for _, name in ipairs({'GameGUID', 'SaveGUID'}) do field(header_name, name, 'System.Guid') end
    field('System.Guid', 'mData1', 'System.UInt32')
    for _, name in ipairs({'mData2', 'mData3'}) do field('System.Guid', name, 'System.UInt16') end
    for i = 0, 7 do field('System.Guid', 'mData4_' .. i, 'System.Byte') end
    if details then
        for _, spec in pairs(primitive_fields) do field(primitive_name, spec[1], spec[2]) end
        for _, spec in pairs(extra_fields) do field(extra_name, spec[1], spec[2]) end
        field(stock_name, 'Index', 'System.Int32'); field(stock_name, 'IsWeaponEquip', 'System.Boolean')
        field(manager_name .. '.ItemData', 'DefaultItem', primitive_name)
        field(manager_name .. '.ItemData', 'AdditionalItem', primitive_name)
        field(manager_name .. '.ItemData', 'ExData', extra_name)
        field(slot_name, '_LastWeaponType', weapon_type)
        method(slot_name, 'get_Stock', stock_name)
        method(slot_name, 'get_InnerData', primitive_name)
        method(slot_name, 'get_ExtendData', extra_name)
        for _, name in ipairs({'_MainShortcutSlots', '_SubShortcutSlots'}) do field(inventory_name, name, dictionary_name) end
        method(dictionary_name, 'get_Count', 'System.Int32')
        method(dictionary_name, 'ContainsKey', 'System.Boolean', {shortcut_name})
        method(dictionary_name, 'get_Item', nil, {shortcut_name})
        local def = assert(sdk.find_type_definition(shortcut_name), 'missing_shortcut_enum')
        for index, name in ipairs({'Up', 'Down', 'Left', 'Right'}) do
            local member = assert(def:get_field(name), 'missing_shortcut_key')
            assert(member:is_static() and member:get_type():get_full_name() == shortcut_name
                and member:get_data(nil) == index - 1, 'unsupported_shortcut_enum')
        end
    end
    local inventory_type = assert(sdk.typeof(inventory_name), 'inventory_component_unavailable')

    local function guid(value)
        assert(value, 'guid_unavailable')
        local bytes = {}
        for i = 0, 7 do bytes[i + 1] = integer(value:get_field('mData4_' .. i), 0, 255) end
        return ('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
            integer(value:get_field('mData1'), 0, 0xffffffff), integer(value:get_field('mData2'), 0, 0xffff),
            integer(value:get_field('mData3'), 0, 0xffff), table.unpack(bytes))
    end
    local function payload(value, type_name, specs)
        if value == nil then return {present = false} end
        assert(value:get_type_definition():get_full_name() == type_name, 'unsupported_item_payload')
        local result = {present = true}
        for name, spec in pairs(specs) do
            local native = value:get_field(spec[1])
            if spec[2] == 'System.Boolean' then result[name] = boolean(native)
            elseif spec[2] == 'System.UInt32' then result[name] = integer(native, 0, 0xffffffff)
            else result[name] = integer(native, -0x80000000, 0xffffffff) end
        end
        return result
    end
    local function stock(value)
        if value == nil then return {present = false} end
        assert(value:get_type_definition():get_full_name() == stock_name, 'unsupported_stock_object')
        return {present = true, index = integer(value:get_field('Index'), -0x80000000, 0x7fffffff),
            weapon_equipped = boolean(value:get_field('IsWeaponEquip')),
            default_item = payload(value:get_field('DefaultItem'), primitive_name, primitive_fields),
            additional_item = payload(value:get_field('AdditionalItem'), primitive_name, primitive_fields),
            extra = payload(value:get_field('ExData'), extra_name, extra_fields)}
    end
    local function slot(value)
        if value == nil then return {present = false} end
        assert(value:get_type_definition():get_full_name() == slot_name, 'unsupported_slot_object')
        local result = {present = true}
        for name, spec in pairs(slot_fields) do
            local native = value:call(spec[1])
            if spec[2] == 'System.Boolean' then result[name] = boolean(native)
            else result[name] = integer(native, -0x80000000, 0xffffffff) end
        end
        if details then
            result.last_weapon_type = integer(value:get_field('_LastWeaponType'), -0x80000000, 0xffffffff)
            result.stock = stock(value:call('get_Stock'))
            result.inner = payload(value:call('get_InnerData'), primitive_name, primitive_fields)
            result.extra = payload(value:call('get_ExtendData'), extra_name, extra_fields)
        end
        return result
    end
    local function shortcuts(inventory, name)
        local dictionary = assert(inventory:get_field(name), 'shortcut_dictionary_unavailable')
        assert(dictionary:get_type_definition():get_full_name() == dictionary_name, 'unsupported_shortcut_dictionary')
        local count = integer(dictionary:call('get_Count'), 0, 4)
        local entries = {}
        for key = 0, 3 do
            if boolean(dictionary:call('ContainsKey', key)) then
                local value = assert(dictionary:call('get_Item', key), 'shortcut_slot_unavailable')
                entries[#entries + 1] = {key = key, slot = slot(value)}
            end
        end
        assert(#entries == count and dictionary:call('get_Count') == count, 'shortcut_dictionary_changed')
        return {count = count, entries = entries}
    end
    local function read()
        local flow, manager, gui = sdk.get_managed_singleton(flow_name), sdk.get_managed_singleton(save_name),
            sdk.get_managed_singleton(gui_name)
        if not flow or not manager or not gui then return nil end
        if boolean(manager:call('get_IsBusy')) or boolean(flow:call('get_IsInTitle'))
            or boolean(flow:call('get_IsInLoadGameData')) or not boolean(flow:call('get_IsFinishedLoadScene')) then return nil end
        for _, name in ipairs({'isTitleMenuOpened', 'isBusyMenuMain', 'isBusyMenuStory', 'isBusyLoad'}) do
            if boolean(gui:call(name)) then return nil end
        end
        local players = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        local player = players and players:call('get_CurrentPlayer')
        if not player then return nil end
        local inventory = player:call('getComponent(System.Type)', inventory_type)
        if not inventory then return nil end
        local header = assert(flow:get_field('gameHeaderSaveData'), 'load_header_unavailable')
        local checkpoint = {}
        for name, spec in pairs(header_fields) do checkpoint[name] = integer(header:get_field(spec[1]), 0, 0x7fffffff) end
        checkpoint.game_guid, checkpoint.save_guid = guid(header:get_field('GameGUID')), guid(header:get_field('SaveGUID'))
        if checkpoint.scenario ~= flow:call('get_CurrentScenarioType') or checkpoint.location ~= flow:call('get_LoadLocation') then return nil end
        local list = assert(inventory:call('get_Slots'), 'inventory_slots_unavailable')
        local count = integer(list:call('get_Count'), 0, 64)
        local capacity = integer(inventory:call('get_CurrentSlotSize'), 0, count)
        local items = {}
        for index = 0, count - 1 do
            local value = assert(list:call('get_Item(System.Int32)', index), 'inventory_slot_unavailable')
            items[#items + 1] = slot(value)
        end
        local result = {checkpoint = checkpoint, inventory = {capacity = capacity, slot_count = count, slots = items,
            survivor = integer(inventory:call('get_SurvivorType'), 0, 0x7fffffff),
            role = integer(inventory:call('get_RoleType'), 0, 0x7fffffff),
            equipped = {main = slot(inventory:call('get_MainSlot')), sub = slot(inventory:call('get_SubSlot')),
                personal = slot(inventory:call('get_PersonalSlot'))}}}
        if details then
            result.inventory.shortcuts = {main = shortcuts(inventory, '_MainShortcutSlots'),
                sub = shortcuts(inventory, '_SubShortcutSlots')}
        end
        local current = players:call('get_CurrentPlayer')
        if not current or current:get_address() ~= player:get_address() or list:call('get_Count') ~= count then return nil end
        local current_inventory = current:call('getComponent(System.Type)', inventory_type)
        if not current_inventory or current_inventory:get_address() ~= inventory:get_address() then return nil end
        return result, tostring(player:get_address()) .. ':' .. tostring(inventory:get_address())
    end
    return {capture = function()
        local ok, first, first_objects = pcall(read)
        if not ok then return nil, 'state_read_failed', tostring(first) end
        if first == nil then return nil, 'scene_unavailable' end
        local success, second, second_objects = pcall(read)
        if not success then return nil, 'state_read_failed', tostring(second) end
        if second == nil or first_objects ~= second_objects or not same(first, second) then return nil, 'state_changed' end
        return first, 'ok'
    end}
end

return M
