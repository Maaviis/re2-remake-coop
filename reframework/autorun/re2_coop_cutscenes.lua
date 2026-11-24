-- TDB70 story playback. Hold only retryable updates for an identified camera performance
-- or a movie player associated with a successful native event request.
if reframework:get_game_name()~='re2' or sdk.get_tdb_version()~=70 then return end
local model=require('re2_coop.cutscenes')
local has_sim,sim=pcall(require,'re2_coop.cutscene_test_peer')
local state=model.new()
local root='app.ropeway.'
local performance=root..'timeline.TimelinePerformance'
local contents=root..'timeline.TimelineContents'
local player=root..'movie.MoviePlayer'
local movies=root..'gamemastering.MovieManager'
local timeline=root..'gamemastering.TimelineEventManager'
local event_type=root..'timeline.TimelineDefine.EventID'
local original,block=sdk.PreHookResult.CALL_ORIGINAL,sdk.PreHookResult.SKIP_ORIGINAL
local armed=false
local bound_movies, camera_infos, pending_by_thread={},{},{}
local applying
local function owner(prefix,address) return prefix..':'..tostring(address) end
local function address(obj) return obj and obj:get_address() end

local function install()
    local queue={}
    local function hook(class,name,before,after,returns,parameters)
        local method=assert(sdk.find_type_definition(class):get_method(name),name)
        local args=method:get_param_types()
        assert(not method:is_static() and method:get_return_type():get_full_name()==(returns or 'System.Void')
            and #args==#(parameters or {}),name)
        for i,p in ipairs(parameters or {}) do assert(args[i]:get_full_name()==p,name) end
        queue[#queue+1]={method,before,after}
    end
    local function value(class,key)
        local f=assert(sdk.find_type_definition(class):get_field(key),key)
        assert(f:is_static(),key)
        return assert(f:get_data(nil),key)
    end
    local known={}
    for _,f in ipairs(sdk.find_type_definition(event_type):get_fields()) do
        if f:is_static() and (f:get_name():match('^EV%d+$') or f:get_name():match('^CF%d+$')) then
            local id=f:get_data(nil)
            known[id]='evt_'..tostring(id)
        end
    end
    assert(next(known),'missing story event IDs')
    local tl_state=root..'timeline.UpdateState'
    local pre,standby,start,play=value(tl_state,'PreStart'),value(tl_state,'Standby'),value(tl_state,'PlayStart'),value(tl_state,'Play')
    local order_play=value(timeline..'.EventOrder','Play')
    local kick=value(player..'.Phase','Kick')
    local request=value(player..'.Phase','Request')
    local movie_play=value(player..'.Phase','Play')
    local function owned(k) return state.owners[k]==true end
    local function intercept(k)
        if not owned(k) or applying==state.scene then return end
        state:request()
        return block
    end
    local function apply(obj,k,allowed,target)
        if not owned(k) or state.applied or not allowed or not state:authorized() then return end
        -- The native call re-enters our hook and may synchronously skip another
        -- representation of the same scene. The exception lasts only for this call.
        state.applied,applying=true,state.scene
        local ok,err=pcall(obj.call,obj,target)
        applying=nil
        if not ok then log.error('RE2_COOP_CUTSCENE native skip: '..tostring(err)) end
    end

    hook(performance,'updateProcess',function(a)
        local k=owner('timeline',sdk.to_int64(a[2]))
        if not state.link and not owned(k) and not state.deferred[k] then return end
        local obj=sdk.to_managed_object(a[2])
        local phase=obj:call('get_State')
        if phase~=pre and phase~=standby and phase~=start and phase~=play then return end
        local info=obj:call('get_CurrentEventInfo')
        if not info or info:call('get_IsCameraEvent')~=true then return end
        local event=known[info:call('get_ID')]
        if not event then return end
        if phase==play then
            if owned(k) and state.scene.event==event then
                apply(obj,k,info:call('get_EnableSkip')==true,'skip')
            end
            return
        end
        -- Loading/standby can be speculative. Only a real Play order or the
        -- native PlayStart dispatch signals that this camera is about to start.
        if phase~=start then
            local content=obj:get_field('_Contents')
            if not content or content:call('get_CurrentOrder')~=order_play then return end
        end
        local admitted=state:admit(event,k)
        if owned(k) then camera_infos[k]=address(info) end
        if not admitted then return block end
    end)
    for _,name in ipairs({'cancelProcess','resetProcess','updateCleanup'}) do
        hook(performance,name,function(a)
            local k=owner('timeline',sdk.to_int64(a[2]))
            state:finish(k); camera_infos[k]=nil
        end)
    end
    hook(performance,'skip',function(a) return intercept(owner('timeline',sdk.to_int64(a[2]))) end)
    hook(contents,'skip',function(a)
        if not next(camera_infos) then return end
        local obj=sdk.to_managed_object(a[2]):call('get_Performance')
        if obj then return intercept(owner('timeline',address(obj))) end
    end)
    hook(timeline,'skipEventPauseUI',function(a)
        if not next(camera_infos) or applying then return end
        local mgr=sdk.to_managed_object(a[2])
        local current=address(mgr:get_field('_ActiveCameraEventInfo'))
        for k,info in pairs(camera_infos) do
            if current==info and owned(k) then
                state:request()
                mgr:call('resumeEventPauseUI')
                return block
            end
        end
    end)

    -- Observe native admission without altering its Boolean, player, prebiz or
    -- delegates. A manager may forward a source movie to its own playback player.
    hook(movies,'requestPlayAndFinishEvent',function(a)
        local thread_id=thread.get_id()
        local previous=pending_by_thread[thread_id]
        local call={previous=previous,generation=state.counts,targets={}}
        pending_by_thread[thread_id]=call
        thread.get_hook_storage().re2_scene_movie=call
        if state.link then
            call.event=known[sdk.to_int64(a[5]) & 0xffffffff]
            call.source=sdk.to_int64(a[3])
            if call.event and call.source~=0 then call.targets[call.source]=true end
        end
    end,function(retval)
        local call=thread.get_hook_storage().re2_scene_movie
        if call then
            pending_by_thread[thread.get_id()]=call.previous
            if call.event and call.generation==state.counts and (sdk.to_int64(retval) & 0xff)==1 then
                for key in pairs(call.targets) do
                    local k=owner('movie',key)
                    if bound_movies[k] and bound_movies[k]~=call.event then state:finish(k) end
                    bound_movies[k]=call.event
                end
            end
        end
    end,'System.Boolean',{player,'System.Boolean',event_type})
    hook(player,'requestPlayWithPlayer',function(a)
        local call=pending_by_thread[thread.get_id()]
        if call and call.event and call.source==sdk.to_int64(a[3]) then
            call.targets[sdk.to_int64(a[2])]=true
        end
    end,nil,'System.Void',{player,'System.Action','System.Action'})
    hook(player,'update',function(a)
        if not next(bound_movies) then return end
        local k=owner('movie',sdk.to_int64(a[2]))
        local event=bound_movies[k]
        if not event then return end
        local obj=sdk.to_managed_object(a[2])
        local phase=obj:call('get_CurrentPhase')
        if phase==kick or phase==request then
            if not state:admit(event,k) then return block end
        elseif phase==movie_play and owned(k) then
            apply(obj,k,obj:call('isEnablePause')==true,'requestSkip')
        end
    end)
    hook(player,'requestSkip',function(a) return intercept(owner('movie',sdk.to_int64(a[2]))) end)
    hook(movies,'requestSkipMovie',function(a)
        if not next(bound_movies) or applying then return end
        local mgr=sdk.to_managed_object(a[2])
        local active=mgr:get_field('_StaticPlayer')
        if active and owned(owner('movie',address(active))) then
            state:request()
            if mgr:get_field('_ExecPause') or mgr:get_field('_IsOpenPauseUI') then mgr:call('requestResumeMovie') end
            return block
        end
    end)
    for _,name in ipairs({'doUpdateFinish','doOnDestroy','requestCancel'}) do
        hook(player,name,function(a)
            local k=owner('movie',sdk.to_int64(a[2]))
            state:finish(k); bound_movies[k]=nil
        end)
    end
    for _,entry in ipairs(queue) do
        sdk.hook(entry[1],function(a)
            if armed and (state.scope or state.link) then
                local ok,result=pcall(entry[2],a)
                if ok then return result or original end
                log.error('RE2_COOP_CUTSCENE '..tostring(result))
            end
            return original
        end,function(retval)
            if armed and entry[3] then
                local ok,err=pcall(entry[3],retval)
                if not ok then log.error('RE2_COOP_CUTSCENE '..tostring(err)) end
            end
            return retval
        end)
    end
    armed=true
end
local ok,err=pcall(install)
if not ok then log.error('RE2_COOP_CUTSCENE unavailable: '..tostring(err)); return end

local function read(path)
    local ok,bytes=pcall(fs.read,path)
    if ok and type(bytes)=='string' and #bytes>0 and #bytes<=8192 then
        local decoded,d=pcall(json.load_string,bytes)
        if decoded and type(d)=='table' then return d end
    end
end
local real,last_read,last_sent,last_at
local down={}
local function pressed(vk)
    local now=reframework:is_key_down(vk)
    local edge=now and down[vk]==false
    down[vk]=now
    return edge
end
local function overlay(s)
    local peer=state:peer()
    local simulated=state.scope.simulated
    local label=simulated and 'Simulierter Gast' or 'Koop'
    local lines={label..'  |  '..s.event..'  # '..s.occurrence}
    if s.phase=='waiting' then
        lines[#lines+1]=state.link and 'Warte auf den zweiten Spieler ...' or 'Verbindung unterbrochen. Warte auf den Partner ...'
    elseif state:incoming() then
        lines[#lines+1]='Partner möchte überspringen.  F7 Ja   /   F8 Nein'
    elseif state:authorized() or state.applied then lines[#lines+1]='Beide haben dem Überspringen zugestimmt.'
    elseif s.decision=='request' and not (peer and peer.vote==s.vote and peer.decision=='decline') then
        lines[#lines+1]='Überspringen angefragt. Warte auf die Antwort ...'
    elseif s.decision=='decline' or peer and peer.vote==s.vote and peer.decision=='decline' then
        lines[#lines+1]='Abgelehnt. Die Szene läuft weiter.  F6 Erneut anfragen'
    else lines[#lines+1]='F6  Überspringen anfragen' end
    if simulated then lines[#lines+1]='Gast steuern:  F2 Ankommen / Ja     F3 Nein     F4 Skip anfragen' end
    local layer=imgui.get_foreground_draw_list()
    local size=imgui.get_display_size()
    local x,y=20,math.max(12,size.y-70-#lines*20)
    local width=0
    for _,line in ipairs(lines) do width=math.max(width,imgui.calc_text_size(line).x) end
    layer:add_rect_filled({x,y},{x+width+24,y+#lines*20+15},0xDF191919,6,0)
    for i,line in ipairs(lines) do layer:add_text({x+12,y+7+(i-1)*20},0xFFFFFFFF,line) end
end
re.on_frame(function()
    local now,clock=os.time(),os.clock()
    if not last_read or clock<last_read or clock-last_read>=0.10 then
        last_read=clock
        real=read('re2_coop_cutscene_peer.json')
        if model.document(real,now,false) then
            local guard=read('re2_coop_native_save_guard.json')
            if not guard or guard.source~='steam_storage_guard' or guard.active~=true
                or guard.game_pid~=real.game_pid or type(guard.at)~='number' or now<guard.at or now-guard.at>3 then real=nil end
        else real=nil end
    end
    if real and not model.document(real,now,false) then real=nil end
    local doc=real
    if has_sim then
        local polled,test=pcall(sim.poll,real~=nil)
        if not real and polled and model.document(test,now,true) then doc=test end
    end
    local generation=state.counts
    state:connect(doc)
    if state.counts~=generation then
        bound_movies,camera_infos,pending_by_thread={},{},{}
        last_sent=nil
    end
    local request,yes,no=pressed(0x75),pressed(0x76),pressed(0x77)
    local s=state.scene
    if not s then return end
    if yes~=no and state:incoming() then state:answer(yes)
    elseif request and not yes and not no then state:request() end
    if s.phase~='ended' then overlay(s) end
    if not doc then return end
    local stamp=table.concat({s.event,s.occurrence,s.phase,s.vote,s.decision},'/')
    if stamp~=last_sent or now~=last_at then
        local record=state:record()
        record.schema,record.game_pid,record.attempt_id,record.at=1,doc.game_pid,doc.attempt_id,now
        local wrote,result
        if doc.simulated then wrote,result=pcall(sim.publish,record)
        else wrote,result=pcall(json.dump_file,'re2_coop_cutscene_local.json',record) end
        if wrote and result~=false then
            if stamp~=last_sent then log.info('RE2_COOP_CUTSCENE '..stamp) end
            last_sent,last_at=stamp,now
        end
    end
end)
