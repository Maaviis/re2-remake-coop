local root = 'app.ropeway.'
local manager, flow, save = root .. 'gamemastering.TimelineEventManager',
    root .. 'gamemastering.MainFlowManager', root .. 'gamemastering.SaveDataManager'
local content, performance, movie = root .. 'timeline.TimelineContents',
    root .. 'timeline.PerformanceInfo', root .. 'gamemastering.MovieManager'
local event = root .. 'timeline.TimelineDefine.EventID'
local module = dofile('reframework/autorun/re2_coop/timeline_state.lua')
local function named(name) return {get_full_name=function() return name end} end
local function fixture()
    local f = {tdb=70, game='re2', in_title=false, loading=false, finished=true, busy=false,
        count=1, calls=0, captures=0, frame=12.5, id=10001, pause=false, movie_playing=false,
        object_address=100, manager_address=20, missing_performance=false}
    local methods, fields, objects = {}, {}, {}
    local function add(type_name, name, returns, static)
        methods[type_name] = methods[type_name] or {}
        methods[type_name][name] = {returns=returns, static=static == true}
    end
    for _, name in ipairs({'get_InCameraEvent','get_CameraEventStandby','get_CameraEventPlay',
        'get_CameraEventEnableSkip','get_CameraEventSkiped','get_CameraEventNoSubtitle'}) do add(manager,name,'System.Boolean') end
    add(manager,'get_CurrentFrameForWwise','System.Single'); add(manager,'get_ActivateContentsList',content .. '[]')
    fields[manager]={_ActiveCameraEventInfo=performance,_CurrentPauseState=manager .. '.CameraEventPauseState',
        _PauseEvent='System.Boolean',_ExecPause='System.Boolean'}
    for _, name in ipairs({'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene'}) do add(flow,name,'System.Boolean') end
    add(save,'get_IsBusy','System.Boolean'); add(movie,'get_IsPlayingMovie','System.Boolean')
    add('via.SceneManager','get_CurrentScene','via.Scene',true)
    for _, name in ipairs({'get_IsPause','get_IsCameraEventStandby','get_EnableSkip','get_IsActive'}) do add(content,name,'System.Boolean') end
    add(content,'get_EventID',event); add(content,'get_CurrentState',content .. '.ProcessState')
    add(content,'get_CurrentOrder',manager .. '.EventOrder'); add(content,'get_CurrentMovieFrame','System.Single')
    add(performance,'get_ID',event); add(performance,'get_FlowID','System.String')
    add(performance,'get_State',performance .. '.EventState'); add(performance,'get_RefTimeline','via.timeline.Timeline')
    for _, name in ipairs({'get_IsCameraEvent','get_EnableSkip','get_Skiped'}) do add(performance,name,'System.Boolean') end
    add('via.timeline.Timeline','get_Frame','System.Single'); add('via.timeline.Timeline','get_PlaySpeed','System.Single')
    add('via.timeline.Timeline','get_PlayState','via.timeline.PlayState'); add('via.timeline.Timeline','get_ValidTimeline','System.Boolean')
    sdk = {get_tdb_version=function() return f.tdb end, hook=function() error('unexpected hook') end,
        find_type_definition=function(type_name)
            return {get_method=function(_, name)
                local spec = methods[type_name] and methods[type_name][name]
                if not spec or name==f.missing_method then return nil end
                return {is_static=function() return spec.static end,
                    get_param_types=function() return name==f.bad_params and {named('System.Boolean')} or {} end,
                    get_return_type=function() return named(name==f.bad_return and 'System.Void' or spec.returns) end}
            end, get_field=function(_, name)
                if not fields[type_name] or not fields[type_name][name] then return nil end
                return {is_static=function() return name==f.static_field end,
                    get_type=function() return named(fields[type_name][name]) end}
            end}
        end}
    reframework = {get_game_name=function() return f.game end}
    local function object(type_name, address, values)
        return {get_type_definition=function() return named(type_name==f.bad_object and 'wrong.Type' or type_name) end,
            get_address=function() return type(address)=='function' and address() or address end,
            get_field=function(_, name) assert(values[name]); return values[name]() end,
            call=function(_, name)
                f.calls=f.calls+1
                assert(name:match('^get_'), 'native mutation: ' .. name)
                if name==f.throw_method then error('native getter failed') end
                if name==f.nil_method then return nil end
                assert(values[name], 'unexpected getter: ' .. name)
                return values[name]()
            end}
    end
    local timeline = object('via.timeline.Timeline',101,{
        get_Frame=function() return f.frame end, get_PlaySpeed=function() return 1.0 end,
        get_PlayState=function() return 2 end, get_ValidTimeline=function() return true end})
    local active = object(performance,102,{
        get_ID=function() return f.id end,get_FlowID=function() return f.flow_id or 'ev010_00' end,
        get_State=function() return 3 end,get_RefTimeline=function() if f.no_timeline then return nil end;return timeline end,
        get_IsCameraEvent=function() return true end,get_EnableSkip=function() return true end,
        get_Skiped=function() return false end})
    local item = object(content,function() return f.object_address end,{
        get_EventID=function() return f.id end,get_CurrentState=function() return 2 end,
        get_CurrentOrder=function() return 1 end,get_CurrentMovieFrame=function() return -1.0 end,
        get_IsPause=function() return f.pause end,get_IsCameraEventStandby=function() return false end,
        get_EnableSkip=function() return true end,get_IsActive=function() return true end})
    local list = {get_size=function() return f.count end, get_element=function() return item end}
    objects[flow]=object(flow,10,{get_IsInTitle=function()
        f.captures=f.captures+1
        if f.captures==2 and f.change then f.change() end
        return f.in_title end,get_IsInLoadGameData=function() return f.loading end,
        get_IsFinishedLoadScene=function() return f.finished end})
    objects[save]=object(save,11,{get_IsBusy=function() return f.busy end})
    objects[movie]=object(movie,12,{get_IsPlayingMovie=function() return f.movie_playing end})
    objects[manager]=object(manager,function() return f.manager_address end,{
        get_InCameraEvent=function() return not f.idle end,get_CameraEventStandby=function() return false end,
        get_CameraEventPlay=function() return not f.idle end,get_CameraEventEnableSkip=function() return not f.idle end,
        get_CameraEventSkiped=function() return false end,get_CameraEventNoSubtitle=function() return false end,
        get_CurrentFrameForWwise=function() return 999.0 end,get_ActivateContentsList=function() return list end,
        _ActiveCameraEventInfo=function() if f.missing_performance then return nil end;return active end,
        _CurrentPauseState=function() return 0 end,_PauseEvent=function() return false end,_ExecPause=function() return false end})
    sdk.get_managed_singleton=function(name) if name==f.missing_singleton then return nil end;return objects[name] end
    sdk.get_native_singleton=function() return {} end
    sdk.call_native_func=function(_, _, name)
        assert(name=='get_CurrentScene'); if f.no_scene then return nil end
        return object('via.Scene',13,{})
    end
    function f:reader() return module.new() end
    return f
