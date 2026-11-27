-- RE2 TDB 70 carried inventory. Sample with getData and update existing live slots.
local M = {}
local root = 'app.ropeway.'
local inventory = root .. 'survivor.Inventory'
local manager = root .. 'gamemastering.InventoryManager.'
local dto = root .. 'inventory.'
local survivor = root .. 'SurvivorDefine.SurvivorType'
local i32, bool, void = 'System.Int32', 'System.Boolean', 'System.Void'
local function number(type_name, low, high) return {name=type_name, low=low, high=high} end
local index = number(i32, -1, 19)
local capacity = number(i32, 8, 20) -- inventory.Define.SLOT_MIN/SLOT_MAX
local weapon = number(root .. 'EquipmentDefine.WeaponType', -1, 381)
local item = number(root .. 'gamemastering.Item.ID', 0, 296) -- excludes the MAX sentinel
local parts = number(root .. 'EquipmentDefine.WeaponParts', 0, 7)
local count = number(i32, -0x80000000, 0x7fffffff)
local flag = number(bool, 0, 1)
local function record(name, fields) return {name=name, fields=fields} end
local function optional(element) return {optional=element, name=element.name} end
local function list(element, limit)
    return {element=element, limit=limit, name='System.Collections.Generic.List`1<' .. element.name .. '>'}
end
local primitive = record(manager .. 'PrimitiveItem', {
    {'ItemId',item}, {'WeaponId',weapon}, {'WeaponParts',parts}, {'BulletId',item}, {'Count',count}})
local extra = record(manager .. 'ItemExData', {
    {'ExUintData',number('System.UInt32',0,0xffffffff)}, {'ExItemID',item}, {'RogueWeaponLevel',count},
    {'IsInitialSet',flag}, {'InitialCount',count}})
local stock = record(manager .. 'StockItem', {
    {'Index',index}, {'IsWeaponEquip',flag}, {'DefaultItem',primitive}, {'AdditionalItem',optional(primitive)},
    {'ExData',optional(extra)}})
local main = record(dto .. 'MainSlotData', {{'_Index',index},{'_LastWeaponType',weapon}})
local sub = record(dto .. 'SubSlotData', {{'_LastWeaponType',weapon},{'_Stock',optional(stock)}})
local shortcut = record(dto .. 'ShortcutSlotData', {
    {'_Index',index},{'_LastWeaponType',weapon},{'_ShortcutKind',number(root .. 'EquipmentDefine.Shortcut',0,3)}})
local slot_type = dto .. 'Slot'
local direction = root .. 'EquipmentDefine.Shortcut'
local slot_dictionary = 'System.Collections.Generic.Dictionary`2<' .. direction .. ',' .. slot_type .. '>'
local stocks, shortcuts = list(stock,20), list(shortcut,4)
local data = record(dto .. 'Data', {{'_CurrentSlotSize',capacity}, {'_Stocks',stocks}, {'_MainData',main},
    {'_SubData',sub}, {'_ShortcutDataList',shortcuts}, {'_SubShortcutDataList',shortcuts}})

local function bounded(value, low, high)
    assert(math.type(value)=='integer' and value>=low and value<=high, 'inventory_value_out_of_range')
    return value
end

