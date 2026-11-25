-- A local visual test in an empty, protected host lobby. No writes to Steam or its receipts.
local M = {}
local request_file = 're2_coop_solo_request.json'
local status_file = 're2_coop_solo_status.json'
local function document(name)
    local ok, bytes = pcall(fs.read, name)
    if not ok or type(bytes) ~= 'string' or #bytes == 0 or #bytes > 65536 then return end
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
local function scope(lobby)
    lobby = lobby or document('re2_coop_lobby.json')
    if not lobby or lobby.role ~= 'H' or lobby.connected ~= false or lobby.steam_lobby ~= 'owned'
        or not recent(lobby.written_at,3) then return end
    local member = lobby.steam_membership
    if not member or type(member.session_id) ~= 'string' or member.session_id == ''
        or math.type(member.revision) ~= 'integer' or member.revision < 1 then return end
    local peer = document('re2_coop_native_peer.json')
    if not peer or peer.game_pid ~= lobby.game_pid or math.type(peer.game_pid) ~= 'integer'
        or peer.game_pid < 1 or not recent(peer.at,2) or peer.role ~= '-' or peer.snapshot_epoch ~= ''
        or peer.solo_host ~= true or peer.revision ~= member.revision then return end
    local guard = document('re2_coop_save_guard.json')
    local protection = guard and guard.protection
    if not protection or not recent(guard.at,3) or guard.active ~= true or guard.runtime_protection ~= true
        or guard.protection_active ~= true or protection.game_pid ~= peer.game_pid or not token(protection.run_id)
        or not token(protection.campaign_namespace) or guard.campaign_mount_ready ~= protection.campaign_namespace
        or type(guard.guard_run_id) ~= 'string' or guard.guard_run_id == '' then return end
    return {schema=1,game_pid=peer.game_pid,attempt_id=protection.campaign_namespace,run_id=protection.run_id,
        guard_run_id=guard.guard_run_id,revision=member.revision,session_id=member.session_id}
end
local function same(a,b)
    return a and b and a.game_pid==b.game_pid and a.attempt_id==b.attempt_id and a.revision==b.revision
        and a.session_id==b.session_id and a.guard_run_id==b.guard_run_id and a.run_id==b.run_id
end
function M.request_start(lobby)
    local value=scope(lobby)
    if not value then return false end
    value.at=os.time()
    return json.dump_file(request_file,value) ~= false
end

-- Only the script that owns the native new-game driver may start this local run.
function M.launcher(guard,driver,loader,guard_run_id)
    local current, consumed, owns, next_check, last_report = nil,nil,false,0,nil
    local self={}
    function self:owns_start() return owns end
    function self:admitted()
        return current~=nil and same(current,scope()) and guard:campaign_ready(guard.protection.current)
    end
    function self:update()
        if os.clock()<next_check then return end
        next_check=os.clock()+(current and 0.20 or 0.35)
        if not current then
            if owns or not driver or loader.new_game then return end
            local request=document(request_file)
            if not request or not recent(request.at,4) or request.guard_run_id~=guard_run_id
                or request.attempt_id==consumed or not same(request,scope()) then return end
            local binding=guard.protection.current
            if not binding or binding.campaign_namespace~=request.attempt_id or not guard:campaign_ready(binding) then return end
            consumed=request.attempt_id
            local ok,reason=driver:start({scenario='LEON_A',difficulty='NORMAL'},request.attempt_id,binding)
            if not ok then
                request.active,request.at,request.reason=false,os.time(),reason or 'new_game_title_not_ready'
                json.dump_file(status_file,request)
                log.info('RE2_COOP_SOLO start blocked: '..request.reason)
                return
            end
            owns,current=true,request
        end
        if not self:admitted() or loader.phase=='failed' then
            current.active,current.at,current.reason=false,os.time(),loader.phase=='failed' and loader.error or 'solo_scope_lost'
            json.dump_file(status_file,current)
            log.info('RE2_COOP_SOLO ended: '..current.reason)
            current=nil
            return
        end
        if last_report~=os.time() then
            last_report=os.time()
            current.active,current.at=true,last_report
            json.dump_file(status_file,current)
        end
    end
    return self
end

local cached, next_read = nil,0
local function live()
    if os.clock()<next_read then return cached end
    next_read=os.clock()+0.10
    cached=nil
    local status=document(status_file)
    if status and status.active==true and recent(status.at,2) and same(status,scope()) then cached=status end
    return cached
end
function M.active() return live()~=nil end

local observation, simulated, attempt, arrived
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
    local status=not real and live()
    if not status then
        attempt,observation,simulated,arrived=nil,nil,nil,false
        return
    end
    if status.attempt_id~=attempt then
        attempt,observation,simulated,arrived=status.attempt_id,nil,nil,false
    end
    local yes,no,request=pressed(0x71),pressed(0x72),pressed(0x73)
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
