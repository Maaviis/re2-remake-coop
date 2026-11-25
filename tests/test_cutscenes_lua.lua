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
assert(host:record().decision=='decline','requester must acknowledge a decline so either player can initiate again')
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
local event_manager=root..'gamemastering.TimelineEventManager'
local contents=root..'timeline.TimelineContents'
local player=root..'movie.MoviePlayer'
local manager=root..'gamemastering.MovieManager'
local enum=root..'timeline.TimelineDefine.EventID'
local defs={}
local function type_of(name)
    return {get_full_name=function() return name end}
end
local function definition(name)
    local d=type_of(name)
    local values={EV000=20000,PreStart=2,Standby=3,PlayStart=4,Play=5,Kick=6,Request=7,Wait=0}
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
    function o:call(key,...)
        if type(fields[key])=='function' then return fields[key](...) end
        if fields[key]~=nil then return fields[key] end
        return invoke(t,key,self,nil,...)
    end
    return o
end
local camera_fields={get_CameraEventPlay=true,get_CameraEventEnableSkip=true}
local camera=object(event_manager,501,camera_fields)
sdk.get_managed_singleton=function(name) if name==event_manager then return camera end end
local wall=1234
os.time=function() return wall end
reframework={get_game_name=function() return 're2' end,is_key_down=function(_,k) return keys[k] or false end,
    is_drawing_ui=function() return false end}