-- The count before each list and presence bit before each nullable object make
-- E1 reversible even when an extra item or an entire shortcut list is absent.
local function decode(wire)
    assert(type(wire)=='string' and #wire<=16384 and wire:sub(1,3)=='E1,', 'bad_equipment_version')
    local pos=4
    local function take(low, high)
        local comma=wire:find(',',pos,true) or (#wire+1)
        local token=wire:sub(pos,comma-1)
        local value=tonumber(token)
        assert(value and tostring(value)==token, 'bad_equipment_number')
        pos=comma+1
        return bounded(value,low,high)
    end
    local function read(spec)
        if spec.low then
            local value=take(spec.low,spec.high)
            if spec.name==bool then return value==1 end
            return value
        end
        if spec.optional then
            if take(0,1)==0 then return false end
            return read(spec.optional)
        end
        local result={}
        if spec.element then
            local used={}
            for i=1,take(0,spec.limit) do
                local entry=read(spec.element)
                local key=entry._ShortcutKind or entry.Index
                assert(key>=0 and not used[key], 'duplicate_or_invalid_inventory_entry')
                if spec==shortcuts and i>1 then
                    assert(key>result[i-1]._ShortcutKind, 'unsorted_inventory_shortcuts')
                end
                used[key],result[i]=true,entry
            end
        else
            for _,field in ipairs(spec.fields) do result[field[1]]=read(field[2]) end
        end
        return result
    end
    local result=read(data)
    assert(pos==#wire+2, 'bad_equipment_length')
    return result
end
function M.valid(wire)
    local ok=pcall(decode,wire)
    return ok
end

-- Both operands came from the same bounded DTO decoder.
local function same_record(left, right)
    if type(left) ~= 'table' or type(right) ~= 'table' then return left == right end
    if #left ~= #right then return false end
    for key,value in pairs(left) do
        if not same_record(value,right[key]) then return false end
    end
    return true
end

function M.new()
    assert(reframework:get_game_name()=='re2' and sdk.get_tdb_version()==70, 'unsupported_equipment_build')
    local methods={}
    local function method(owner, name, result, ...)
        local params={...}
        local signature=name .. '(' .. table.concat(params,', ') .. ')'
        local def=assert(sdk.find_type_definition(owner), 'missing_type:' .. owner)
        local m=assert(def:get_method(signature), 'missing_method:' .. owner .. '.' .. signature)
        assert(not m:is_static() and m:get_return_type():get_full_name()==result and #m:get_param_types()==#params,
            'unsupported_method:' .. signature)
        for i,actual in ipairs(m:get_param_types()) do
            assert(actual:get_full_name()==params[i], 'unsupported_parameter:' .. signature)
        end
        methods[owner]=methods[owner] or {}
        methods[owner][name]=m
    end
    for _,spec in ipairs({primitive,extra,stock,main,sub,shortcut,data}) do
        for _,field in ipairs(spec.fields) do
            -- Use the declaring type for inherited TDB fields.
            local owner=spec.name
            if field[1]=='_LastWeaponType' then owner=dto .. 'SlotData'
            elseif field[1]=='_Index' then owner=main.name
            elseif spec==stock and (field[2].fields or field[2].optional) then owner=manager .. 'ItemData' end
            local member=assert(sdk.find_type_definition(owner):get_field(field[1]), 'missing_field:' .. field[1])
            assert(not member:is_static() and member:get_type():get_full_name()==field[2].name,
                'unsupported_inventory_field:' .. field[1])
        end
        if spec==stock or spec==primitive or spec==extra then method(spec.name,'.ctor',void) end
    end
    for _,spec in ipairs({stocks,shortcuts}) do
        method(spec.name,'get_Count',i32)
        method(spec.name,'get_Item',spec.element.name,i32)
    end
    method(manager .. 'ItemData','setData',void,primitive.name,primitive.name,extra.name)
    method(data.name,'get_SurvivorType',survivor)
    method(inventory,'get_SurvivorType',survivor)
    method(inventory,'getData',data.name)
    method(inventory,'get_MainSlot',slot_type)
    method(inventory,'get_SubSlot',slot_type)
    method(slot_type,'set',bool,stock.name)
    method(slot_type,'set_LastWeaponType',void,weapon.name)
    method(slot_dictionary,'get_Item',slot_type,direction)
    method(inventory,'getSlot',slot_type,i32)
    method(slot_type,'get_Number',i32)
    method(slot_type,'set_Number',void,i32)
    method(slot_type,'get_MaxNumber',i32)
    local component=assert(sdk.typeof(inventory))

    local function typed(object, name)
        assert(object and object:get_type_definition():get_full_name()==name, 'unexpected_object:' .. name)
        return object
    end
    local function current()
        local players=sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
        local player=players and players:call('get_CurrentPlayer')
        return typed(player and player:call('getComponent(System.Type)',component),inventory)
    end
    local function serialize(snapshot)
        local tokens={'E1'}
        local function write(spec, value)
            if spec.low then
                if spec.name==bool then
                    assert(type(value)=='boolean','bad_native_bool')
                    value=value and 1 or 0
                end
                tokens[#tokens+1]=tostring(bounded(value,spec.low,spec.high))
            elseif spec.optional then
                tokens[#tokens+1]=value and '1' or '0'
                if value then write(spec.optional,value) end
            else
                typed(value,spec.name)
                if spec.element then
                    local ops=methods[spec.name]
                    local size=bounded(ops.get_Count:call(value),0,spec.limit)
                    tokens[#tokens+1]=tostring(size)
                    local entries={}
                    for i=1,size do entries[i]=typed(ops.get_Item:call(value,i-1),spec.element.name) end
                    -- Native dictionaries can enumerate in a different order after loadData.
                    if spec==shortcuts then
                        table.sort(entries,function(a,b) return a:get_field('_ShortcutKind')<b:get_field('_ShortcutKind') end)
                    end
                    for _,entry in ipairs(entries) do write(spec.element,entry) end
                else
                    for _,field in ipairs(spec.fields) do write(field[2],value:get_field(field[1])) end
                end
            end
        end
        write(data,snapshot)
        local wire=table.concat(tokens,',')
        assert(M.valid(wire),'invalid_native_equipment')
        return wire
    end
    local function read(inv)
        local value=typed(methods[inventory].getData:call(inv),data.name)
        value:add_ref()
        assert(methods[data.name].get_SurvivorType:call(value)==methods[inventory].get_SurvivorType:call(inv),
            'inventory_survivor_changed')
        return serialize(value)
    end
    local function construct(spec, values)
        if spec.optional then
            if values==false then return nil end
            return construct(spec.optional,values)
        end
        local obj=typed(sdk.create_instance(spec.name),spec.name)
        -- TDB70 may return a frame-local object. REFramework tracks this ref
        -- with the Lua userdata and releases it when that userdata is collected.
        obj:add_ref()
        methods[spec.name]['.ctor']:call(obj)
        if spec==stock then
            methods[manager .. 'ItemData'].setData:call(obj,construct(primitive,values.DefaultItem),
                construct(optional(primitive),values.AdditionalItem),construct(optional(extra),values.ExData))
        end
        for _,field in ipairs(spec.fields) do
            if field[2].low then obj:set_field(field[1],values[field[1]]) end
        end
        return obj
    end
    local function capture()
        local inv=current()
        local wire=read(inv)
        assert(inv:get_address()==current():get_address(),'inventory_changed')
        return wire
    end
    -- Preflight every slot before writing. A save DTO can be deserialized during
    -- engine loading, but calling Inventory.loadData again on a live survivor
    -- can invalidate weapon objects still owned by the standby controller.
    local function apply(wire)
        local requested=decode(wire)
        local inv=current()
        local before=read(inv)
        if before==wire then return true end
        local previous=decode(before)
        local layout='equipment_layout_requires_campaign_load'
        assert(previous._CurrentSlotSize==requested._CurrentSlotSize
            and #previous._Stocks==#requested._Stocks and previous._MainData._Index==requested._MainData._Index
            and same_record(previous._SubData._Stock,requested._SubData._Stock),layout)
        local ops=methods[slot_type]
        local edits={}
        local function edit(slot, setter, old, new, expects_result)
            edits[#edits+1]={slot=typed(slot,slot_type),setter=setter,old=old,new=new,expects_result=expects_result}
        end
        for i,old in ipairs(previous._Stocks) do
            local new=requested._Stocks[i]
            assert(old.Index==new.Index,layout)
            if not same_record(old,new) then
                local slot=typed(methods[inventory].getSlot:call(inv,old.Index),slot_type)
                local count=old.DefaultItem.Count
                old.DefaultItem.Count=new.DefaultItem.Count
                local count_only=same_record(old,new)
                old.DefaultItem.Count=count
                if count_only then
                    assert(ops.get_Number:call(slot)==count,'inventory_slot_changed')
                    bounded(new.DefaultItem.Count,0,ops.get_MaxNumber:call(slot))
                    edit(slot,ops.set_Number,count,new.DefaultItem.Count)
                else
                    edit(slot,ops.set,construct(stock,old),construct(stock,new),true)
                end
            end
        end
        for _,role in ipairs({'Main','Sub'}) do
            local key='_' .. role .. 'Data'
            local old,new=previous[key]._LastWeaponType,requested[key]._LastWeaponType
            if old~=new then edit(methods[inventory]['get_' .. role .. 'Slot']:call(inv),ops.set_LastWeaponType,old,new) end
            local group=role=='Main' and '_ShortcutDataList' or '_SubShortcutDataList'
            assert(#previous[group]==#requested[group],layout)
            for i,entry in ipairs(previous[group]) do
                local target=requested[group][i]
                assert(entry._ShortcutKind==target._ShortcutKind and entry._Index==target._Index,layout)
                if entry._LastWeaponType~=target._LastWeaponType then
                    local dictionary=typed(inv:get_field('_' .. role .. 'ShortcutSlots'),slot_dictionary)
                    local slot=methods[slot_dictionary].get_Item:call(dictionary,entry._ShortcutKind)
                    edit(slot,ops.set_LastWeaponType,entry._LastWeaponType,target._LastWeaponType)
                end
            end
        end
        local function set(e,value)
            local result=e.setter:call(e.slot,value)
            assert(not e.expects_result or result==true,'equipment_slot_rejected')
        end
        local attempted=0
        assert(capture()==before and current():get_address()==inv:get_address(),'inventory_changed')
        local ok,why=pcall(function()
            for i,e in ipairs(edits) do
                attempted=i
                set(e,e.new)
            end
            assert(current():get_address()==inv:get_address() and read(inv)==wire,'equipment_slot_mismatch')
        end)
        if not ok then
            assert(current():get_address()==inv:get_address(),'inventory_changed')
            for i=attempted,1,-1 do set(edits[i],edits[i].old) end
            assert(capture()==before,'equipment_rollback_unverified')
            error(why)
        end
        return true
    end
    return {capture=function()
        local ok,result=pcall(capture)
        if ok then return result end
        return nil,tostring(result)
    end, apply=function(wire)
        local ok,result=pcall(apply,wire)
        if ok then return result end
        return false,tostring(result)
    end}
end
return M
