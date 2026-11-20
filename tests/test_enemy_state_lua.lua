local root = 'app.ropeway.'
local manager, record = root .. 'EnemyManager', root .. 'EnemyManager.RegisterEnemyInfo'
local context, stored = root .. 'enemy.EmCommonContext', root .. 'enemy.savedata.EmSaveData'
local controller, hp = root .. 'EnemyController', root .. 'EnemyHitPointController'
local think = root .. 'enemy.EnemyThinkBehavior'
local flow, save = root .. 'gamemastering.MainFlowManager', root .. 'gamemastering.SaveDataManager'
local header = flow .. '.GameHeaderSaveData'
local list, active_list = 'System.Collections.Generic.List`1<' .. record .. '>',
    'System.Collections.Generic.List`1<' .. controller .. '>'
local storage_type='System.Collections.Generic.Dictionary`2<System.Guid,' .. stored .. '>'
local assembly=', mscorlib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null'
local entry_type='System.Collections.Generic.Dictionary`2.Entry<System.Guid,' .. stored .. '>'
local entries_array_type='System.Collections.Generic.Dictionary`2.Entry[[System.Guid' .. assembly .. '],[' .. stored .. assembly .. ']][]'
local methods, fields = {}, {}
local function add(t, values) methods[t] = values end
local function field(t, values) fields[t] = values end
-- Signatures and inheritance observed on RE2 TDB 70. Generic item returns are erased.
add(manager, {get_EnemyList=list,get_ActiveEnemyList=active_list,get_IsPausing='System.Boolean',
    get_LastPlayerStaySceneID=root .. 'gamemastering.Map.ID',get_LastPlayerStaySceneArea=root .. 'gamemastering.Map.Area'})
add(storage_type,{get_Count='System.Int32'})
for _, t in ipairs({list,active_list}) do add(t,{get_Count='System.Int32',['get_Item(System.Int32)']='System.Object'}) end
add(record,{get_GUID='System.Guid',get_KindID=root .. 'EnemyDefine.KindID',get_Context=context,
    get_ContextData=stored,get_Controller=controller})
add(context,{get_InheritID='System.Int32',get_IsEliminated='System.Boolean',get_Status=context .. '.InstanceStatus',
    get_ContextPosition='via.vec3',get_ContextRotation='via.Quaternion'})
add(stored,{get_DefaultHitPoint='System.Int32',get_CurrentHitPoint='System.Int32',get_Eliminated='System.Boolean',
    get_CurrentWincePoint='System.Int32',get_Position='via.vec3',get_Rotation='via.Quaternion'})
add(controller,{get_InheritID='System.Int32',get_KindID=root .. 'EnemyDefine.KindID',get_IsActiveEnemy='System.Boolean',
    get_IsLive='System.Boolean',get_Setupped='System.Boolean',get_Loading='System.Boolean',get_IsStandby='System.Boolean',
    get_ConditionBits='System.UInt32',get_ConditionBits2='System.UInt32',get_ThinkEnable='System.Boolean',
    get_LastStaySceneMapID=root .. 'gamemastering.Map.ID',get_LastStaySceneAreaID=root .. 'gamemastering.Map.Area'})
add(think,{get_IsLive='System.Boolean'})
add(root .. 'HitPointController',{get_DefaultHitPoint='System.Int32',get_CurrentHitPoint='System.Int32',get_IsDead='System.Boolean'})
add(flow,{get_IsInTitle='System.Boolean',get_IsInLoadGameData='System.Boolean',get_IsFinishedLoadScene='System.Boolean',
    get_CurrentScenarioType=flow .. '.ScenarioType',get_LoadLocation=root .. 'gamemastering.Location.ID'})
add(save,{get_IsBusy='System.Boolean'})
add('via.SceneManager',{get_CurrentScene='via.Scene'})
field(manager,{TotalEnemyKillCount='System.UInt32',StoreDataStorage=storage_type})
field(storage_type,{_entries=entries_array_type,_count='System.Int32',_freeCount='System.Int32'})
field(entry_type,{hashCode='System.Int32',key='System.Guid',value=stored})
field(context,{GUID='System.Guid'})
field(stored,{GUID='System.Guid',InheritID='System.Int32',KindID=root .. 'EnemyDefine.KindID',
    SceneID=root .. 'gamemastering.Map.ID',AreaID=root .. 'gamemastering.Map.Area',FlagData='System.UInt32',
    HitPointData='System.Int32[]',TransformData='System.Single[]'})
