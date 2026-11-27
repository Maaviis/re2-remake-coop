-- TDB70 story playback. Hold only the retryable start of an identified camera performance
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
local apply_camera_skip
local queued_camera, failed_skip_scene, menu_retry_scene
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
    local start=value(tl_state,'PlayStart')
    local pause_wait=value(timeline..'.CameraEventPauseState','Wait')
    local kick=value(player..'.Phase','Kick')
    local request=value(player..'.Phase','Request')
    local movie_play=value(player..'.Phase','Play')
    local function owned(k) return state.owners[k]==true end
    local function intercept(k)
        if not owned(k) or state.applied then return end
        return block
    end
    local function menu_skip()
        local s=state.scene
        if failed_skip_scene==s and state:authorized() then
            menu_retry_scene=s
            return
        end
        local previous_vote,previous_decision=s.vote,s.decision
        state:menu_skip()
        if s.vote~=previous_vote or s.decision~=previous_decision then
            log.info(('RE2_COOP_CUTSCENE menu %s/%d/%d/%s'):format(s.event,s.occurrence,s.vote,s.decision))
        end
    end
    local function apply(obj,target)
        -- Consent belongs to this occurrence. Allow the engine's downstream
        -- skip calls even if the event manager dispatches them on a later tick.
        local scene, previously_applied=state.scene,state.applied
        state.applied=true
        local ok,err=pcall(obj.call,obj,target)
        if ok then
            log.info('RE2_COOP_CUTSCENE native skip requested: '..target)
        else
            if state.scene==scene then
                state.applied=previously_applied
                failed_skip_scene=scene
            end
            log.error('RE2_COOP_CUTSCENE native skip: '..tostring(err))
        end
        return ok
    end
    local function current_camera(mgr)
        local info=mgr:get_field('_ActiveCameraEventInfo')
        local current=address(info)
        if current then
            for k,saved in pairs(camera_infos) do
                if current==saved and owned(k) then return info,k end
            end
        end
    end

    -- TimelineContents.update retries playStart while the performance is in PlayStart.
    -- The independent late update prepares fades, actors and the camera in PreStart.
    hook(performance,'playStart',function(a)
        local k=owner('timeline',sdk.to_int64(a[2]))
        if not state:track_new() and not owned(k) and not state.deferred[k] then return end
        local obj=sdk.to_managed_object(a[2])
        if obj:call('get_State')~=start then return end
        local info=obj:call('get_CurrentEventInfo')
        if not info or info:call('get_IsCameraEvent')~=true then return end
        local event=known[info:call('get_ID')]
        if not event then return end
        local admitted=state:admit(event,k)
        if owned(k) then camera_infos[k]=address(info) end
        if not admitted then return block end
    end)
    apply_camera_skip=function(retry)
        if queued_camera and queued_camera.scene~=state.scene then queued_camera=nil end
        if failed_skip_scene and failed_skip_scene==state.scene then return end
        if not next(camera_infos) or (not queued_camera and (state.applied or not state:authorized())) then return end
        local mgr=sdk.get_managed_singleton(timeline)
        if not mgr or mgr:call('get_CameraEventPlay')~=true then return end
        local info,k=current_camera(mgr)
        if not info then return end
        if not queued_camera then
            -- Use the same deferred camera/fade/audio path as RE2's skip menu.
            -- A native call may start the request and still fail at the Lua boundary.
            local already_requested=retry and mgr:get_field('_SkipEvent')==true
            if already_requested or (mgr:call('get_CameraEventEnableSkip')==true and apply(mgr,'skipEventPauseUI')) then
                state.applied=true
                queued_camera={scene=state.scene,info=address(info)}
            end
            return
        end
        if queued_camera.info~=address(info) or state.scene.phase~='playing' then return end
        if info:call('get_Skiped')==true then queued_camera=nil; return end
        -- EV011 can complete the native audio cycle and return to Wait while
        -- leaving the matching contents paused. Finish the queued operation
        -- through the same per-contents function used by native resumeEvent.
        if mgr:get_field('_CurrentPauseState')~=pause_wait or mgr:get_field('_ExecPause')~=false
            or mgr:get_field('_PauseEvent')~=true or mgr:get_field('_SkipEvent')~=true
            or mgr:get_field('_WwiseRequestExecEnd')~=true then return end
        local list=mgr:call('get_ActivateContentsList')
        local count=list and list:get_size() or 0
        if count>64 then return end
        for i=0,count-1 do
            local content=list:get_element(i)
            local performance_object=content and content:call('get_Performance')
            if performance_object and owner('timeline',address(performance_object))==k
                and address(performance_object:call('get_CurrentEventInfo'))==queued_camera.info
                and known[content:call('get_EventID')]==state.scene.event and content:call('get_IsPause')==true then
                if apply(content,'skip') then queued_camera=nil end
                return
            end
        end
    end
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
        if not next(camera_infos) or state.applied then return end
        local mgr=sdk.to_managed_object(a[2])
        if current_camera(mgr) then
            menu_skip()
            mgr:call('resumeEventPauseUI')
            return block
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
        if state:track_new() then
            call.event=known[sdk.to_int64(a[5]) & 0xffffffff]
            call.source=sdk.to_int64(a[3])
        end
    end,function(retval)
        local call=thread.get_hook_storage().re2_scene_movie
        if call then
            pending_by_thread[thread.get_id()]=call.previous
            if call.event and call.generation==state.counts and (sdk.to_int64(retval) & 0xff)==1 then
                if not next(call.targets) and call.source~=0 then call.targets[call.source]=true end
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
        elseif phase==movie_play and owned(k) and not state.applied and failed_skip_scene~=state.scene and state:authorized()
            and obj:call('isEnablePause')==true then
            apply(obj,'requestSkip')
        end
    end)
    hook(player,'requestSkip',function(a) return intercept(owner('movie',sdk.to_int64(a[2]))) end)
    hook(movies,'requestSkipMovie',function(a)
        if not next(bound_movies) or state.applied then return end
        local mgr=sdk.to_managed_object(a[2])
        local active=mgr:get_field('_StaticPlayer')
        if active and owned(owner('movie',address(active))) then
            if mgr:get_field('_IsOpenPauseUI') or mgr:get_field('_ExecPause') then
                menu_skip()
                mgr:call('requestResumeMovie')
            end
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
local real, real_binding, native_guard, last_read, last_sent, last_at
local stopped_attempt, last_release_check, last_peer_state
local function guard_is_current(guard, pid, now)
    return guard and guard.source=='steam_storage_guard' and guard.active==true and guard.game_pid==pid
        and type(guard.at)=='number' and now>=guard.at and now-guard.at<=3
end
local function token(value)
    return type(value)=='string' and #value==32 and value:match('^[0-9a-f]+$')~=nil
end
local function same_guard(guard, binding)
    return guard.run_id==binding.run_id and guard.campaign_namespace==binding.campaign_namespace
end
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
    local guest_help
    if stopped_attempt==state.scope.attempt_id and not simulated then
        lines[#lines+1]='Kampagne angehalten. Beide Spieler müssen RE2 neu starten.'
    elseif s.phase=='waiting' then
        lines[#lines+1]=state.link and 'Warte auf den zweiten Spieler ...' or 'Verbindung unterbrochen. Warte auf den Partner ...'
        guest_help='F2 Gast ankommen lassen'
    elseif state:incoming() then
        lines[#lines+1]='Partner möchte überspringen. Esc → Überspringen → Leertaste: Ja   /   F8: Nein'
    elseif failed_skip_scene==s then
        lines[#lines+1]=state:authorized() and 'RE2 konnte die Szene nicht überspringen.  Esc → Überspringen oder F6 Erneut versuchen'
            or 'RE2 konnte die Szene nicht überspringen.  Warte auf gültige Zustimmung …'
    elseif state:authorized() or state.applied then lines[#lines+1]='Beide haben dem Überspringen zugestimmt.'
    elseif s.decision=='request' and not (peer and peer.vote==s.vote and peer.decision=='decline') then
        lines[#lines+1]='Überspringen angefragt. Warte auf die Antwort ...'
        guest_help='Gast antwortet:  F2 Ja  /  F3 Nein'
    elseif s.decision=='decline' or peer and peer.vote==s.vote and peer.decision=='decline' then
        lines[#lines+1]='Abgelehnt. Die Szene läuft weiter.  Esc → Überspringen: erneut anfragen'
        guest_help='F4 Gast fragt Überspringen an'
    else
        lines[#lines+1]='Esc → Überspringen → Leertaste: Partner fragen'
        guest_help='F4 Gast fragt Überspringen an'
    end
    local replay_hint=simulated and sim.replay_hint and sim.replay_hint()
    if replay_hint then lines[#lines+1]='Replay · '..replay_hint..' · F10 beenden'
    elseif simulated and guest_help then lines[#lines+1]=guest_help end
    local layer=imgui.get_foreground_draw_list()
    local size=imgui.get_display_size()
    local x,y=20,math.max(12,size.y-70-#lines*20)
    local width=0
    for _,line in ipairs(lines) do width=math.max(width,imgui.calc_text_size(line).x) end
    layer:add_rect_filled({x,y},{x+width+24,y+#lines*20+15},0xDF191919,6,0)
    for i,line in ipairs(lines) do layer:add_text({x+12,y+7+(i-1)*20},0xFFFFFFFF,line) end
end
re.on_pre_application_entry('UpdateBehavior',function()
    local clock=os.clock()
    if not last_read or clock<last_read or clock-last_read>=0.10 then
        last_read=clock
        local received=read('re2_coop_cutscene_peer.json')
        real=nil
        native_guard=(received or real_binding) and read('re2_coop_native_save_guard.json')
        local now=os.time()
        if model.document(received,now,false) and guard_is_current(native_guard,received.game_pid,now) then
            local same_attempt=real_binding and real_binding.attempt_id==received.attempt_id
                and real_binding.game_pid==received.game_pid and real_binding.role==received.role
            if not same_attempt or same_guard(native_guard,real_binding) then
                real=received
                real_binding=nil
                if token(native_guard.run_id) and token(native_guard.campaign_namespace) then
                    real_binding={game_pid=received.game_pid,attempt_id=received.attempt_id,role=received.role,
                        run_id=native_guard.run_id,campaign_namespace=native_guard.campaign_namespace}
                end
            end
        end
    end
    if real and not model.document(real,os.time(),false) then real=nil end
    local doc=real
    local simulation_ended=false
    if has_sim then
        local polled,test,ended=pcall(sim.poll,real~=nil)
        -- The local simulator stamps its response during poll. The wall clock
        -- may advance while a receipt is being read or produced.
        if not real and polled and model.document(test,os.time(),true) then doc=test end
        simulation_ended=not real and polled and ended==true
    end
    local generation=state.counts
    -- A matching local save namespace keeps the camera gate available during
    -- a peer read gap. It cannot count as the partner's arrival or vote.
    local local_campaign=real_binding and guard_is_current(native_guard,real_binding.game_pid,os.time())
        and same_guard(native_guard,real_binding)
    state:connect(doc,simulation_ended,local_campaign)
    local scope=state.scope
    if not doc and scope and not scope.simulated and state.scene and stopped_attempt~=scope.attempt_id
        and last_release_check~=os.time() then
        last_release_check=os.time()
        local report=read('re2_coop_campaign_release_status.json')
        if report and report.schema==1 and report.game_pid==scope.game_pid and report.role==scope.role
            and report.attempt_id==scope.attempt_id and type(report.transitions)=='table' then
            local last=report.transitions[#report.transitions]
            if type(last)=='table' and last.phase=='failed' then stopped_attempt=scope.attempt_id end
        end
    end
    if state.counts~=generation then
        bound_movies,camera_infos,pending_by_thread={},{},{}
        queued_camera,failed_skip_scene=nil,nil
        last_sent,last_peer_state=nil,nil
    end
    local request,yes,no=pressed(0x75),pressed(0x76),pressed(0x77)
    local s=state.scene
    if not s then return end
    if doc and not doc.simulated then
        local peer=doc.peer
        if model.valid_peer(peer) then
            local summary=table.concat({peer.event,peer.occurrence,peer.phase,peer.vote,peer.decision},'/')
            if summary~=last_peer_state then log.info('RE2_COOP_CUTSCENE peer '..summary); last_peer_state=summary end
        end
    end
    local retry=false
    if yes~=no and state:incoming() then state:answer(yes)
    elseif (request or menu_retry_scene==s) and not yes and not no then
        if failed_skip_scene==s and state:authorized() then failed_skip_scene,retry=nil,true
        elseif request then state:request() end
    end
    menu_retry_scene=nil
    local applied,error_message=pcall(apply_camera_skip,retry)
    if not applied then log.error('RE2_COOP_CUTSCENE camera skip: '..tostring(error_message)) end
    if not doc then return end
    local now=os.time()
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

local hud_failed=false
re.on_frame(function()
    local scene=state.scene
    if not scene or scene.phase=='ended' then return end
    local drawn,err=pcall(overlay,scene)
    if not drawn and not hud_failed then log.warn('RE2_COOP_CUTSCENE HUD: '..tostring(err)) end
    hud_failed=not drawn
end)
