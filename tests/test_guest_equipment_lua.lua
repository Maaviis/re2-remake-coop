local equipment = dofile('reframework/autorun/re2_coop/guest_equipment.lua')
-- Capacity, stocks, main equipped index/last weapon, sub last weapon/optional
-- stock, then the main and sub shortcut records (index, last weapon, key).
local empty = 'E1,8,0,-1,-1,-1,0,0,0'
assert(equipment.valid(empty))
for _, bad in ipairs({false, '', empty .. ',', empty .. ',1', empty:gsub('8','80'), empty:gsub(',0,', ',00,', 1),
        'E1,8,0,20,-1,-1,0,0,0', 'E1,8,0,-1,-1,-1,0,2,0,1,0,1,2,0,0'}) do
    assert(not equipment.valid(bad), tostring(bad))
end

local root='app.ropeway.'
local dto=root .. 'inventory.'
local manager=root .. 'gamemastering.InventoryManager.'
local data,inv=dto .. 'Data',root .. 'survivor.Inventory'
local stock,primitive,extra=manager .. 'StockItem',manager .. 'PrimitiveItem',manager .. 'ItemExData'
local main,sub,shortcut=dto .. 'MainSlotData',dto .. 'SubSlotData',dto .. 'ShortcutSlotData'
local item=root .. 'gamemastering.Item.ID'
local weapon,parts=root .. 'EquipmentDefine.WeaponType',root .. 'EquipmentDefine.WeaponParts'
local actor=root .. 'SurvivorDefine.SurvivorType'
local stock_list='System.Collections.Generic.List`1<' .. stock .. '>'
local shortcut_list='System.Collections.Generic.List`1<' .. shortcut .. '>'
local i32,bool,void='System.Int32','System.Boolean','System.Void'
local function named(name) return {get_full_name=function() return name end} end
local fields={
    [primitive]={ItemId=item,WeaponId=weapon,WeaponParts=parts,BulletId=item,Count=i32},
    [extra]={ExUintData='System.UInt32',ExItemID=item,RogueWeaponLevel=i32,IsInitialSet=bool,InitialCount=i32},
    [manager .. 'ItemData']={DefaultItem=primitive,AdditionalItem=primitive,ExData=extra},
    [stock]={Index=i32,IsWeaponEquip=bool},[main]={_Index=i32},[dto .. 'SlotData']={_LastWeaponType=weapon},
    [sub]={_Stock=stock},[shortcut]={_ShortcutKind=root .. 'EquipmentDefine.Shortcut'},
    [data]={_CurrentSlotSize=i32,_Stocks=stock_list,_MainData=main,_SubData=sub,
        _ShortcutDataList=shortcut_list,_SubShortcutDataList=shortcut_list}}
local f={actor=1,loads=0}
local function object(kind,values)
    local obj=values or {}
    obj.add_ref=function(self) self.retained=true; return self end
    obj.get_type_definition=function() return named(kind) end
    obj.get_field=function(self,key) return self[key] end
    obj.set_field=function(self,key,value) self[key]=value end
    return obj
end
local ops={}
local function method(owner,name,returns,params,fn)
    local signature=name .. '(' .. table.concat(params,', ') .. ')'
    ops[owner]=ops[owner] or {}
    ops[owner][signature]={get_return_type=function() return named(returns) end,is_static=function() return false end,
        get_param_types=function()
            local arr={}; for i,p in ipairs(params) do arr[i]=named(p) end; return arr
        end,call=function(_,obj,...) return fn(obj,...) end}