field(controller,{['<ContextGUID>k__BackingField']='System.Guid',['<HitPoint>k__BackingField']=hp,
    ['<Think>k__BackingField']=think})
field(flow,{gameHeaderSaveData=header});field(header,{GameGUID='System.Guid',SaveGUID='System.Guid'})
field('System.Guid',{mData1='System.UInt32',mData2='System.UInt16',mData3='System.UInt16'})
for i=0,7 do fields['System.Guid']['mData4_' .. i]='System.Byte' end
local parent = {['test.Context']=context,['test.Controller']=controller,['test.Think']=think,[hp]=root .. 'HitPointController'}
local f
local function named(name)
    return {get_full_name=function() return name end,
        get_parent_type=function() return parent[name] and named(parent[name]) end,
        get_method=function(_,name_)
            local returns=methods[name] and methods[name][name_]
            if not returns or name_==f.missing_method then return nil end
            return {is_static=function() return name=='via.SceneManager' or name==manager and name_:match('^get_LastPlayer')~=nil end,
                get_return_type=function() return named(name_==f.bad_method and 'System.Void' or returns) end,
                call=function(_,receiver)
                    assert(name==manager and receiver==nil)
                    f.calls[#f.calls+1]=name_
                    if name_=='get_LastPlayerStaySceneID' then return f.change_player_map and f.reads>1 and 351 or 350 end
                    assert(name_=='get_LastPlayerStaySceneArea');return 9
                end,
                get_param_types=function() return name_:find('System.Int32',1,true) and {named('System.Int32')} or {} end}
        end,
        get_field=function(_,name_)
            local returns=fields[name] and fields[name][name_]
            if not returns or name_==f.missing_field then return nil end
            return {is_static=function() return false end,
                get_type=function() return named(name_==f.bad_field and 'System.String' or returns) end}
        end}
end
local function fixture(options)
    f=options or {}; f.reads,f.calls,f.scene_calls=0,{},0
    local next_address=100
    local function object(t,values,functions,label)
        next_address=next_address+1;local address=next_address
        return {get_type_definition=function() return named(label=='context' and f.foreign_context and 'foreign.Context'
                or label=='think' and f.foreign_think and 'foreign.Think' or t) end,
            get_address=function() return address+((f.swap_object==label and f.reads>1) and 1000 or 0) end,
            get_field=function(_,key)
                assert(not key:match('^set_'),'game state write')
                if key==f.nil_field then return nil end
                local value=values and values[key]
                if type(value)=='function' then return value() end
                return value
            end,
            call=function(_,key,...)
                f.calls[#f.calls+1]=key
                local fn=functions and functions[key]
                assert(fn,'unexpected native call '..key)
                return fn(...)
            end}
    end
    local function guid(n)
        local values={mData1=function() return f.duplicate and n==2 and 1 or n end,mData2=0xffff,mData3=0xabcd}
        for i=0,7 do values['mData4_'..i]=i+240 end
        return object('System.Guid',values)
    end
    local function array(t,values,size,label)
        local result=object(t,nil,nil,label)
        result.get_size=function() return size end
        result.get_element=function(_,index) return values[index+1] end
        return result
    end
    local ids={guid(1),guid(2)}
    local pos={x=1.5,y=2,z=-4};local rot={x=0,y=0,z=0,w=1}
    if f.nan then pos.x=0/0 end
    if f.zero_rotation then rot.w=0 end
    local health=object(hp,nil,{get_DefaultHitPoint=function() return 100 end,
        get_CurrentHitPoint=function() return f.change_hp and f.reads>1 and 8 or 7 end,
        get_IsDead=function() return f.dead==true end},'hp')
    local thinking=object('test.Think',nil,{get_IsLive=function() return not f.think_dead end},'think')
    local live=object('test.Controller',{['<ContextGUID>k__BackingField']=function() return f.wrong_live_id and ids[2] or ids[1] end,
        ['<Think>k__BackingField']=function() return not f.no_think and thinking or nil end,
        ['<HitPoint>k__BackingField']=function() return not f.no_hp and health or nil end},
        {get_InheritID=function() return 3 end,get_KindID=function() return 4 end,
        get_IsActiveEnemy=function() return true end,get_IsLive=function() return false end,
        get_Setupped=function() return true end,get_Loading=function() return false end,
        get_IsStandby=function() return false end,get_ConditionBits=function() return 0xffffffff end,
        get_ConditionBits2=function() return 0 end,
        get_ThinkEnable=function() return f.invalid_activity and 0 or f.change_think and f.reads>1 or f.think_enabled==true end,
        get_LastStaySceneMapID=function() return 112 end,get_LastStaySceneAreaID=function() return 7 end},'live')
    local hp_array=array('System.Int32[]',{},f.bad_saved_arrays and 2 or 3,'hp_array')
    local transform_array=array('System.Single[]',{},10,'transform_array')
    local data=object(stored,{GUID=ids[1],InheritID=3,KindID=4,SceneID=350,AreaID=9,FlagData=0xffffffff,
        HitPointData=hp_array,TransformData=transform_array},
        {get_DefaultHitPoint=function() return 101 end,get_CurrentHitPoint=function() return 17 end,
        get_CurrentWincePoint=function() return 2 end,
        get_Eliminated=function() return false end,get_Position=function() return pos end,
        get_Rotation=function() return rot end},'stored')
    local third_id=guid(3)
    local unregistered=object(stored,{GUID=third_id,InheritID=-1,KindID=6,SceneID=347,AreaID=0,FlagData=0xffffffff,
        HitPointData=hp_array,TransformData=transform_array},
        {get_DefaultHitPoint=function() return 50 end,get_CurrentHitPoint=function() return 0 end,
        get_CurrentWincePoint=function() return 1 end,get_Eliminated=function() return false end,
        get_Position=function() return pos end,get_Rotation=function() return rot end},'unregistered')
    local dictionary_entries={object(entry_type,{hashCode=12,key=ids[1],value=data}),
        object(entry_type,{hashCode=-1}),
        object(entry_type,{hashCode=14,key=f.duplicate_storage and ids[1] or (f.wrong_storage_key and ids[2] or third_id),
            value=f.duplicate_storage and data or unregistered})}
    local storage_array=array(entries_array_type,dictionary_entries,3,'storage_array')
    local dictionary=object(storage_type,{_count=f.empty_storage and 0 or 3,_freeCount=f.empty_storage and 0 or 1,
        _entries=function() return not f.no_storage_array and storage_array or nil end},
        {get_Count=function() return f.empty_storage and 0 or (f.storage_count_mismatch and 3 or 2) end},'storage')
    local records={}
    for i=1,2 do
        local ctx=object('test.Context',{GUID=function() return f.wrong_context_id and i==1 and ids[2] or ids[i] end},
            {get_InheritID=function() return 3 end,get_IsEliminated=function() return false end,
            get_Status=function() return 2 end,get_ContextPosition=function() return pos end,
            get_ContextRotation=function() return rot end},'context')
        records[i]=object(record,nil,{get_GUID=function() return ids[i] end,get_KindID=function() return 4 end,
            get_Context=function() return not f.no_context and ctx or nil end,
            get_ContextData=function() return i==1 and data or nil end,
            get_Controller=function() return i==1 and not f.no_live and live or nil end},'record')
    end
    local registry=object(list,nil,{get_Count=function() return f.count or (f.empty and 0 or 2) end,
        ['get_Item(System.Int32)']=function(i) return records[f.reverse and 2-i or i+1] end},'registry')
    local active_alias=object('test.Controller',{['<ContextGUID>k__BackingField']=ids[1]})
    local active=object(active_list,nil,{get_Count=function() return (f.empty or f.no_live) and 0 or (f.active_duplicate and 2 or 1) end,
        ['get_Item(System.Int32)']=function() return f.active_alias and active_alias or live end},'active')
    local enemies=object(manager,{TotalEnemyKillCount=0xffffffff,StoreDataStorage=dictionary},{
        get_EnemyList=function() f.reads=f.reads+1;return registry end,
        get_ActiveEnemyList=function() return active end,get_IsPausing=function() return false end},'manager')
    local h=object(header,{GameGUID=guid(0xffffffff),SaveGUID=guid(3)})
    local main=object(flow,{gameHeaderSaveData=h},{get_IsInTitle=function() return f.title==true end,
        get_IsInLoadGameData=function() return f.loading==true or f.change_loading and f.reads>0 or false end,
        get_IsFinishedLoadScene=function() return not f.unfinished end,
        get_CurrentScenarioType=function() return 1 end,get_LoadLocation=function() return 16 end})
    local saves=object(save,nil,{get_IsBusy=function() return f.busy==true end})
    local player=object('via.GameObject',nil,nil,'player')
    local scene=object('via.Scene',nil,nil,'scene')
    local players=object('test.PlayerManager',nil,{get_CurrentPlayer=function() return not f.no_player and player or nil end})
    reframework={get_game_name=function() return f.wrong_game and 're3' or 're2' end}
    sdk={get_tdb_version=function() return f.wrong_tdb and 71 or 70 end,find_type_definition=named,
        game_namespace=function(n) return 'app.ropeway.'..n end,
        get_managed_singleton=function(n)
            return ({[flow]=main,[save]=saves,[manager]=not f.no_manager and enemies or nil,
                [root..'PlayerManager']=players})[n]
        end,
        get_native_singleton=function() return {} end,
        call_native_func=function(_,_,name)
            assert(name=='get_CurrentScene');f.scene_calls=f.scene_calls+1
            if f.scene_change and f.scene_calls>1 then return object('via.Scene') end
            return scene
        end}
    return dofile('reframework/autorun/re2_coop/enemy_state.lua').new
end
local function capture(options)
    return fixture(options)().capture()
end
local state=assert(capture())
assert(state.registered_count==2 and state.active_count==1 and state.total_kills==0xffffffff)
local first,second=table.unpack(state.entries)
assert(first.id:match('^00000001%-ffff%-abcd%-f0f1%-f2f3f4f5f6f7$'))
assert(state.checkpoint.game_guid:match('^ffffffff%-'))
assert(first.live.hp==7 and first.stored.hp==17 and first.live.default_hp==100 and first.stored.default_hp==101)
assert(first.live.is_live==false and first.live.is_dead==false and first.live.conditions==0xffffffff)
assert(second.context.present and second.live.present==false and second.stored.present==false)
assert(second.live.hp==nil and second.live.is_dead==nil,'unloaded context is not dead')
assert(state.stored_count==2 and #state.stored_entries==2,'free dictionary slots must not become enemies')
assert(state.stored_entries[2].id:match('^00000003%-'),'stored enemy outside the registry must be retained')
assert(state.stored_entries[2].hp==0 and state.stored_entries[2].eliminated==false
    and state.stored_entries[2].inherit_id==-1,'zero stored HP does not invent elimination')
assert(state.stored_entries[1].wince_hp==2 and state.stored_entries[2].flags==0xffffffff)
assert(capture({empty_storage=true,no_storage_array=true}).stored_count==0,'unallocated empty dictionary is valid')
assert(capture({dead=true}).entries[1].live.is_dead,'preserve raw death flag independently of HP')
assert(capture({reverse=true}).entries[1].id==first.id,'canonical order must not depend on registry order')
assert(capture({empty=true}).registered_count==0,'a valid empty registry remains distinct from failed capture')
for _, options in ipairs({{title=true},{loading=true},{unfinished=true},{busy=true},{no_player=true},{no_manager=true}}) do
    local value,reason=capture(options); assert(value==nil and reason=='scene_unavailable')
end
for _, options in ipairs({{duplicate=true},{wrong_context_id=true},{wrong_live_id=true},{no_hp=true},
        {no_context=true},{foreign_context=true},{nan=true},{zero_rotation=true},{count=513},{nil_field='TotalEnemyKillCount'},
        {active_alias=true},{active_duplicate=true},{bad_saved_arrays=true},{duplicate_storage=true},
        {wrong_storage_key=true},{no_storage_array=true},{storage_count_mismatch=true}}) do
    local value,reason=capture(options); assert(value==nil and reason=='enemy_read_failed')
end
for _, options in ipairs({{change_hp=true},{scene_change=true},{swap_object='record'},{swap_object='player'},
        {swap_object='manager'},{change_loading=true},{swap_object='storage'},
        {swap_object='storage_array'},{swap_object='hp_array'}}) do
    local value,reason=capture(options);assert(value==nil and reason=='enemy_state_changed')
end
for _, options in ipairs({{wrong_game=true},{wrong_tdb=true},{bad_method='get_GUID'},
        {missing_method='get_IsDead'},{bad_field='TotalEnemyKillCount'},{missing_field='GUID'}}) do
    assert(not pcall(fixture(options)),'unsupported interfaces must prevent reader creation')
end

-- Opt-in AI flags preserve the established default report and never infer execution.
local new_reader=fixture({missing_method='get_ThinkEnable'})
assert(new_reader().capture().activity==nil,'default reader unexpectedly needs optional AI interfaces')
assert(not pcall(new_reader,{include_activity=true}),'optional missing metadata must fail closed')
state=assert(capture())
assert(state.activity==nil and state.entries[1].live.activity==nil)
for _,name in ipairs(f.calls) do assert(not name:find('Think') and not name:find('StayScene')) end
local activity=assert(fixture()({include_activity=true}).capture())
assert(activity.activity.scope=='native_enemy_ai_flags' and activity.activity.player_map==350 and activity.activity.player_area==9)
local a=activity.entries[1].live.activity
assert(activity.entries[1].live.active and not a.think_enabled and a.think.present and a.think.is_live)
assert(a.last_map==112 and a.last_area==7 and a.think.type=='test.Think')
assert(a.simulated==nil and a.executed==nil,'raw flags must not invent an AI execution result')
assert(activity.entries[2].live.activity==nil,'missing controller must remain explicit')
assert(fixture({no_think=true})({include_activity=true}).capture().entries[1].live.activity.think.present==false)
assert(fixture({think_enabled=true,think_dead=true})({include_activity=true}).capture().entries[1].live.activity.think.is_live==false)
for _,options in ipairs({{change_think=true},{change_player_map=true},{swap_object='think'}}) do
    local value,reason=fixture(options)({include_activity=true}).capture()
    assert(not value and reason=='enemy_state_changed')
end
for _,options in ipairs({{invalid_activity=true},{foreign_think=true}}) do
    local value,reason=fixture(options)({include_activity=true}).capture()
    assert(not value and reason=='enemy_read_failed')
end
for _,options in ipairs({{bad_method='get_ThinkEnable'},{bad_method='get_LastPlayerStaySceneID'},
    {missing_field='<Think>k__BackingField'}}) do
    assert(not pcall(fixture(options),{include_activity=true}))
end
for _,options in ipairs({true,{include_activity=1},{unknown=true}}) do assert(not pcall(fixture(),options)) end
print('ok - opt-in AI flags distinguish membership, presence and readiness; unstable identities/flags fail closed')

-- Observer must publish source loss without retaining the prior enemy list.
local callback,reset,reports,now=nil,nil,{},100
local real_time=os.time
os.time=function() return now end
local captures=0
package.loaded['re2_coop.enemy_state']={new=function() return {capture=function()
    captures=captures+1;if captures==1 then return state,'ok' end;return nil,'scene_unavailable'
end} end}
re={on_pre_application_entry=function(name,fn) assert(name=='UpdateBehavior');callback=fn end,
    on_script_reset=function(fn) reset=fn end}
json={dump_file=function(name,value) assert(name=='re2_coop_enemy_state.json');reports[#reports+1]=value end}
log={info=function() end}
dofile('reframework/diagnostics/re2_coop_enemy_state_observer.lua')
for _=1,6 do callback() end
now=101;for _=1,6 do callback() end
assert(#reports==2 and reports[1].available and not reports[2].available)
assert(reports[1].scope=='registered_and_stored_enemy_contexts' and reports[2].state==nil)
assert(reports[2].sequence==2 and reports[2].run_id==reports[1].run_id)
reset()
assert(reports[3].sequence==3 and reports[3].available==false and reports[3].state==nil
    and reports[3].reason=='script_reset','VM reset must invalidate the old enemy report')
os.time=real_time

local previous_require=require
local activity_calls=0
require=function(name)
    assert(name=='re2_coop.enemy_state')
    return {new=function(options)
        assert(options.include_activity==true)
        return {capture=function() activity_calls=activity_calls+1
            if activity_calls==1 then return activity,'ok' end
            return nil,'enemy_state_changed'
        end}
    end}
end
reports={}
re.on_application_entry=function(name,fn) assert(name=='UpdateBehavior');callback=fn end
json.dump_file=function(name,value) assert(name=='re2_coop_enemy_activity.json');reports[#reports+1]=value end
dofile('reframework/diagnostics/re2_coop_enemy_activity.lua')
for _=1,12 do callback() end
assert(#reports==2 and reports[1].available and reports[1].scope=='native_enemy_ai_flags')
assert(not reports[2].available and reports[2].reason=='enemy_state_changed' and reports[2].state==nil)
reset();local count=#reports;for _=1,12 do callback() end
assert(#reports==count and reports[count].reason=='script_reset' and reports[count].state==nil)
require=previous_require
print('Enemy reader: registered/stored identity, free slots, array gates, absent/live HP, changes and source loss passed')