end
local f=fixture();local reader=f:reader();local state,reason=reader.capture()
assert(state and reason=='ok' and state.active_count==1 and state.contents[1].event_id==10001)
assert(state.camera_performance.timeline.frame==12.5 and state.camera.wwise_frame==999.0)
assert(state.camera_performance.flow_id=='ev010_00' and state.contents[1].movie_frame==-1.0)
assert(not state.movie_playing and not state.contents[1].paused)
state.contents[1].event_id=999
assert(reader.capture().contents[1].event_id==10001, 'export aliases native or cached state')
print('ok - copied activity separates native timeline, movie and audio-related frame values')

f=fixture();f.count=0;f.idle=true;f.missing_performance=true
state=f:reader().capture()
assert(state and state.active_count==0 and next(state.contents)==nil and not state.camera_performance.present)
assert(not state.camera.in_event, 'idle became a fabricated cutscene transition')
f=fixture();f.no_timeline=true;state=f:reader().capture()
assert(state.camera_performance.present and not state.camera_performance.timeline.present,
    'an absent timeline became an invented zero frame')
for _,change in ipairs({function(x) x.in_title=true end,function(x) x.loading=true end,
    function(x) x.finished=false end,function(x) x.busy=true end,function(x) x.no_scene=true end,
    function(x) x.missing_singleton=manager end}) do
    f=fixture();change(f);assert(f:reader().capture()==nil)
end
print('ok - empty activity is observable; title/loading or absent scene/manager is unavailable')

for _,change in ipairs({function(x) x.frame=0/0 end,function(x) x.frame=math.huge end,
    function(x) x.pause=1 end,function(x) x.count=65 end,function(x) x.count=-1 end,
    function(x) x.count=2 end,function(x) x.id=1.5 end,function(x) x.flow_id=string.rep('a',257) end,
    function(x) x.bad_object=performance end,function(x) x.nil_method='get_CurrentFrameForWwise' end,
    function(x) x.throw_method='get_Frame' end}) do
    f=fixture();change(f);state,reason=f:reader().capture()
    assert(state==nil and reason=='state_read_failed')
end
print('ok - invalid numbers/booleans, duplicate or oversized lists and failed getters never publish state')

for _,change in ipairs({function(x) x.frame=x.frame+1 end,function(x) x.object_address=999 end,
    function(x) x.manager_address=999 end,function(x) x.loading=true end}) do
    f=fixture();f.change=function() change(f) end;state,reason=f:reader().capture()
    assert(state==nil and reason=='state_changed')
end
print('ok - changed native values, objects or scene readiness between reads invalidate the whole sample')

for _,change in ipairs({function(x) x.tdb=71 end,function(x) x.game='re3' end,
    function(x) x.missing_method='get_RefTimeline' end,function(x) x.bad_params='get_CurrentOrder' end,
    function(x) x.bad_return='get_CurrentMovieFrame' end,function(x) x.static_field='_PauseEvent' end}) do
    f=fixture();change(f);assert(not pcall(f.reader,f) and f.calls==0)
end
print('ok - unsupported native metadata is rejected before any game getter')

f=fixture();local real_require=require;local callback,published,logs
logs={};json={dump_file=function(path,value) assert(path=='re2_coop_timeline_state.json');published=value end}
log={info=function(value) logs[#logs+1]=value end}
re={on_pre_application_entry=function(name,fn) assert(name=='UpdateBehavior');callback=fn end}
require=function(name) assert(name=='re2_coop.timeline_state');return module end
dofile('reframework/diagnostics/re2_coop_timeline_state_observer.lua')
for _=1,5 do callback() end
assert(published==nil)
callback();assert(published.available and published.sequence==1 and published.scope=='native_timeline_activity')
assert(published.state.camera_performance.timeline.frame==12.5 and published.run_id:match('^timeline%-state'))
f.throw_method='get_Frame'
for _=1,6 do callback() end
assert(not published.available and published.sequence==2 and published.state==nil)
assert(published.reason=='state_read_failed' and #logs==1)
require=real_require
print('ok - optional observer publishes fresh scoped samples and clears old state after a read failure')
print('Timeline activity: 6 groups passed; no real cutscene playback or synchronization claim')
