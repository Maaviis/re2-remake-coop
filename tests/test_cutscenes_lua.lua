package.path = 'reframework/autorun/?.lua;' .. package.path
local loaded, mod = pcall(require, 're2_coop.cutscenes')
assert(loaded, 'the paired cutscene coordinator is required')
local attempt = string.rep('d',32)
local function doc(role,peer)
    return {schema=1,role=role,attempt_id=attempt,game_pid=13,at=1234,peer=peer}
end
local function pair()
    local clock=function() return 1234 end
    local host, guest = mod.new(clock), mod.new(clock)
    local function sync()
        local h, g = host:record(), guest:record()
        host:connect(doc('H',g)); guest:connect(doc('G',h))
    end
    sync()
    return host,guest,sync
end
local function start()
    local host, guest, sync = pair()
    assert(not host:admit('evt_20001','timeline:1'))
    sync()
    assert(guest:admit('evt_20001','movie:8'))
    sync()
    assert(host:admit('evt_20001','timeline:1'))
    sync()
    return host,guest,sync
end
local solo = mod.new()
assert(solo:admit('evt_20001','movie:1') and solo:record()==nil)
local host,guest,sync = start()
assert(host:admit('evt_20001','movie:2'))
assert(host:record().occurrence==1)
host:request(); sync()
assert(guest:incoming() and not guest:authorized() and not host:authorized())
guest:answer(false); sync()
assert(not host:authorized() and not guest:authorized())
host:request(); sync(); assert(guest:incoming())
guest:answer(true); sync()
assert(host:authorized() and guest:authorized())
guest:finish('movie:8'); sync()
assert(guest:record().phase=='ended' and host:authorized())
host:finish('movie:2'); assert(host:record().phase=='playing')
host:finish('timeline:1'); assert(host:record().phase=='ended')
assert(not host:admit('evt_20001','timeline:1'))
assert(host:record().occurrence==2 and host:record().vote==0)
host:connect(nil); assert(not host:admit('evt_20001','timeline:1'))
host:finish('timeline:1')
assert(host:admit('evt_20002','timeline:4'))
host,guest,sync = start()
host:request(); guest:request(); sync()
assert(not host:incoming() and guest:incoming() and not host:authorized() and not guest:authorized())
guest:answer(true); sync()
assert(host:authorized() and guest:authorized())
host:connect(nil); assert(not host:authorized())
local same = host:record()
host:connect(doc('H',{event='evt_20002',occurrence=1,phase='playing',vote=same.vote,decision='accept'}))
assert(not host:authorized())
print('Paired camera/movie admission, second-person decisions, repeat and disconnect passed')
host,guest,sync = start()
host:request(); sync(); guest:answer(true); sync()
guest:finish('movie:8')
assert(not guest:admit('evt_20002','timeline:2') and guest:record().decision=='accept'
    and guest:record().phase=='ended', 'a rapid next scene must retain the second vote for the requester')
sync(); assert(host:authorized()); host:finish('timeline:1'); sync()
assert(not guest:admit('evt_20002','timeline:2') and guest:record().event=='evt_20002')
sync(); assert(host:admit('evt_20002','movie:5'))
host,guest,sync = pair()
assert(not host:admit('evt_20001','timeline:1')); sync()
assert(guest:admit('evt_20001','movie:8')); guest:finish('movie:8'); sync()
assert(host:admit('evt_20001','timeline:1'), 'a short peer occurrence still witnesses arrival')
print('Back-to-back scenes retain terminal evidence and the accepted vote')
local h,g,exchange=pair()
assert(not h:admit('evt_20001','timeline:1'))
assert(not g:admit('evt_20002','movie:2')); exchange()
assert(not h:admit('evt_20002','movie:2'))
assert(g:admit('evt_20001','timeline:1'), 'when both native candidates arrived, follow host ordering')
exchange(); assert(h:admit('evt_20001','timeline:1'))
g:finish('timeline:1');h:finish('timeline:1');exchange()
assert(not g:admit('evt_20002','movie:2'));exchange()
assert(h:admit('evt_20002','movie:2') and h:record().occurrence==1)
exchange();assert(g:admit('evt_20002','movie:2') and g:record().occurrence==1)
-- Run the normal autorun with only the engine/ImGui/file boundary substituted.
local hooks, frames, calls, keys, drawn, received, publication = {}, {}, {}, {}, {}, nil, nil
local root='app.ropeway.'
local timeline=root..'timeline.TimelinePerformance'
local player=root..'movie.MoviePlayer'
local manager=root..'gamemastering.MovieManager'
local enum=root..'timeline.TimelineDefine.EventID'
local defs={}
local function type_of(name)
    return {get_full_name=function() return name end}
end
local function definition(name)
    local d=type_of(name)
    local values={EV000=20000,PreStart=2,Standby=3,PlayStart=4,Play=5,Kick=6,Request=7}
    if name:match('EventOrder$') then values.Play=1 end
    if name:match('Phase$') then values.Play=8 end
    function d:get_fields()
        return {{is_static=function() return true end,get_name=function() return 'EV000' end,get_data=function() return 20000 end}}
    end
    function d:get_field(key)
        return {is_static=function() return true end,get_data=function() return values[key] end}
    end
    function d:get_method(key)
        local args, returns={},'System.Void'
        if key=='requestPlayAndFinishEvent' then args={type_of(player),type_of('System.Boolean'),type_of(enum)};returns='System.Boolean' end
        if key=='requestPlayWithPlayer' then args={type_of(player),type_of('System.Action'),type_of('System.Action')} end
        local method={is_static=function() return false end,get_param_types=function() return args end,
            get_return_type=function() return type_of(returns) end,key=name..'.'..key}
        function method:call(obj,...) return obj:call(key,...) end
        return method
    end
    return d
