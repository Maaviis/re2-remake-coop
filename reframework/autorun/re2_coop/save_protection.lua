-- Local launch receipts; no game getters or I/O in ready()/matches().
local M = {}
local function integer(value, minimum)
    return type(value) == 'number' and value % 1 == 0 and value >= minimum
end
local function token(value)
    return type(value) == 'string' and #value == 32 and value:match('^[0-9a-f]+$') ~= nil
end

function M.new(options)
    options = options or {}
    local clock = options.clock or os.time
    local read = options.read or json.load_file
    local run_id = options.run_id
    if run_id == nil then
        -- REFramework's Lua sandbox does not promise os.getenv. The launcher
        -- generates this module before CreateProcess, with the same native token.
        local ok, value = pcall(require, 're2_coop.protected_launch_token')
        if ok then run_id = value end
    end
    local thread_id = options.thread_id or (thread and thread.get_id)
    local requested = (token(run_id) or options.runtime == true) and type(thread_id) == 'function'
    local self = {current = nil, requested = requested,
        reason = requested and 'waiting_for_receipts' or 'launch_identity_unavailable'}
    local challenge, challenge_thread, challenge_run
    local function valid(value, source, now)
        return type(value) == 'table' and value.schema == 1 and value.source == source
            and value.active == true and integer(value.at, 0) and now >= value.at and now - value.at <= 3
            and integer(value.game_pid, 1) and token(value.run_id)
            and value.app_id == 883710 and value.build_id == 11636119
    end
    function self:poll()
        self.current = nil
        if not requested then return false end
        self.reason = 'protection_receipt_invalid'
        local native_ok, native = pcall(read, 're2_coop_native_save_guard.json')
        local now = clock()
        local native_valid = native_ok and valid(native, 'steam_storage_guard', now)
            and native.reason == 'ok' and native.interface == '014' and native.guarded_methods == 10
        local active_run, launch_at = run_id, nil
        if native_valid and native.runtime_locked_files ~= nil then
            if not options.runtime or not integer(native.runtime_locked_files, 1)
                or native.runtime_locked_files > 128 then return false end
            active_run, launch_at = native.run_id, native.at
        end
        if not token(active_run) then return false end
        -- A token file can outlive RE2. The native plugin must acknowledge
        -- this Lua VM's challenge after checking the thread belongs to itself.
        local owner = thread_id()
        if not integer(owner, 1) or owner > 0xffffffff then return false end
        if owner ~= challenge_thread or challenge_run ~= active_run then
            local nonce = string.format('%08x:%08x%08x%08x%08x', owner, math.random(0, 0x7fffffff),
                math.random(0, 0x7fffffff), math.random(0, 0x7fffffff), math.random(0, 0x7fffffff))
            if not pcall(options.write or fs.write, 're2_coop_save_guard_challenge.txt', nonce) then return false end
            challenge, challenge_thread, challenge_run = nonce, owner, active_run
        end
        if native_valid and native.run_id == active_run and native.lua_challenge == challenge then
            if not launch_at then
                local ok, launch = pcall(read, 're2_coop_protected_launch.json')
                if not ok or not valid(launch, 'inherited_save_locks', now) or launch.run_id ~= active_run
                    or launch.game_pid ~= native.game_pid or not integer(launch.locked_files, 1) then return false end
                launch_at = launch.at
            end
            self.current = {game_pid = native.game_pid, run_id = active_run, at = native.at, launch_at = launch_at,
                runtime = native.runtime_locked_files ~= nil}
            self.reason = 'ok'
        end
        return self:ready()
    end
    function self:ready()
        local now, value = clock(), self.current
        return value ~= nil and now >= value.at and now - value.at <= 3
            and now >= value.launch_at and now - value.launch_at <= 3
    end
    function self:matches(binding)
        return self:ready() and type(binding) == 'table'
            and binding.game_pid == self.current.game_pid and binding.run_id == self.current.run_id
    end
    return self
end
return M
