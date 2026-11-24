-- Hold an admitted prepared load in the owned native pause menu.
-- A held menu is not evidence that every world subsystem is frozen.
local M = {}
local transient = {gameplay_not_ready = true, pause_state_unavailable = true}
local rehold_timeout = 3
local peer_start_timeout, peer_release_timeout = 10, 4
local transition = {selection_changed = true, local_source_unavailable = true,
    guest_source_unavailable = true, guest_ack_expired = true, start_window_expired = true}
local function token(value, length)
    return type(value) == 'string' and #value == length and value:match('^[0-9a-f]+$') ~= nil
end
local function integer(value, low, high)
    return type(value) == 'number' and value % 1 == 0 and value >= low and value <= high
end

function M.new(guard, loader, guard_run_id, options)
    assert(type(guard_run_id) == 'string' and #guard_run_id > 0 and #guard_run_id <= 128, 'invalid_guard_run_id')
    options = options or {}
    -- REFramework resolves script modules at startup; do not require one later
    -- from a native update callback. The owning script supplies its instance.
    local pause = assert(options.pause, 'native_pause_dependency_required')
    assert(type(pause.poll) == 'function' and type(pause.request) == 'function'
        and type(pause.release) == 'function' and type(pause.rehold) == 'function', 'invalid_native_pause_dependency')
    local clock = options.clock or os.time
    local self = {phase = 'idle', reason = '', available = false}
    local bound, retired, count = nil, {}, 0
    local released_epoch, release_id, released_at, peer_release_at, link_lost, rehold_deadline, interrupted_at
    local release_loss_reason

    local function protection_matches()
        return guard.protection:matches(bound.protection) and (not bound.protection.campaign_namespace
            or guard:campaign_ready(bound.protection,true))
    end
    local function guard_matches()
        if not bound or not protection_matches()
            or guard.active ~= true or guard.hook_count ~= 26 or guard.denied_loads ~= 0
            or type(guard.writes) ~= 'table' then return false end
        if bound.new_game then
            return guard.policy == nil and guard.allowed_load_calls == 0
                and loader.new_game ~= nil and loader.new_game.scenario == bound.new_game.scenario
                and loader.new_game.difficulty == bound.new_game.difficulty
        end
        if type(guard.policy) ~= 'table' then return false end
        for key, value in pairs(bound.reference) do
            if guard.policy[key] ~= value then return false end
        end
        return true
    end
    local function context_matches(status, now)
        if type(status) ~= 'table' or status.schema ~= 1 or not integer(status.written_at, 0, math.maxinteger)
            or now < status.written_at or now - status.written_at > 3 or status.connected ~= true
            or status.game_pid ~= bound.scope.game_pid or status.role ~= bound.scope.role
            or (status.role == 'H' and status.steam_lobby ~= 'owned')
            or (status.role == 'G' and status.steam_lobby ~= 'joined') then return false end
        local member, message = status.steam_membership, status.lobby
        if type(member) ~= 'table' or member.session_id ~= bound.scope.membership.session_id
            or member.revision ~= bound.scope.membership.revision or type(message) ~= 'table'
            or message.version ~= 1 or message.type ~= 'lobby_state'
            or message.session_id ~= bound.scope.session_id or type(message.data) ~= 'table' then return false end
        local data = message.data
        local check = data.load_check
        if data.connected ~= true
            or type(check) ~= 'table' or check.attempt_id ~= bound.scope.attempt_id
            or check.revision ~= bound.scope.revision or check.save_digest ~= bound.scope.save_digest
            or (check.phase ~= 'prepared' and check.phase ~= 'starting'
                and not (check.phase == 'failed' and transition[check.reason])) then return false end
        if bound.new_game then
            return check.campaign_start == true and options.new_game.matches(data,bound.new_game)
                and data.revision == bound.scope.revision and type(data.ready) == 'table'
                and data.host_id ~= data.guest_id and data.ready[data.host_id] == true and data.ready[data.guest_id] == true
                and (check.phase == 'starting' or check.phase == 'failed' and check.reason == 'start_window_expired')
        end
        if data.new_game ~= nil or data.save_slot ~= 'scenario:' .. bound.reference.slot_id then return false end
        local selected = data.save_ref
        if type(selected) ~= 'table' then return false end
        if selected.available == true then
            for key, value in pairs(bound.reference) do if selected[key] ~= value then return false end end
        elseif selected.available ~= false then return false end
        return true
    end
    local function peer_matches(peer, now, epoch)
        return type(peer) == 'table' and peer.schema == 1
            and integer(peer.at, 0, now) and now - peer.at <= 1
            and peer.game_pid == bound.scope.game_pid and peer.role == bound.scope.role
            and peer.revision == bound.scope.membership.revision and peer.snapshot_epoch == epoch
    end
    local function release_loss(now, evidence)
        if link_lost then return 'campaign_peer_lost' end
        if not protection_matches() then return 'campaign_protection_lost' end
        if peer_release_at and (now < peer_release_at or now - peer_release_at >= peer_release_timeout)
            or not peer_release_at and now - released_at >= peer_start_timeout then
            return 'campaign_peer_release_unconfirmed'
        end
        if type(evidence) == 'table' and evidence.schema == 1
            and integer(evidence.at, peer_release_at or released_at, now)
            and now - evidence.at < peer_release_timeout
            and evidence.game_pid == bound.scope.game_pid and evidence.load_request_id == bound.id
            and evidence.snapshot_epoch == released_epoch and evidence.release_id == release_id then
            peer_release_at = evidence.at
        end
    end
    local function poll_rehold(now)
        if loader.request_id ~= bound.id or loader.phase ~= 'scene_loaded' or loader.error ~= '' then
            self.phase, self.reason = 'rehold_failed', 'native_load_changed'
            return
        end
        if now >= rehold_deadline then
            self.phase, self.reason = 'rehold_failed', 'campaign_rehold_timeout'
            return
        end
        if self.phase == 'rehold_pending' then
            local called, accepted, reason = pcall(pause.rehold, pause, bound.id)
            if called and accepted then
                self.phase = 'reholding'
            elseif not called or not transient[reason] then
                self.phase = 'rehold_failed'
                self.reason = called and (reason or 'native_rehold_rejected') or 'native_rehold_call_failed'
            end
            return
        end
        local called, verified = pcall(pause.poll, pause)
        if called and verified and pause.phase == 'held' and pause.verified and pause.request_id == bound.id then
            self.phase, interrupted_at = 'interrupted', now
        elseif not called or pause.phase == 'lost' or pause.phase == 'failed' then
            self.phase = 'rehold_failed'
            self.reason = called and (pause.reason or 'native_pause_lost') or 'native_pause_poll_failed'
        end
    end

    function self:in_progress()
        return bound ~= nil
    end
    function self:new_game_admitted(status)
        if not bound or not bound.new_game or not guard_matches() or not context_matches(status,clock()) then return false end
        local check = status.lobby.data.load_check
        if check.phase == 'failed' then return loader.phase == 'loading' end
        return check.reason == '' and type(check.start) == 'table' and check.start[bound.scope.role] == bound.id
    end
    function self:arm(id, scope, reference, new_game)
        if bound then return false, 'load_pause_in_progress' end
        if not token(id, 32) or retired[id] or count >= 256 or type(scope) ~= 'table'
            or scope.guard_run_id ~= guard_run_id or not integer(scope.game_pid, 1, 0xffffffff)
            or (scope.role ~= 'H' and scope.role ~= 'G') or type(scope.session_id) ~= 'string' or scope.session_id == ''
            or not integer(scope.revision, 0, 9007199254740991) or not token(scope.attempt_id, 32)
            or not token(scope.save_digest, 64) or type(scope.membership) ~= 'table'
            or not token(scope.membership.session_id, 32) or not integer(scope.membership.revision, 1, 0xffffffff)
            then return false, 'invalid_load_pause_binding' end
        if new_game ~= nil then
            if reference ~= nil or not options.new_game or not options.new_game.selection(new_game)
                or guard.policy ~= nil or guard.allowed_load_calls ~= 0 then return false, 'invalid_load_pause_binding' end
        elseif type(reference) ~= 'table' or reference.mode ~= 1 or not integer(reference.slot_id, 0, 20)
            or not integer(reference.scenario, 0, 3) or type(reference.timestamp) ~= 'string'
            or not reference.timestamp:match('^[0-9]+$') then return false, 'invalid_load_pause_binding' end
        if not guard.protection:ready() or guard.protection.current.game_pid ~= scope.game_pid then
            return false, 'protected_launch_required'
        end
        retired[id], count = true, count + 1
        bound = {id = id, scope = {game_pid=scope.game_pid, role=scope.role, session_id=scope.session_id,
            revision=scope.revision, attempt_id=scope.attempt_id, save_digest=scope.save_digest,
            guard_run_id=scope.guard_run_id,
            membership={session_id=scope.membership.session_id, revision=scope.membership.revision}},
            reference=reference and {mode=reference.mode, slot_id=math.tointeger(reference.slot_id),
                timestamp=reference.timestamp, scenario=reference.scenario},
            new_game=new_game and {scenario=new_game.scenario,difficulty=new_game.difficulty},
            scenario=reference and reference.scenario or options.new_game.scenario(new_game.scenario),
            protection={game_pid=guard.protection.current.game_pid, run_id=guard.protection.current.run_id,
                campaign_namespace=guard.protection.current.campaign_namespace}}
        self.phase, self.reason, self.available = 'waiting_for_scene', '', false
        return true
    end
    function self:cancel(id)
        if bound and bound.id == id and self.phase == 'waiting_for_scene' then
            bound = nil
            self.phase, self.reason, self.available = 'idle', '', false
            return true
        end
        return false
    end
    function self:poll(status, peer, peer_release)
        self.available = false
        if not bound or self.phase == 'resume_failed' or self.phase == 'rehold_failed' then return false end
        local now = clock()
        if self.phase == 'releasing' or self.phase == 'released' then
            -- Latch loss even while the native menu is still closing.
            link_lost = link_lost or not peer_matches(peer, now, released_epoch)
        end
        if self.phase == 'releasing' then
            local polled = pcall(pause.poll, pause)
            if polled and pause.phase == 'released' and pause.verified == true then
                self.phase, self.reason, released_at = 'released', 'campaign_peer_release_pending', now
            elseif polled and (pause.phase == 'lost' or pause.phase == 'failed') then
                self.phase, self.reason = 'resume_failed', pause.reason or 'native_pause_lost'
            end
            if self.phase ~= 'released' then return false end
        end
        if self.phase == 'released' then
            local reason = release_loss(now, peer_release)
            if not reason then
                if peer_release_at then self.reason = '' end
                return false
            end
            release_loss_reason = reason
            self.phase, self.reason = 'rehold_pending', reason
            rehold_deadline = now + rehold_timeout
        end
        if self.phase == 'rehold_pending' or self.phase == 'reholding' then
            poll_rehold(now)
            return false
        end
        if self.phase == 'interrupted' then
            local called, verified = pcall(pause.poll, pause)
            if not called or not verified or pause.phase ~= 'held' then
                self.phase, self.reason = 'rehold_failed', 'interrupted_pause_lost'
            end
            return false
        end
        if loader.request_id ~= bound.id or (loader.phase == 'failed' and not bound.new_game) then
            self.reason = 'native_load_changed'
            return false -- Never release an owned pause on a lost load or link.
        end
        local context = loader.phase ~= 'failed' and guard_matches() and next(guard.writes) == nil and context_matches(status, now)
        local ok = pcall(pause.poll, pause)
        if not ok then self.reason = 'native_pause_poll_failed'; return false end
        -- Setup may have taken effect even if a later call or protection check failed.
        -- In that case the native pause still catches an arriving player, with release disabled.
        if self.phase == 'waiting_for_scene' and (loader.phase == 'loading' or loader.phase == 'scene_loaded'
                or bound.new_game and loader.phase == 'failed') then
            local called, accepted, reason = pcall(pause.request, pause, bound.id)
            if called and accepted then self.phase = 'requesting'
            elseif not called or not transient[reason] then
                self.phase, self.reason = 'failed', called and (reason or 'native_pause_rejected') or 'native_pause_call_failed'
                return false
            end
        end
        if pause.phase == 'lost' or pause.phase == 'failed' then
            self.phase, self.reason = 'lost', pause.reason or 'native_pause_lost'
            return false
        end
        if pause.phase == 'held' and pause.verified == true and pause.request_id == bound.id then
            self.phase = 'held'
            self.available = context and loader.phase == 'scene_loaded' and loader.error == ''
        end
        self.reason = not context and 'prepared_load_context_unavailable'
            or self.available and '' or 'native_pause_pending'
        return self.available
    end
    function self:resume(status, command, peer)
        if self.phase ~= 'held' or type(command) ~= 'table' or command.schema ~= 1 then return false end
        local now = clock()
        local scope = command.lobby_load
        if not integer(command.at, 0, now) or now - command.at > 3 or command.load_request_id ~= bound.id
            or type(scope) ~= 'table' or type(scope.membership) ~= 'table' then return false end
        for _, key in ipairs({'game_pid', 'role', 'session_id', 'revision', 'attempt_id', 'save_digest', 'guard_run_id'}) do
            if scope[key] ~= bound.scope[key] then return false end
        end
        if scope.membership.session_id ~= bound.scope.membership.session_id
            or scope.membership.revision ~= bound.scope.membership.revision
            or not token(command.release_id, 32) or not token(command.snapshot_epoch, 16)
            or not peer_matches(peer, now, command.snapshot_epoch)
            or not self:poll(status) or status.lobby.data.load_check.campaign_start ~= true then return false end
        if bound.new_game then
            local expected = command.new_game_world
            if type(expected) ~= 'table' or type(options.read_world) ~= 'function' then return false end
            local valid, world = pcall(options.read_world)
            if not valid or not world or world.request_id ~= bound.id then return false end
            local keys = {scenario=true,difficulty=true,map=true,area=true}
            for key in pairs(expected) do if not keys[key] then return false end end
            for key in pairs(keys) do if expected[key] ~= world[key] then return false end end
        elseif command.new_game_world ~= nil then return false end
        self.phase, self.available = 'releasing', false
        local called, accepted, reason = pcall(pause.release, pause, bound.id)
        if not called or not accepted then
            self.phase, self.reason = 'resume_failed', called and (reason or 'native_pause_return_rejected')
                or 'native_pause_return_failed'
            return false
        end
        released_epoch, release_id = command.snapshot_epoch, command.release_id
        return true
    end
    function self:snapshot()
        local result = {schema = 1, scope = 'prepared_load_native_pause', observed_at = clock(),
            load_request_id = bound and bound.id or '', guard_run_id = guard_run_id,
            pause_id = pause.request_id or '', native_phase = pause.phase,
            phase = self.phase, available = self.available, reason = self.reason,
            release_loss_reason = release_loss_reason}
        if self.phase == 'released' and pause.phase == 'released' and released_epoch then
            result.release = {id = release_id, snapshot_epoch = released_epoch}
            if peer_release_at then
                local scope = bound.scope
                result.campaign = {session_id = scope.session_id, game_pid = scope.game_pid,
                    attempt_id = scope.attempt_id, scenario = bound.scenario,
                    role = scope.role, revision = scope.membership.revision, snapshot_epoch = released_epoch,
                    protection_run_id = bound.protection.run_id,
                    local_player = pause.released_player, local_scene = pause.released_scene}
            end
        end
        if self.phase == 'interrupted' and pause.phase == 'held' and pause.verified == true
            and pause.request_id == bound.id and guard_matches()
            and loader.request_id == bound.id and loader.phase == 'scene_loaded' and loader.error == ''
            and options.read_area then
            local called, area = pcall(options.read_area)
            local scope = bound.scope
            if called and type(area) == 'table' and area.scenario == bound.scenario
                and integer(area.map, 0, 0xffffffff) and integer(area.area, 0, 0xffffffff) then
                result.interruption = {session_id = scope.session_id, attempt_id = scope.attempt_id,
                    release_id = release_id, game_pid = scope.game_pid, role = scope.role,
                    protection_run_id = bound.protection.run_id, at = interrupted_at,
                    area = {scenario = area.scenario, map = area.map, area = area.area}}
            end
        end
        return result
    end
    return self
end
return M
