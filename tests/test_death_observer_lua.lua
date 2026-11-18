local owner='app.ropeway.enemy.em0000.Em0000ThinkBase'
local concrete='app.ropeway.enemy.em0000.Em0000Think'
local think='app.ropeway.enemy.EnemyThinkBehavior'
local controller='app.ropeway.EnemyController'
local base='app.ropeway.HitPointController'
local flow='app.ropeway.gamemastering.MainFlowManager'
local save='app.ropeway.gamemastering.SaveDataManager'
local field_types={
    [think]={['<Controller>k__BackingField']=controller},
    [controller]={['<ContextGUID>k__BackingField']='System.Guid',['<HitPoint>k__BackingField']='app.ropeway.EnemyHitPointController'},
    [base]={['<CurrentHitPoint>k__BackingField']='System.Int32'},
    ['System.Guid']={mData1='System.UInt32',mData2='System.UInt16',mData3='System.UInt16'}}
for i=0,7 do field_types['System.Guid']['mData4_' .. i]='System.Byte' end
local function kind(name) return {get_full_name=function() return name end} end
local hooks,stack,metadata,reads={}, {}, {}, 0
reframework={get_game_name=function() return metadata.game or 're2' end}
thread={get_hook_storage=function() return assert(stack[#stack]) end}
sdk={PreHookResult={CALL_ORIGINAL=123},get_tdb_version=function() return metadata.tdb or 70 end,
    to_int64=function(value) return value end,
    to_managed_object=function(value) return value end,
    find_type_definition=function(type_name)
        return {get_method=function(_,name)
            if type_name==flow or type_name==save then
                return {is_static=function() return false end,get_return_type=function() return kind('System.Boolean') end,
                    get_param_types=function() return {} end}
            end
            assert((type_name==owner or type_name==concrete) and name=='onDead')
            if metadata.no_method then return nil end
            return {is_static=function() return metadata.static==true end,
                get_return_type=function() return kind(metadata.returns or 'System.Void') end,
                get_function=function() return metadata.zero_address and 0 or (type_name==concrete and metadata.different_dispatch and 2 or 1) end,
                get_declaring_type=function() return kind(metadata.wrong_declaring and 'wrong.Type' or owner) end,
                get_param_types=function() return metadata.params and {kind('System.Int32')} or {} end}
        end,get_field=function(_,name)
            local actual=assert(field_types[type_name][name],type_name .. '.' .. name)
            if metadata.no_field==name then return nil end
            return {is_static=function() return false end,get_type=function() return kind(actual) end}
        end}
    end,hook=function(_,pre,post) hooks[#hooks+1]={pre=pre,post=post} end,
    get_managed_singleton=function(type_name)
        assert(type_name==flow or type_name==save)
        if metadata.missing_manager==type_name then return nil end
        return {call=function(_,name)
            if metadata.throw_readiness==name then error('native readiness unavailable') end
            if name=='get_IsInTitle' then return metadata.ready==false end
            if name=='get_IsFinishedLoadScene' then return metadata.ready~=false and metadata.finished~=false end
            if name=='get_IsInLoadGameData' then return metadata.loading==true end
            assert(name=='get_IsBusy');return metadata.busy==true
        end}
    end}
local function object(values)
    return {get_field=function(_,name)
        reads=reads+1;assert(not metadata.forbid_reads,'native read after original callback')
        if values.fail then error('native primitive unavailable') end
        return values[name]
    end,call=function() error('native game method inside death hook') end}
end
local function actor(id,hp)
    local data={mData1=id,mData2=0xabcd,mData3=0xffff}
    for i=0,7 do data['mData4_' .. i]=i end
    local health={['<CurrentHitPoint>k__BackingField']=hp}
    local fields={['<ContextGUID>k__BackingField']=object(data),['<HitPoint>k__BackingField']=object(health)}
    return object({['<Controller>k__BackingField']=object(fields)}),health,fields,data
end
local function enter(hook,value)
    stack[#stack+1]={};assert(hook.pre({nil,value})==123,'original callback was suppressed')
end
local function leave(hook)
    local sentinel={};assert(hook.post(sentinel)==sentinel,'original result changed')
    table.remove(stack)
end
local module=dofile('reframework/autorun/re2_coop/death_observer.lua')
local function started_observer() local value=module.new();assert(value:start());return value end
metadata.ready=false
local dormant=module.new();local old_hooks=#hooks
assert(not dormant:start() and #hooks==old_hooks and not dormant:snapshot().started)
metadata.ready=true;assert(dormant:start() and #hooks==old_hooks+1)
assert(dormant:start() and #hooks==old_hooks+1);dormant:stop();assert(not dormant:start())
for _,unready in ipairs({{loading=true},{finished=false},{busy=true},{missing_manager=flow},
    {missing_manager=save},{throw_readiness='get_IsFinishedLoadScene'}}) do
    metadata=unready;local count=#hooks;local pending=module.new()
    assert(not pending:start() and #hooks==count)
end
metadata={}
print('ok - metadata preparation installs no hook; native scene readiness gates one registration')
local observer=started_observer();local hook=hooks[#hooks]
local value,health=actor(0xffffffff,770)
enter(hook,value);health['<CurrentHitPoint>k__BackingField']=0
metadata.forbid_reads=true;local before=reads;leave(hook);metadata.forbid_reads=false
local s=observer:snapshot()
assert(reads==before and s.sequence==1 and s.read_errors==0)
assert(s.events[1].id=='ffffffff-abcd-ffff-0001-020304050607' and s.events[1].hp_on_entry==770)
assert(s.events[1].phase=='returned' and s.events[1].callback==owner .. '.onDead')
assert(s.events[1].hp_on_exit==nil and s.events[1].is_dead==nil,'callback invented later native state')
print('ok - copies entry primitives, preserves original calls/results and performs no post-call native read')

observer=started_observer();hook=hooks[#hooks]
local outer=actor(1,0);local inner=actor(2,0)
enter(hook,outer);enter(hook,inner);leave(hook);leave(hook)
s=observer:snapshot();assert(s.sequence==2 and s.events[1].id:match('^00000002') and s.events[2].id:match('^00000001'))
s.events[1].id='changed';s.events[2].hp_on_entry=1
assert(observer:snapshot().events[1].id~='changed' and observer:snapshot().events[2].hp_on_entry==0)
print('ok - nested invocations keep their own receiver and exported records do not alias state')

observer=started_observer();hook=hooks[#hooks]
local a,_,fields=actor(3,0);fields['<HitPoint>k__BackingField']=nil
enter(hook,a);leave(hook);s=observer:snapshot()
assert(s.sequence==1 and not s.events[1].hp_present and s.events[1].hp_on_entry==nil)
local b,_,bad_fields=actor(4,0);bad_fields['<ContextGUID>k__BackingField']=nil
enter(hook,b);leave(hook)
assert(observer:snapshot().sequence==1 and observer:snapshot().read_errors==1)
local c,_,_,empty=actor(0,0);empty.mData2=0;empty.mData3=0;for i=0,7 do empty['mData4_'..i]=0 end
enter(hook,c);leave(hook);assert(observer:snapshot().read_errors==2)
print('ok - missing HP stays explicit; unavailable/zero identity records no fabricated death')

observer=started_observer();hook=hooks[#hooks]
for i=1,140 do local target=actor(i,0);enter(hook,target);leave(hook) end
s=observer:snapshot();assert(s.sequence==140 and #s.events==128 and s.discarded==12 and s.events[1].sequence==13)
enter(hook,outer);observer:stop();leave(hook);enter(hook,outer);leave(hook)
assert(observer:snapshot().sequence==140)
print('ok - history is bounded and stop suppresses new evidence without suppressing the engine')

for _,bad in ipairs({{tdb=71},{game='re3'},{no_method=true},{static=true},{returns='System.Boolean'},
    {params=true},{no_field='<Controller>k__BackingField'},{different_dispatch=true},{wrong_declaring=true},{zero_address=true}}) do
    metadata=bad;local count=#hooks;assert(not pcall(module.new) and #hooks==count)
end
metadata={}
print('ok - unsupported build, callback or field metadata is rejected before hook installation')

local real_require=require
local update,reset,published,publications
publications=0
require=function(name) assert(name=='re2_coop.death_observer');return module end
json={dump_file=function(name,data) assert(name=='re2_coop_death_observer.json');published=data;publications=publications+1 end}
log={info=function() end}
re={on_application_entry=function(name,fn) assert(name=='UpdateBehavior');update=fn end,
    on_script_reset=function(fn) reset=fn end}
dofile('reframework/diagnostics/re2_coop_death_observer.lua')
for _=1,6 do update() end
assert(published.available and published.scope=='native_em0000_on_dead_callbacks' and published.sequence==1)
assert(published.state.sequence==0,'empty callback history fabricated an event')
reset();assert(not published.available and published.reason=='script_reset' and published.state==nil)
local count=publications;for _=1,12 do update() end;assert(publications==count)
metadata={tdb=71};dofile('reframework/diagnostics/re2_coop_death_observer.lua')
assert(not published.available and published.reason=='unsupported_interfaces' and published.state==nil)
require=real_require;metadata={}
print('ok - opt-in export is scoped, clears state on reset/failure and cannot resume after reset')
print('Native onDead observer: 7 groups passed; callback evidence is not complete enemy-death synchronization')
