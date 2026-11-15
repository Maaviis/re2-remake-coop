local root = 'app.ropeway.'
local flow_type = root .. 'gamemastering.MainFlowManager'
local inventory_type = root .. 'survivor.Inventory'
local slot_type = root .. 'inventory.Slot'
local list_type = 'System.Collections.Generic.List`1<' .. slot_type .. '>'
local header_type = flow_type .. '.GameHeaderSaveData'
local function named(name) return {get_full_name = function() return name end} end
local methods, fields = {}, {}
local function add(type_name, name, returns, params)
    methods[type_name] = methods[type_name] or {}
    methods[type_name][name] = {returns = returns, params = params or {}}
end
local function field(type_name, name, returns)
    fields[type_name] = fields[type_name] or {}; fields[type_name][name] = returns
end
for _, name in ipairs({'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene'}) do add(flow_type,name,'System.Boolean') end
add(flow_type,'get_CurrentScenarioType',flow_type .. '.ScenarioType')
add(flow_type,'get_LoadLocation',root .. 'gamemastering.Location.ID')
add(root .. 'gamemastering.SaveDataManager','get_IsBusy','System.Boolean')
for _, name in ipairs({'isTitleMenuOpened','isBusyMenuMain','isBusyMenuStory','isBusyLoad'}) do
    add(root .. 'gui.GUIMaster',name,'System.Boolean')
end
add(inventory_type,'get_CurrentSlotSize','System.Int32'); add(inventory_type,'get_Slots',list_type)
add(inventory_type,'get_SurvivorType',root .. 'SurvivorDefine.SurvivorType')
add(inventory_type,'get_RoleType',root .. 'SurvivorDefine.RoleType')
for _, role in ipairs({'Main','Sub','Personal'}) do add(inventory_type,'get_' .. role .. 'Slot',slot_type) end
add(list_type,'get_Count','System.Int32'); add(list_type,'get_Item(System.Int32)','System.Object',{'System.Int32'})
local slot_methods = {get_Index='System.Int32',get_Type=root .. 'inventory.SlotType',
    get_ItemID=root .. 'gamemastering.Item.ID', get_WeaponType=root .. 'EquipmentDefine.WeaponType',
    get_WeaponParts=root .. 'EquipmentDefine.WeaponParts',get_BulletID=root .. 'gamemastering.Item.ID',get_Number='System.Int32'}
for _, name in ipairs({'get_HasStock','get_IsBlank','get_IsForceBlank','get_IsFatSlot','get_IsDeadSlot','get_Infinity'}) do
    slot_methods[name] = 'System.Boolean'
end
for name, returns in pairs(slot_methods) do add(slot_type,name,returns) end
field(flow_type,'gameHeaderSaveData',header_type)
for name, returns in pairs({ScenarioTypeValue=flow_type .. '.ScenarioType',SurvivorTypeValue=root .. 'SurvivorDefine.SurvivorType',
    CurrentDifficulty=flow_type .. '.Difficulty',LocationId=root .. 'gamemastering.Location.ID',AreaId=root .. 'gamemastering.Map.ID',
    GameGUID='System.Guid',SaveGUID='System.Guid'}) do field(header_type,name,returns) end
field('System.Guid','mData1','System.UInt32'); field('System.Guid','mData2','System.UInt16'); field('System.Guid','mData3','System.UInt16')
for i=0,7 do field('System.Guid','mData4_' .. i,'System.Byte') end
local module = dofile('reframework/autorun/re2_coop/load_state.lua')