end
local function list(kind,entries) return object(kind,{entries=entries or {}}) end
for kind,element in pairs({[stock_list]=stock,[shortcut_list]=shortcut}) do
    method(kind,'get_Count',i32,{},function(obj) return #obj.entries end)
    method(kind,'get_Item',element,{i32},function(obj,idx) return obj.entries[idx+1] end)
    method(kind,'Clear',void,{},function(obj) obj.entries={} end)
    method(kind,'Add',void,{element},function(obj,entry) table.insert(obj.entries,entry) end)
end
for _,owner in ipairs({primitive,extra,stock,main,sub,shortcut}) do method(owner,'.ctor',void,{},function() end) end
method(manager .. 'ItemData','setData',void,{primitive,primitive,extra},function(obj,first,second,ex)
    obj.DefaultItem,obj.AdditionalItem,obj.ExData=first,second,ex
end)
method(data,'.ctor',void,{actor},function(obj,survivor)
    obj.survivor=survivor
    obj._Stocks,obj._ShortcutDataList,obj._SubShortcutDataList=list(stock_list),list(shortcut_list),list(shortcut_list)
end)
for _,name in ipairs({'MainData','SubData'}) do
    method(data,'set_' .. name,void,{name=='MainData' and main or sub},function(obj,value) obj['_' .. name]=value end)
end
method(sub,'set_Stock',void,{stock},function(obj,value) obj._Stock=value end)
method(data,'get_SurvivorType',actor,{},function(obj) return obj.survivor end)
method(inv,'get_SurvivorType',actor,{},function() return f.actor end)
method(inv,'getData',data,{},function() return f.live end)
method(inv,'loadData',bool,{data},function(_,snapshot)
    f.loads=f.loads+1
    assert(snapshot.survivor==f.actor)
    assert(snapshot.retained,'staged inventory must survive native allocations and callbacks')
    f.live=snapshot
    if f.drop_next then snapshot._CurrentSlotSize=20; f.drop_next=false end
    return true
end)
local function blank(survivor)
    return object(data,{survivor=survivor,_CurrentSlotSize=8,_Stocks=list(stock_list),
        _MainData=object(main,{_Index=-1,_LastWeaponType=-1}),_SubData=object(sub,{_LastWeaponType=-1}),
        _ShortcutDataList=list(shortcut_list),_SubShortcutDataList=list(shortcut_list)})
end
local function payload(id,wp,custom,bullet,num)
    return object(primitive,{ItemId=id,WeaponId=wp,WeaponParts=custom,BulletId=bullet,Count=num})
end
local rifle=object(stock,{Index=2,IsWeaponEquip=true,DefaultItem=payload(0,5,3,15,7),
    AdditionalItem=payload(9,-1,0,0,2),ExData=object(extra,{ExUintData=4294967295,ExItemID=13,
        RogueWeaponLevel=2,IsInitialSet=true,InitialCount=4})})
local knife=object(stock,{Index=-1,IsWeaponEquip=true,DefaultItem=payload(0,8,0,0,40)})
local function hotkey(key,idx,wp) return object(shortcut,{_ShortcutKind=key,_Index=idx,_LastWeaponType=wp}) end
f.live=blank(f.actor)
f.live._Stocks.entries={rifle}
f.live._MainData._Index,f.live._MainData._LastWeaponType=2,5
f.live._SubData._LastWeaponType,f.live._SubData._Stock=8,knife
f.live._ShortcutDataList.entries={hotkey(3,2,5),hotkey(0,-1,-1)}
f.live._SubShortcutDataList.entries={hotkey(1,-1,8)}
local native=object(inv,{get_address=function() return 111 end})
local player={call=function(_,method,component)
    assert(method=='getComponent(System.Type)' and component==inv); return native end}
sdk={get_tdb_version=function() return 70 end, typeof=function(name) return name end,
    game_namespace=function(n) return root .. n end,
    get_managed_singleton=function(name)
        assert(name==root .. 'PlayerManager'); return {call=function(_,m) assert(m=='get_CurrentPlayer'); return player end}
    end,
    find_type_definition=function(name)
        return {get_method=function(_,key) return (ops[name] or {})[key] end,
            get_field=function(_,key)
                local typ=(fields[name] or {})[key]
                if typ then return {is_static=function() return false end,get_type=function() return named(typ) end} end
            end}
    end,
    create_instance=function(kind) return object(kind) end}
reframework={get_game_name=function() return 're2' end}
local api=equipment.new()
local original='E1,8,1,2,1,0,5,3,15,7,1,9,-1,0,0,2,1,4294967295,13,2,1,4,2,5,8,1,-1,1,0,8,0,0,40,0,0,2,-1,-1,0,2,5,3,1,-1,8,1'
assert(api.capture()==original)
f.actor=0; f.live=blank(f.actor)
assert(api.apply(original)); assert(f.loads==1 and api.capture()==original and f.live.survivor==0)
assert(f.live._Stocks.entries[1].DefaultItem.Count==7 and f.live._SubData._Stock.DefaultItem.Count==40)
assert(api.apply(original) and f.loads==1,'duplicate reloaded native equipment')
assert(not api.apply(original .. ',100') and f.loads==1)
f.drop_next=true
local ok,why=api.apply(empty)
assert(not ok and why:find('equipment_load_rejected_or_mismatch',1,true) and f.loads==3 and api.capture()==original)
assert(api.apply(empty) and f.loads==4 and api.capture()==empty)
fields[stock].Index=bool
assert(not pcall(equipment.new),'incorrect native signature should disable writes')
-- Canonical order is required so a persisted payload can pass native readback.
assert(not equipment.valid('E1,8,0,-1,-1,-1,0,2,0,1,3,1,2,0,0'))