local updates={}
re={on_frame=function(cb) frames[#frames+1]=cb end,
    on_pre_application_entry=function(name,cb) assert(name=='UpdateBehavior');updates[#updates+1]=cb end}
local function tick() for _,f in ipairs(updates) do f() end end
local function draw() for _,f in ipairs(frames) do f() end end
local function frame() tick(); draw() end
local layer={add_rect_filled=function() end,add_text=function(_,a,b,c) drawn[#drawn+1]=c end}
imgui={get_foreground_draw_list=function() return layer end,get_display_size=function() return {x=1280,y=720} end,
    calc_text_size=function() return {x=200,y=15} end}
fs={read=function() return '' end}
json={load_file=function() return nil end,dump_file=function() error('simulator must not publish real records') end}
local hud_warnings=0
log={info=function() end,error=function(msg) error(msg) end,warn=function() hud_warnings=hud_warnings+1 end}
local sim_on,cross_clock_boundary=false,false
package.loaded['re2_coop.cutscene_test_peer']={
    poll=function(real)
        if sim_on and not real then
            if cross_clock_boundary then wall=wall+1; cross_clock_boundary=false end
            local d=doc('H',received); d.simulated=true; d.at=os.time(); return d
        end
    end,publish=function(r) publication=r end}
local ok=pcall(dofile,'reframework/autorun/re2_coop_cutscenes.lua')
assert(ok and hooks[timeline..'.playStart'] and hooks[manager..'.requestPlayAndFinishEvent'],
    'normal autorun must install typed movie and camera start gates')
local info_fields={get_IsCameraEvent=false,get_ID=20000,get_EnableSkip=true}
local info=object(root..'timeline.PerformanceInfo',201,info_fields)
local content_fields={get_CurrentOrder=1,get_IsPause=false,get_EventID=20000}
local content=object(contents,301,content_fields)
local t_fields={get_State=2,get_CurrentEventInfo=info,_Contents=content}
local t=object(timeline,401,t_fields)
content_fields.get_Performance=t
camera_fields.get_ActivateContentsList={get_size=function() return 1 end,get_element=function() return content end}
frame(); invoke(timeline,'updateProcess',t)
assert(calls.updateProcess==1)
sim_on=true;frame()
invoke(timeline,'updateProcess',t);assert(calls.updateProcess==2 and not publication)
t_fields.get_State=4
invoke(timeline,'playStart',t);tick()
assert(calls.playStart==1 and not publication,'a non-camera event starts without a partner')
t_fields.get_State=2
info_fields.get_IsCameraEvent=true
-- TDB70 prepares actors and fades in PreStart. A separate TimelineContents.update
-- dispatches playStart on each tick in state 4 until the original changes it to 5.
invoke(timeline,'updateProcess',t,function() t_fields.get_State=4 end)
assert(t_fields.get_State==4,'camera and fade preparation must run before the partner arrives')
local function content_update()
    if t_fields.get_State==4 then
        invoke(timeline,'playStart',t,function() t_fields.get_State=5 end)
    end
end
content_update();tick()
invoke(timeline,'updateProcess',t);content_update();tick()
assert(t_fields.get_State==4 and calls.playStart==1 and publication and publication.phase=='waiting',
    'hold the native camera start across retries and publish waiting without drawing')
local good_layer=imgui.get_foreground_draw_list
imgui.get_foreground_draw_list=function() error('HUD fixture unavailable') end
draw();draw();assert(hud_warnings==1)
imgui.get_foreground_draw_list=good_layer;draw()
assert(table.concat(drawn,' '):match('Simulierter Gast'))
local function hud_text()
    drawn={}
    draw()
    return table.concat(drawn,' ')
end
local waiting_text=hud_text()
assert(waiting_text:find('F2 Gast ankommen lassen',1,true) and not waiting_text:find('F3') and not waiting_text:find('F4'),
    'show only the guest arrival control while waiting')
cross_clock_boundary=true
tick(); content_update()
assert(t_fields.get_State==4 and calls.playStart==1,
    'a freshly reported solo scope across a wall-clock second must retain its waiting native camera')
received={event='evt_20000',occurrence=1,phase='waiting',vote=0,decision='none'}
tick();content_update();content_update()
assert(calls.playStart==2 and t_fields.get_State==5,'partner arrival releases the original audiovisual start exactly once')
received.phase='playing';frame()
local playing_text=hud_text()
assert(playing_text:find('F4') and not playing_text:find('F2') and not playing_text:find('F3'),
    'ordinary playback offers a guest skip request without showing vote keys')
invoke(timeline,'skip',t); frame()
assert(not calls.skip and publication.decision=='request')
local voting_text=hud_text()
assert(voting_text:find('F2 Ja',1,true) and voting_text:find('F3 Nein',1,true) and not voting_text:find('F4'),
    'show guest vote controls only for an outstanding host request')
received.vote,received.decision=1,'decline';frame();invoke(timeline,'updateProcess',t)
assert(not calls.skip)
keys[0x75]=true;tick();tick();keys[0x75]=false;tick()
assert(publication.vote==2 and publication.decision=='request','one F6 edge must work with the menu closed and no draw')
received.vote,received.decision=2,'accept';frame()
local accepted_text=hud_text()
assert(not accepted_text:find('F2') and not accepted_text:find('F3') and not accepted_text:find('F4'))
invoke(timeline,'updateProcess',t)
assert(not calls.skip and not calls.skipEventPauseUI,'consent must not bypass the native camera event manager')
camera_fields._ActiveCameraEventInfo=object(root..'timeline.PerformanceInfo',202,info_fields)
tick()
assert(not calls.skipEventPauseUI,'an unrelated active camera must not consume the vote')
camera_fields._ActiveCameraEventInfo=info
camera_fields.get_CameraEventEnableSkip=false
tick()
assert(not calls.skipEventPauseUI,'respect the native camera skip availability')
camera_fields.get_CameraEventEnableSkip=true
tick();tick()
assert(calls.skipEventPauseUI==1 and not calls.skip,'queue exactly one skip on the active native camera event')
assert(publication.phase=='playing','a native request is not proof of scene completion')
camera_fields._SkipEvent,camera_fields._PauseEvent,camera_fields._WwiseRequestExecEnd=true,true,true
camera_fields._ExecPause,camera_fields._CurrentPauseState=true,5
info_fields.get_Skiped=false
content_fields.get_IsPause=true
content_fields.skip=function()
    invoke(contents,'skip',content,function()
        content_fields.get_IsPause=false
        invoke(timeline,'skip',t)
    end)
end
tick()
assert(not calls.skip,'do not dispatch while the native audio pause transition runs')
camera_fields._ExecPause,camera_fields._CurrentPauseState=false,0
tick();tick()
assert(calls.skip==2 and content_fields.get_IsPause==false,
    'dispatch once through the paused contents if the native manager leaves it pending')
assert(publication.phase=='playing','wait for native teardown after content dispatch')
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
invoke(player,'doUpdateFinish',mp);frame()
received.phase='ended';frame()
local function forward()
    return invoke(player,'requestPlayWithPlayer',other,nil,mp,'native onplay','native onfinish') and 1
end
assert(invoke(manager,'requestPlayAndFinishEvent',m,forward,mp,1,20000)==1)
local count=calls.update
invoke(player,'update',mp);invoke(player,'update',other);frame()
assert(calls.update==count+1 and publication.occurrence==3,
    'only the forwarded playback receiver may be held, the source player remains untouched')
received.occurrence,received.phase=3,'waiting';frame()
invoke(player,'update',other)
assert(calls.update==count+2)