local function fixture(options)
    options = options or {}
    local f = {in_title=false,loading=false,finished=true,busy=false,player_calls=0,reads=0,count=2,capacity=1,number_calls=0}
    local function touch(name)
        f.reads = f.reads + 1
        assert(name:match('^get_') or name:match('^is') or name == 'getComponent(System.Type)', 'game mutation: ' .. name)
        if name == f.throw_method then error('getter unavailable') end
    end
    local guid = {get_field=function(_, name)
        if name == 'mData1' then return 0xffffffff end
        if name == 'mData2' or name == 'mData3' then return 0xffff end
        assert(name:match('^mData4_%d$')); return 255
    end}
    local header = {get_field=function(_, name)
        if name == f.nil_field then return nil end
        local values = {ScenarioTypeValue=1,SurvivorTypeValue=1,CurrentDifficulty=1,LocationId=16,AreaId=350,
            GameGUID=guid,SaveGUID=guid}
        assert(values[name] ~= nil); return values[name]
    end}
    local slots = {}
    for i=1,2 do
        slots[i] = {get_type_definition=function() return named(f.wrong_slot_type and 'foreign.Slot' or slot_type) end,
            call=function(_, name)
                touch(name)
                if name == f.nil_method then return nil end
                local values = {get_Index=i-1,get_Type=1,get_ItemID=-1,get_WeaponType=9,get_WeaponParts=0,
                    get_BulletID=2,get_Number=6,get_HasStock=true,get_IsBlank=false,get_IsForceBlank=false,
                    get_IsFatSlot=i==2,get_IsDeadSlot=false,get_Infinity=false}
                assert(values[name] ~= nil)
                if name == 'get_Number' then
                    f.number_calls = f.number_calls + 1
                    if f.change_number and f.number_calls > 3 then return 7 end
                end
                return values[name]
            end}
    end
    local list = {call=function(_, name, index)
        touch(name)
        if name == 'get_Count' then return f.count end
        assert(name == 'get_Item(System.Int32)'); return not f.missing_slot and slots[index+1] or nil
    end}
    local inventory = {get_address=function() return f.replace_inventory and f.player_calls>=3 and 78 or 77 end,
        call=function(_, name)
            touch(name)
            local values = {get_CurrentSlotSize=f.capacity,get_Slots=list,get_SurvivorType=1,get_RoleType=0,
                get_MainSlot=slots[1]}
            if name == 'get_SubSlot' or name == 'get_PersonalSlot' then return nil end
            assert(values[name] ~= nil); return values[name]
        end}
    local player = {get_address=function() return f.replace_player and f.player_calls>=3 and 102 or 101 end,
        call=function(_, name)
            touch(name); assert(name == 'getComponent(System.Type)'); return not f.no_inventory and inventory or nil
        end}
    local players = {call=function(_, name)
        touch(name); assert(name=='get_CurrentPlayer'); f.player_calls=f.player_calls+1
        return not f.no_player and player or nil
    end}
    local flow = {get_field=function(_, name) assert(name=='gameHeaderSaveData'); return header end,
        call=function(_, name)
            touch(name)
            local values = {get_IsInTitle=f.in_title,get_IsInLoadGameData=f.loading,get_IsFinishedLoadScene=f.finished,
                get_CurrentScenarioType=f.scenario or 1,get_LoadLocation=16}
            assert(values[name] ~= nil); return values[name]
        end}
    local save = {call=function(_, name) touch(name); assert(name=='get_IsBusy'); return f.busy end}
    local gui = {call=function(_, name) touch(name); return name==f.open_menu end}
    reframework = {get_game_name=function() return options.game or 're2' end}
    sdk = {get_tdb_version=function() return options.tdb or 70 end, game_namespace=function(name) return root .. name end,
        typeof=function(name) assert(name==inventory_type); return name end,
        find_type_definition=function(type_name)
            if type_name==options.missing_type then return nil end
            return {get_method=function(_, name)
                local spec = methods[type_name] and methods[type_name][name]
                assert(spec, 'unexpected metadata query ' .. type_name .. '.' .. name)
                if name == options.missing_method then return nil end
                return {is_static=function() return name==options.static_method end,
                    get_return_type=function() return named(name==options.bad_return and 'System.Void' or spec.returns) end,
                    get_param_types=function()
                        local p={}; for i, param in ipairs(spec.params) do p[i]=named(param) end; return p
                    end}
            end,get_field=function(_, name)
                if name==options.missing_field then return nil end
                local returns = fields[type_name] and fields[type_name][name]
                assert(returns, 'unexpected field metadata ' .. name)
                return {is_static=function() return false end,get_type=function() return named(returns) end}
            end}
        end,
        get_managed_singleton=function(name)
            if name==f.missing_singleton then return nil end
            local singletons={[flow_type]=flow,[root .. 'gamemastering.SaveDataManager']=save,
                [root .. 'gui.GUIMaster']=gui,[root .. 'PlayerManager']=players}
            return assert(singletons[name], 'unexpected singleton')
        end}
    f.reader = function() return module.new() end
    return f
end

local f=fixture(); local reader=f.reader(); local data, reason=reader.capture()
assert(data and reason=='ok' and data.inventory.slot_count==2 and data.inventory.capacity==1)
assert(data.inventory.slots[1].blank==false and data.inventory.slots[2].fat_slot==true)
assert(data.inventory.equipped.sub.present==false)
assert(data.checkpoint.save_guid=='ffffffff-ffff-ffff-ffff-ffffffffffff', 'GUID high bits lost precision')
for _, change in ipairs({'in_title','loading','busy','no_player','no_inventory'}) do
    f=fixture(); f[change]=true; reader=f.reader(); assert(reader.capture()==nil,change)
end
for _, menu in ipairs({'isTitleMenuOpened','isBusyMenuMain','isBusyMenuStory','isBusyLoad'}) do
    f=fixture(); f.open_menu=menu; assert(f.reader().capture()==nil,menu)
end
for _, change in ipairs({'replace_player','replace_inventory','change_number'}) do
    f=fixture(); f[change]=true; local state, error=f.reader().capture()
    assert(state==nil and error=='state_changed', change)
end
for _, change in ipairs({'missing_slot','wrong_slot_type'}) do
    f=fixture(); f[change]=true; local state, error=f.reader().capture()
    assert(state==nil and error=='state_read_failed',change)
end
f=fixture(); f.nil_method='get_Number'; assert(f.reader().capture()==nil)
f=fixture(); f.nil_field='GameGUID'; assert(f.reader().capture()==nil)
f=fixture(); f.count=65; assert(f.reader().capture()==nil)
f=fixture(); f.capacity=3; assert(f.reader().capture()==nil)
f=fixture(); f.scenario=2; assert(f.reader().capture()==nil)
f=fixture(); f.throw_method='isBusyLoad'; assert(f.reader().capture()==nil)
for _, options in ipairs({{tdb=71},{game='re3'},{missing_field='SaveGUID'},{static_method='get_Number'},
        {bad_return='get_HasStock'},{missing_type=inventory_type}}) do
    f=fixture(options); assert(not pcall(f.reader)); assert(f.reads==0, 'unsupported metadata reached game state')
end
f=fixture(); local output, update
package.loaded['re2_coop.load_state']=module
os.time=function() return 100 end
re={on_pre_application_entry=function(name, fn) assert(name=='UpdateBehavior'); update=fn end}
json={dump_file=function(path, value) assert(path=='re2_coop_load_state.json'); output=value end}
log={info=function() end}
dofile('reframework/diagnostics/re2_coop_load_state_observer.lua')
for _=1,6 do update() end
assert(output.available and output.sequence==1 and output.scope=='load_header_and_inventory_core')
f.no_player=true
for _=1,6 do update() end
assert(not output.available and output.state==nil and output.sequence==2, 'last good state survived source loss')
print('Load state: scoped inventory/header reads, false values, GUID bits, scene/object stability and unavailable reporting passed')
