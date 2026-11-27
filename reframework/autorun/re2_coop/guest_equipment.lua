-- RE2 TDB 70 live inventory save DTO. Inventory.getData/loadData serialize a
-- single survivor's carried inventory. The manager's campaign save is separate.
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
        if spec==data then method(spec.name,'.ctor',void,survivor) else method(spec.name,'.ctor',void) end
    end
    for _,spec in ipairs({stocks,shortcuts}) do
        method(spec.name,'get_Count',i32)
        method(spec.name,'get_Item',spec.element.name,i32)
        method(spec.name,'Add',void,spec.element.name)
        method(spec.name,'Clear',void)
    end
    method(manager .. 'ItemData','setData',void,primitive.name,primitive.name,extra.name)
    method(sub.name,'set_Stock',void,stock.name)
    method(data.name,'set_MainData',void,main.name)
    method(data.name,'set_SubData',void,sub.name)
    method(data.name,'get_SurvivorType',survivor)
    method(inventory,'get_SurvivorType',survivor)
    method(inventory,'getData',data.name)
    method(inventory,'loadData',bool,data.name)
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
    local function construct(spec, values, actor)
        if spec.optional then
            if values==false then return nil end
            return construct(spec.optional,values,actor)
        end
        local obj=typed(sdk.create_instance(spec.name),spec.name)
        -- TDB70 may return a frame-local object. REFramework tracks this ref
        -- with the Lua userdata and releases it when that userdata is collected.
        obj:add_ref()
        local ops=methods[spec.name]
        if spec==data then ops['.ctor']:call(obj,actor) else ops['.ctor']:call(obj) end
        if spec==stock then
            methods[manager .. 'ItemData'].setData:call(obj, construct(primitive,values.DefaultItem),
                construct(optional(primitive),values.AdditionalItem),construct(optional(extra),values.ExData))
        end
        for _,field in ipairs(spec.fields) do
            local key,child=field[1],field[2]
            if child.low then obj:set_field(key,values[key])
            elseif child.element then
                local target=typed(obj:get_field(key),child.name)
                local list_ops=methods[child.name]
                list_ops.Clear:call(target)
                for _,entry in ipairs(values[key]) do list_ops.Add:call(target,construct(child.element,entry)) end
            elseif spec~=stock then
                ops['set' .. key]:call(obj,construct(child,values[key]))
            end
        end
        return obj
    end
    local function capture()
        local inv=current()
        local wire=read(inv)
        assert(inv:get_address()==current():get_address(),'inventory_changed')
        return wire
    end
    local function apply(wire)
        local requested=decode(wire)
        local inv=current()
        local before=read(inv)
        if before==wire then return true end
        local actor=methods[inventory].get_SurvivorType:call(inv)
        local target=construct(data,requested,actor)
        assert(serialize(target)==wire,'equipment_construction_mismatch')
        -- Rebuild both graphs separately. Native getData may share stock references with live slots.
        local rollback=construct(data,decode(before),actor)
        assert(serialize(rollback)==before and current():get_address()==inv:get_address(),'inventory_changed')
        local function load_and_check(native, expected)
            assert(current():get_address()==inv:get_address() and methods[inventory].get_SurvivorType:call(inv)==actor,
                'inventory_changed')
            return methods[inventory].loadData:call(inv,native)==true and current():get_address()==inv:get_address()
                and read(inv)==expected
        end
        local ok, applied=pcall(load_and_check,target,wire)
        if ok and applied then return true end
        local restored, verified=pcall(load_and_check,rollback,before)
        assert(restored and verified,'equipment_rollback_unverified')
        error('equipment_load_rejected_or_mismatch')
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
