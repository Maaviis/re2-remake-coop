local root = 'app.ropeway.'
local flow_name, gui_name = root .. 'gamemastering.MainFlowManager', root .. 'gui.GUIMaster'
local pause_name, behavior_name = root .. 'gamemastering.PauseFlow', root .. 'gui.PauseBehavior'
local save_name = root .. 'gamemastering.SaveDataManager'
local function named(name) return {get_full_name = function() return name end} end
local specs = {}
local function add(t, name, returns, params, static)
    specs[t] = specs[t] or {}; specs[t][name] = {returns = returns, params = params or {}, static = static == true}
end
add(flow_name, 'goPause', 'System.Void'); add(flow_name, 'get_Pause', pause_name)
for _, name in ipairs({'get_IsInTitle','get_IsInLoadGameData','get_IsFinishedLoadScene',
        'get_IsInPause','get_IsInGameNotPause'}) do add(flow_name,name,'System.Boolean') end
add(gui_name,'get_IsOpenPause','System.Boolean'); add(save_name,'get_IsBusy','System.Boolean')
add(behavior_name,'get_EnableInput','System.Boolean'); add(behavior_name,'toReturnGame','System.Void')
add('via.SceneManager','get_CurrentScene','via.Scene',{},true)
add('via.Scene','findComponents','via.Component[]',{'System.Type'})
local module = dofile('reframework/autorun/re2_coop/gameplay_pause.lua')
local function fixture(options)
    options = options or {}
    local f = {paused=false,menu=false,playing=true,title=false,loading=false,finished=true,busy=false,
        player_address=10,scene_address=20,flow_address=30,pause_address=40,behavior_address=50,
        count=1,state=1,enabled=true,calls={},reads=0}
    local behavior = {get_address=function() return f.behavior_address end,
        get_type_definition=function() return named(behavior_name) end,
        call=function(_,name)
            if name=='get_EnableInput' then return f.enabled end
            assert(name=='toReturnGame','wrong native return path: '..name)
            f.calls[#f.calls+1]='menu_return'
            if f.throw_return then error('return failed') end
            if not f.delay_return then f.paused,f.menu,f.playing,f.state=false,false,true,5 end
        end}
    local pause = {get_address=function() return f.pause_address end,
        get_type_definition=function() return named(pause_name) end,
        get_field=function(_,name) assert(name=='StateValue'); return f.state end}
    local list = {get_size=function() return f.count end,get_element=function(_,i) assert(i==0); return behavior end}
    local scene = {get_address=function() return f.scene_address end,
        get_type_definition=function() return named('via.Scene') end,
        call=function(_,name,t) assert(name=='findComponents' and t==behavior_name); return list end}
    local player = {get_address=function() return f.player_address end}
    local flow = {get_address=function() return f.flow_address end,
        call=function(_,name)
            f.reads=f.reads+1
            if name=='goPause' then
                f.calls[#f.calls+1]='pause'
                if f.throw_pause then error('pause failed') end
                if not f.delay_pause then f.paused,f.menu,f.playing,f.state=true,true,false,1 end
                return
            end
            if name=='get_Pause' then return not f.no_pause and pause or nil end
            local values={get_IsInTitle=f.title,get_IsInLoadGameData=f.loading,get_IsFinishedLoadScene=f.finished,
                get_IsInPause=f.paused,get_IsInGameNotPause=f.playing}
            if name==f.throw_read then error('read failed') end
            assert(values[name]~=nil,'unexpected flow write: '..name);return values[name]
        end}
    local gui = {call=function(_,name) assert(name=='get_IsOpenPause'); return f.menu end}
    local save = {call=function(_,name) assert(name=='get_IsBusy'); return f.busy end}
    local players = {call=function(_,name) assert(name=='get_CurrentPlayer');return not f.no_player and player or nil end}
    reframework={get_game_name=function() return options.game or 're2' end}
    sdk={get_tdb_version=function() return options.tdb or 70 end,game_namespace=function(n) return root..n end,
        typeof=function(n) assert(n==behavior_name);return n end,
        find_type_definition=function(t)
            if t==options.missing_type then return nil end
            return {get_method=function(_,name)
                local spec=assert(specs[t] and specs[t][name],t..':'..name)
                return {is_static=function() if name==options.bad_static then return not spec.static end;return spec.static end,
                    get_return_type=function() return named(name==options.bad_return and 'System.Void' or spec.returns) end,
                    get_param_types=function()
                        local p={};for i,n in ipairs(spec.params) do p[i]=named(name==options.bad_parameter and 'System.Int32' or n) end;return p
                    end}
            end,get_field=function(_,name)
                if name==options.missing_field then return nil end
                if t==pause_name then
                    assert(name=='StateValue');return {is_static=function() return false end,
                        get_type=function() return named(pause_name..'.State') end}
                end
                assert(t==pause_name..'.State' and name=='UPDATE')
                return {is_static=function() return true end,get_data=function() return options.bad_update and 2 or 1 end}
            end}
        end,
        get_native_singleton=function(name) assert(name=='via.SceneManager');return not f.no_scene and {} or nil end,
        call_native_func=function(_,_,name) assert(name=='get_CurrentScene');return scene end,
        get_managed_singleton=function(name)
            return assert(({[flow_name]=flow,[gui_name]=gui,[save_name]=save,[root..'PlayerManager']=players})[name])
        end}
    f.controller = module.new
    return f
end
local id,other=string.rep('a',32),string.rep('b',32)
local f=fixture();local pause=f.controller()
assert(pause:request(id));assert(pause.phase=='requesting' and not pause.verified)
assert(pause:poll() and pause.phase=='held' and pause.verified)
assert(not pause:request(other) and pause.request_id==id,'overlap replaced ownership')
assert(not pause:release(other) and #f.calls==1,'foreign return changed the game')
assert(pause:release(id));assert(pause.phase=='returning' and not pause.verified)
assert(pause.released_player == nil and pause.released_scene == nil)
assert(pause:poll() and pause.phase=='released')
assert(pause.released_player == tostring(f.player_address) and pause.released_scene == tostring(f.scene_address))
assert(table.concat(f.calls,',')=='pause,menu_return','native menu action was bypassed')
assert(not pause:request(id),'replayed pause ID was accepted')
assert(pause:request(other));assert(pause.released_player == nil and pause.released_scene == nil)
assert(pause:poll());assert(pause:cleanup());assert(pause:poll())
local function released_fixture()
    local current=fixture()
    local controller=current.controller()
    assert(controller:request(id) and controller:poll() and controller:release(id) and controller:poll())
    return current, controller
end
f,pause=released_fixture()
assert(not pause:rehold(other) and #f.calls==2)
assert(pause:rehold(id) and pause.phase=='requesting' and pause.released_player==nil)
assert(pause:poll() and pause.phase=='held' and table.concat(f.calls,',')=='pause,menu_return,pause')
assert(not pause:rehold(id) and not pause:request(id) and #f.calls==3)
for _,change in ipairs({'player_address','scene_address','flow_address'}) do
    f,pause=released_fixture(); f[change]=99
    local accepted,reason=pause:rehold(id)
    assert(not accepted and reason=='pause_context_replaced' and #f.calls==2,change)
end
f,pause=released_fixture(); f.paused,f.menu,f.playing=true,true,false
assert(not pause:rehold(id) and #f.calls==2,'player pause was taken over')
for _,change in ipairs({'title','loading','busy','paused','menu'}) do
    f=fixture();f[change]=true;pause=f.controller();assert(not pause:request(id));assert(#f.calls==0,change)
end
for _,change in ipairs({'no_player','no_scene'}) do
    f=fixture();f[change]=true;assert(not f.controller():request(id));assert(#f.calls==0,change)
end
f=fixture();f.finished=false;assert(not f.controller():request(id))
f=fixture();f.playing=false;assert(not f.controller():request(id))
for _,change in ipairs({'player_address','scene_address','flow_address','pause_address','behavior_address'}) do
    f=fixture();pause=f.controller();assert(pause:request(id));assert(pause:poll());f[change]=99
    assert(not pause:poll() and pause.phase=='lost',change)
    assert(not pause:release(id) and #f.calls==1,'replacement pause was resumed')
end
f=fixture();pause=f.controller();assert(pause:request(id));f.count=2
assert(not pause:poll() and not pause.verified,'ambiguous menu was accepted')
f.count=1;assert(pause:poll());f.throw_read='get_IsInPause'
assert(not pause:poll() and not pause.verified);assert(not pause:release(id) and #f.calls==1)
f=fixture();pause=f.controller();assert(pause:request(id));assert(pause:poll());f.paused,f.menu,f.playing=false,false,true
assert(not pause:poll() and pause.phase=='lost');assert(not pause:cleanup() and #f.calls==1)
f=fixture();f.delay_return=true;pause=f.controller();assert(pause:request(id));assert(pause:poll());assert(pause:release(id))
assert(not pause:poll() and pause.phase=='returning','return was confirmed before native menu completion')
f.paused,f.playing=false,true;assert(not pause:poll(),'open GUI survived the return check')
f.menu=false;assert(pause:poll() and pause.phase=='released')
f=fixture();f.delay_pause=true;pause=f.controller();assert(pause:request(id));assert(not pause:poll())
assert(not pause:release(id));f.paused,f.menu,f.playing=true,true,false;assert(pause:poll())
f=fixture();f.throw_pause=true;pause=f.controller();assert(not pause:request(id) and pause.phase=='failed')
f=fixture();pause=f.controller();assert(pause:request(id));assert(pause:poll());f.throw_return=true
assert(not pause:release(id) and pause.reason=='pause_return_failed');assert(not pause:release(id) and #f.calls==2)
for _,options in ipairs({{game='re3'},{tdb=71},{bad_return='get_IsInPause'},{bad_static='get_CurrentScene'},
        {bad_parameter='findComponents'},{missing_field='StateValue'},{bad_update=true}}) do
    f=fixture(options);assert(not pcall(f.controller));assert(#f.calls==0 and f.reads==0)
end
print('Native gameplay pause: menu return, ownership, replay, scene/player changes, read failures and delayed completion passed')

-- Probe receipts, bounded cleanup and replay handling are independent of native mutation tests above.
local now, command, output, tick, reset, clock_failure = 100, nil, nil, nil, nil, false
local controller = {phase='idle',reason='',verified=true,request_id='',requests=0,returns=0}
function controller:poll()
    if self.phase=='requesting' then self.phase='held' end
    if self.phase=='returning' then self.phase='released' end
    self.verified=true;return true
end
function controller:request(request_id)
    if self.phase=='held' or self.phase=='requesting' then return false,'pause_in_progress' end
    self.request_id,self.phase,self.verified=request_id,'requesting',false;self.requests=self.requests+1;return true
end
function controller:release(request_id)
    if request_id~=self.request_id or self.phase~='held' then return false,'pause_not_owned' end
    self.phase,self.verified='returning',false;self.returns=self.returns+1;return true
end
function controller:cleanup() return self:release(self.request_id) end
package.loaded['re2_coop.gameplay_pause']={new=function() return controller end}
os.time=function() return now end
local load_id=string.rep('c',32)
local guard={schema=1,active=true,hooks=26,at=now,load_request_id=load_id,policy_id=load_id,
    load_phase='scene_loaded',load_error='',denied_loads=0,allowed_load_calls=1,allowed_slot=4,load_index=4,has_player=true}
sdk.find_type_definition=function(name)
    assert(name==root..'GameClock')
    return {get_method=function() return {is_static=function() return false end,
        get_param_types=function() return {} end,get_return_type=function() return named('System.UInt64') end} end}
end
sdk.get_managed_singleton=function(name)
    assert(name==root..'GameClock')
    return {call=function() if clock_failure then error('clock lost') end;return 0 end}
end
json={load_file=function(path)
    if path=='re2_coop_pause_command.json' then return command end
    assert(path=='re2_coop_save_guard.json');return guard
end,dump_file=function(path,value) assert(path=='re2_coop_gameplay_pause.json');output=value end}
log={info=function() end}
re={on_pre_application_entry=function(name,fn) assert(name=='UpdateBehavior');tick=fn end,
    on_script_reset=function(fn) reset=fn end}
dofile('reframework/diagnostics/re2_coop_gameplay_pause_probe.lua')
local function advance() for _=1,6 do tick() end end
command={schema=1,id=id,at=now,action='pause',load_request_id=load_id,seconds=3}
advance();assert(output.phase=='held' and output.available and controller.requests==1)
command={schema=1,id=other,at=now,action='pause',load_request_id=load_id,seconds=3}
advance();assert(output.pause_id==id and output.command_id==other and output.command_error=='pause_in_progress')
now=104;guard.at=now;advance()
assert(output.phase=='released' and output.release_id=='deadline' and controller.returns==1)
command={schema=1,id=id,at=now,action='pause',load_request_id=load_id,seconds=3}
advance();assert(controller.requests==1,'replayed command reacquired the game')
local third,fourth,fifth=string.rep('d',32),string.rep('e',32),string.rep('f',32)
command={schema=1,id=third,at=now,action='pause',load_request_id=load_id,seconds=10}
guard.policy_id=other;advance();assert(controller.requests==1 and output.command_error=='matching_native_load_guard_required')
guard.policy_id=load_id
command={schema=1,id=fourth,at=now,action='pause',load_request_id=load_id,seconds=10}
advance();assert(controller.requests==2 and output.pause_id==fourth)
clock_failure=true;advance();assert(not output.available and output.reason=='clock_unavailable' and output.phase=='held')
command={schema=1,id=fifth,at=now,action='return',pause_id=fourth}
advance();assert(controller.returns==2 and output.release_id==fifth and output.phase=='released')
clock_failure=false;command={schema=1,id=string.rep('1',32),at=now,action='pause',load_request_id=load_id,seconds=10,extra=true}
advance();assert(controller.requests==2,'unknown command field was accepted')
command.extra=nil;command.seconds=true;advance();assert(controller.requests==2,'boolean lease was accepted')
command.seconds=10;advance();assert(controller.requests==3)
reset();assert(controller.returns==3,'script reset did not use the owned menu return')
print('Pause probe: independent receipts, overlap, guard binding, replay, clock loss, deadline and reset cleanup passed')
