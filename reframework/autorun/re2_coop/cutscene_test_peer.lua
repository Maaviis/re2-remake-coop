-- A local visual test in an empty, protected host lobby. No writes to Steam or its receipts.
local M = {}
local request_file = 're2_coop_solo_request.json'
local status_file = 're2_coop_solo_status.json'
local bridge_lobby
local function document(name)
    local ok, bytes = pcall(fs.read, name)
    if not ok or type(bytes) ~= 'string' or #bytes == 0 then return nil,true end
    if #bytes > 65536 then return end
    local decoded, value = pcall(json.load_string, bytes)
    if decoded and type(value) == 'table' and value.schema == 1 then return value end
end
local function recent(at, seconds)
    local now = os.time()
    return math.type(at) == 'integer' and at <= now and now-at <= seconds
end
local function token(s)
    return type(s)=='string' and #s==32 and s:match('^[0-9a-f]+$') ~= nil
end
local function native_started(phase)
    return phase=='loading' or phase=='scene_loaded'
end
local function scope(lobby, owner_guard, guard_run_id, started)
    local read_lobby
    if not lobby then
        local unreadable
        read_lobby,unreadable=document('re2_coop_lobby.json')
        -- A single file-read collision during publication must not revoke a
        -- solo start if a new read confirms the exact live lobby and mount.
        if unreadable then read_lobby,unreadable=document('re2_coop_lobby.json') end
        if not unreadable then bridge_lobby=nil end
        -- After native title finalization, an unreadable bridge sample can
        -- use the rest of its existing lease. Recheck Steam and the mount.
        lobby=read_lobby or (started and unreadable and bridge_lobby)
    end
    if not lobby or not recent(lobby.written_at,3) then return nil,'solo_lobby_stale' end
    if lobby.role ~= 'H' or lobby.connected ~= false or lobby.steam_lobby ~= 'owned' then return nil,'solo_lobby_changed' end
    local member = lobby.steam_membership
    if not member or type(member.session_id) ~= 'string' or member.session_id == ''
        or math.type(member.revision) ~= 'integer' or member.revision < 1 then return nil,'solo_lobby_changed' end
    local peer = document('re2_coop_native_peer.json')
    if not peer or not recent(peer.at,2) then return nil,'solo_native_peer_stale' end
    if peer.game_pid ~= lobby.game_pid or math.type(peer.game_pid) ~= 'integer' or peer.game_pid < 1
        or peer.role ~= '-' or peer.snapshot_epoch ~= '' or peer.solo_host ~= true
        or peer.revision ~= member.revision then return nil,'solo_membership_changed' end
    local protection
    if owner_guard then
        -- This VM owns the mount. Validate it directly, including the current
        -- native receipt and actual engine path, before each protected step.
        protection = owner_guard.protection.current
        if not protection or not protection.runtime or not owner_guard:campaign_ready(protection) then
            return nil,'solo_mount_lost'
        end
    else
        local guard = document('re2_coop_save_guard.json')
        protection = guard and guard.protection
        if not protection or not recent(guard.at,3) or guard.active ~= true or guard.runtime_protection ~= true
            or guard.protection_active ~= true or guard.campaign_mount_ready ~= protection.campaign_namespace then
            return nil,'solo_mount_lost'
        end
        guard_run_id = guard.guard_run_id
    end
    if protection.game_pid ~= peer.game_pid or not token(protection.run_id) or not token(protection.campaign_namespace)
        or type(guard_run_id) ~= 'string' or guard_run_id == '' then return nil,'solo_mount_lost' end
    if read_lobby then bridge_lobby=read_lobby end
    return {schema=1,game_pid=peer.game_pid,attempt_id=protection.campaign_namespace,run_id=protection.run_id,
        guard_run_id=guard_run_id,revision=member.revision,session_id=member.session_id}
end
local function same(a,b)
    return a and b and a.game_pid==b.game_pid and a.attempt_id==b.attempt_id and a.revision==b.revision
        and a.session_id==b.session_id and a.guard_run_id==b.guard_run_id and a.run_id==b.run_id
end
local next_request=0
function M.request_start(lobby)
    local value,reason=scope(lobby)
    if not value then return false,reason end
    value.at=os.time()
    next_request=next_request+1
    value.request_id=string.format('%d-%d-%.6f-%d',value.game_pid,value.at,os.clock(),next_request)
    local ok,result=pcall(json.dump_file,request_file,value)
    if not ok or result==false then return false,'solo_request_failed' end
    return true,value.request_id
end