end
local storage={}
thread={get_id=function() return 42 end,get_hook_storage=function() return storage end}
sdk={find_type_definition=function(name) defs[name]=defs[name] or definition(name);return defs[name] end,
    to_managed_object=function(value) return value end,to_int64=function(x) return type(x)=='table' and x:get_address() or x end,
    get_tdb_version=function() return 70 end,PreHookResult={CALL_ORIGINAL=1,SKIP_ORIGINAL=2},
    hook=function(method,pre,post) hooks[method.key]={pre,post} end}
local function invoke(t,method,obj,orig,...)
    local h=hooks[t..'.'..method]
    local result=314
    if not h or h[1]({0,obj,...})~=2 then
        calls[method]=(calls[method] or 0)+1
        if orig then result=orig() end
    end
    if h then result=h[2](result) end
    return result
end
local function object(t,address,fields)
    local o={get_address=function() return address end,get_type_definition=function() return sdk.find_type_definition(t) end,
        get_field=function(_,key) return fields[key] end}
    function o:call(key,...) if fields[key]~=nil then return fields[key] end;return invoke(t,key,self,nil,...) end
    return o
end
os.time=function() return 1234 end
reframework={get_game_name=function() return 're2' end,is_key_down=function(_,k) return keys[k] or false end}
re={on_frame=function(cb) frames[#frames+1]=cb end}
local function frame() for _,f in ipairs(frames) do f() end end
local function key(k) keys[k]=true;frame();keys[k]=false;frame() end
local layer={add_rect_filled=function() end,add_text=function(_,a,b,c) drawn[#drawn+1]=c end}
imgui={get_foreground_draw_list=function() return layer end,get_display_size=function() return {x=1280,y=720} end,
    calc_text_size=function() return {x=200,y=15} end}
fs={read=function() return '' end}
json={load_file=function() return nil end,dump_file=function() error('simulator must not publish real records') end}
log={info=function() end,error=function(msg) error(msg) end,warn=function() end}
local sim_on=false
package.loaded['re2_coop.cutscene_test_peer']={
    poll=function(real)
        if sim_on and not real then local d=doc('H',received); d.simulated=true; return d end
    end,publish=function(r) publication=r end}
local ok=pcall(dofile,'reframework/autorun/re2_coop_cutscenes.lua')
assert(ok and hooks[timeline..'.updateProcess'] and hooks[manager..'.requestPlayAndFinishEvent'],
    'normal autorun must install typed movie and camera update gates')
local info_fields={get_IsCameraEvent=false,get_ID=20000,get_EnableSkip=true}
local info=object(root..'timeline.PerformanceInfo',201,info_fields)
local t_fields={get_State=4,get_CurrentEventInfo=info}
local t=object(timeline,401,t_fields)
frame(); invoke(timeline,'updateProcess',t)
assert(calls.updateProcess==1)
sim_on=true;frame()
invoke(timeline,'updateProcess',t);assert(calls.updateProcess==2 and not publication)
info_fields.get_IsCameraEvent=true
invoke(timeline,'updateProcess',t);frame()
assert(calls.updateProcess==2 and publication and publication.phase=='waiting')
assert(table.concat(drawn,' '):match('Simulierter Gast'))
received={event='evt_20000',occurrence=1,phase='waiting',vote=0,decision='none'}
frame(); invoke(timeline,'updateProcess',t)
assert(calls.updateProcess==3)
t_fields.get_State=5
received.phase='playing';frame()
invoke(timeline,'skip',t); frame()
assert(not calls.skip and publication.decision=='request')
received.vote,received.decision=1,'decline';frame();invoke(timeline,'updateProcess',t)
assert(not calls.skip)
key(0x75); assert(publication.vote==2 and publication.decision=='request')
received.vote,received.decision=2,'accept';frame()
invoke(timeline,'updateProcess',t); invoke(timeline,'updateProcess',t)
assert(calls.skip==1,'reentrant native skip must execute exactly once')
invoke(timeline,'cancelProcess',t);frame(); assert(publication.phase=='ended')
local m=object(manager,91,{})
local mf={get_CurrentPhase=6,isEnablePause=true}
local mp=object(player,111,mf)
local other=object(player,112,mf)
received.phase='ended';frame()
assert(invoke(manager,'requestPlayAndFinishEvent',m,function() return 0 end,mp,1,20000)==0)
invoke(player,'update',mp); assert(calls.update==1)
assert(invoke(manager,'requestPlayAndFinishEvent',m,function() return 257 end,mp,1,20000)==257)
invoke(player,'update',other); invoke(player,'update',mp); frame()
assert(calls.update==2 and publication.occurrence==2 and publication.phase=='waiting')
received.occurrence,received.phase,received.vote,received.decision=2,'waiting',0,'none';frame()
invoke(player,'update',mp);assert(calls.update==3)
print('Normal autorun respects native return values, targets, camera type, controls and one-shot skip')
