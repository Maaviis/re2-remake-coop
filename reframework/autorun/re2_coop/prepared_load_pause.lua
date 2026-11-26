-- Hold an admitted prepared load in the owned native pause menu.
-- A held menu is not evidence that every world subsystem is frozen.
local M = {}
local transient = {gameplay_not_ready = true, pause_state_unavailable = true}
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
    assert(type(pause.poll) == 'function' and type(pause.request) == 'function', 'invalid_native_pause_dependency')
    local clock = options.clock or os.time
    local self = {phase = 'idle', reason = '', available = false}
    local bound, retired, count = nil, {}, 0

    local function guard_matches()
        if not bound or not guard.protection:matches(bound.protection)
            or guard.active ~= true or guard.hook_count ~= 26 or guard.denied_loads ~= 0
            or type(guard.writes) ~= 'table' or next(guard.writes) ~= nil
            or type(guard.policy) ~= 'table' then return false end
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
        if data.connected ~= true or data.save_slot ~= 'scenario:' .. bound.reference.slot_id
            or type(check) ~= 'table' or check.attempt_id ~= bound.scope.attempt_id
            or check.revision ~= bound.scope.revision or check.save_digest ~= bound.scope.save_digest
            or (check.phase ~= 'prepared' and check.phase ~= 'starting'
                and not (check.phase == 'failed' and transition[check.reason])) then return false end
        local selected = data.save_ref
        if type(selected) ~= 'table' then return false end
        if selected.available == true then
            for key, value in pairs(bound.reference) do if selected[key] ~= value then return false end end
        elseif selected.available ~= false then return false end
        return true
    end

    function self:in_progress()
        return bound ~= nil
    end
    function self:arm(id, scope, reference)
        if bound then return false, 'load_pause_in_progress' end
        if not token(id, 32) or retired[id] or count >= 256 or type(scope) ~= 'table'
            or scope.guard_run_id ~= guard_run_id or not integer(scope.game_pid, 1, 0xffffffff)
            or (scope.role ~= 'H' and scope.role ~= 'G') or type(scope.session_id) ~= 'string' or scope.session_id == ''
            or not integer(scope.revision, 0, 9007199254740991) or not token(scope.attempt_id, 32)
            or not token(scope.save_digest, 64) or type(scope.membership) ~= 'table'
            or not token(scope.membership.session_id, 32) or not integer(scope.membership.revision, 1, 0xffffffff)
            or type(reference) ~= 'table' or reference.mode ~= 1 or not integer(reference.slot_id, 0, 20)
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
            reference={mode=reference.mode, slot_id=math.tointeger(reference.slot_id),
                timestamp=reference.timestamp, scenario=reference.scenario},
            protection={game_pid=guard.protection.current.game_pid, run_id=guard.protection.current.run_id}}
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
    function self:poll(status)
        self.available = false
        if not bound then return false end
        local now = clock()
        if loader.request_id ~= bound.id or loader.phase == 'failed' then
            self.reason = 'native_load_changed'
            return false -- Never release an owned pause on a lost load or link.
        end
        local context = guard_matches() and context_matches(status, now)
        local ok = pcall(pause.poll, pause)
        if not ok then self.reason = 'native_pause_poll_failed'; return false end
        if self.phase == 'waiting_for_scene' and (loader.phase == 'loading' or loader.phase == 'scene_loaded') then
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
    function self:snapshot()
        return {schema = 1, scope = 'prepared_load_native_pause', observed_at = clock(),
            load_request_id = bound and bound.id or '', guard_run_id = guard_run_id,
            pause_id = pause.request_id or '', native_phase = pause.phase,
            phase = self.phase, available = self.available, reason = self.reason}
    end
    return self
end
return M