-- Only the script that owns the native new-game driver may start this local run.
function M.launcher(guard,driver,loader,guard_run_id)
    local current, consumed, owns, next_check, last_report = nil,nil,false,0,nil
    local self={}
    local first_loss,failed_request
    function self:owns_start() return owns end
    function self:admitted()
        if not current then return false end
        local observed, reason=scope(nil,guard,guard_run_id,native_started(loader.phase))
        if same(current,observed) then first_loss=nil; return true end
        first_loss=first_loss or reason or 'solo_scope_changed'
        return false
    end
    function self:update()
        -- A native title reset may close and reopen the same menu between
        -- status writes. Observe it on game ticks until recovery is confirmed.
        local retryable=false
        if owns and loader.phase=='failed' then
            retryable=(failed_request and failed_request.retryable) or driver:recoverable()
        end
        if os.clock()<next_check then return end
        next_check=os.clock()+(current and 0.20 or 0.35)
        if not current then
            if not driver then return end
            if failed_request and retryable and not failed_request.retryable then
                failed_request.retryable,failed_request.at=true,os.time()
                json.dump_file(status_file,failed_request)
            end
            if (owns or loader.new_game) and not retryable then return end
            local request=document(request_file)
            if not request or not recent(request.at,4) or request.guard_run_id~=guard_run_id
                or type(request.request_id)~='string' or #request.request_id<1 or #request.request_id>96
                or request.request_id==consumed then return end
            consumed=request.request_id
            local observed,issue=scope(nil,guard,guard_run_id)
            local binding=guard.protection.current
            if not same(request,observed) then
                request.active,request.at,request.reason=false,os.time(),issue or 'solo_scope_changed'
                request.retryable=not owns or retryable
                json.dump_file(status_file,request)
                return
            end
            if retryable then
                if not driver:reset_failed() then return end
                owns,failed_request=false,nil
            end
            local ok,reason=driver:start({scenario='LEON_A',difficulty='NORMAL'},request.attempt_id,binding)
            if not ok then
                request.active,request.at,request.reason=false,os.time(),reason or 'new_game_title_not_ready'
                owns=loader.phase=='failed'
                request.retryable=not owns
                failed_request=request
                json.dump_file(status_file,request)
                log.info('RE2_COOP_SOLO start blocked: '..request.reason)
                return
            end
            owns,current,first_loss=true,request,nil
        end
        if not self:admitted() or loader.phase=='failed' then
            current.active,current.at,current.reason=false,os.time(),first_loss or (loader.phase=='failed' and loader.error) or 'solo_scope_changed'
            current.retryable=false
            failed_request=current
            json.dump_file(status_file,current)
            log.info('RE2_COOP_SOLO ended: '..current.reason)
            current=nil
            return
        end
        local started=native_started(loader.phase)
        if last_report~=os.time() or current.native_started~=started then
            last_report=os.time()
            current.active,current.at,current.native_started=true,last_report,started
            json.dump_file(status_file,current)
        end
    end
    return self
end

local cached, reported, next_read = nil,nil,0
local function live()
    if os.clock()<next_read then return cached,reported end
    next_read=os.clock()+0.10
    cached=nil
    reported=document(status_file)
    if reported and reported.active==true and recent(reported.at,2)
        and same(reported,scope(nil,nil,nil,reported.native_started==true)) then cached=reported end
    return cached,reported
end
function M.active() return live()~=nil end

local observation, simulated, attempt, arrived, active_scope
function M.preview_ready()
    local status = live()
    return status ~= nil and status.attempt_id == attempt and observation ~= nil and observation.phase == 'ended'
end
local held={}
local function pressed(key)
    local down=reframework:is_key_down(key)
    local edge=down and not held[key]
    held[key]=down
    return edge
end
function M.publish(value)
    if type(value)~='table' or value.attempt_id~=attempt then return end
    if not observation or observation.event~=value.event or observation.occurrence~=value.occurrence then
        arrived=false
        simulated={event=value.event,occurrence=value.occurrence,vote=0,decision='none',phase='waiting'}
    end
    observation={event=value.event,occurrence=value.occurrence,vote=value.vote,decision=value.decision,phase=value.phase}
end
function M.poll(real)
    if real then
        attempt,observation,simulated,arrived,active_scope=nil,nil,nil,false,nil
        return
    end
    local status,report=live()
    local yes,no,request=pressed(0x71),pressed(0x72),pressed(0x73)
    if not status then
        -- A missing receipt is not a terminal receipt. Preserve the occurrence
        -- during a read gap while suspending its synthetic arrivals and votes.
        if active_scope and report and report.active==false and same(report,active_scope)
            and report.request_id==active_scope.request_id and math.type(report.at)=='integer'
            and report.at>=active_scope.at and report.at<=os.time() then
            attempt,observation,simulated,arrived,active_scope=nil,nil,nil,false,nil
            return nil,true
        end
        return
    end
    active_scope=status
    if status.attempt_id~=attempt then
        attempt,observation,simulated,arrived=status.attempt_id,nil,nil,false
    end
    if observation then
        if observation.phase=='waiting' and yes then arrived=true end
        if arrived then
            simulated.phase=observation.phase
            if observation.phase=='playing' then
                if observation.decision=='request' and (yes or no) then
                    simulated.vote=observation.vote
                    simulated.decision=yes and 'accept' or 'decline'
                elseif request and observation.decision~='request' then
                    simulated.vote=math.max(simulated.vote,observation.vote)+1
                    simulated.decision='request'
                end
            end
        end
    end
    return {schema=1,game_pid=status.game_pid,attempt_id=attempt,role='H',at=os.time(),
        simulated=true,peer=arrived and simulated or nil}
end
return M
