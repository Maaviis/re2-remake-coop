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
    local self = {current = nil, reason = token(run_id) and 'waiting_for_receipts' or 'launch_identity_unavailable'}
    local function valid(value, source, now)
        return type(value) == 'table' and value.schema == 1 and value.source == source
            and value.active == true and integer(value.at, 0) and now >= value.at and now - value.at <= 3
            and integer(value.game_pid, 1) and token(run_id) and value.run_id == run_id
            and value.app_id == 883710 and value.build_id == 11636119
    end
    function self:poll()
        self.current = nil
        self.reason = token(run_id) and 'protection_receipt_invalid' or 'launch_identity_unavailable'
        local native_ok, native = pcall(read, 're2_coop_native_save_guard.json')
        local launch_ok, launch = pcall(read, 're2_coop_protected_launch.json')
        local now = clock()
        if native_ok and launch_ok and valid(native, 'steam_storage_guard', now)
            and valid(launch, 'inherited_save_locks', now) and native.game_pid == launch.game_pid
            and native.reason == 'ok' and native.interface == '014' and native.guarded_methods == 10
            and integer(launch.locked_files, 1) then
            self.current = {game_pid = native.game_pid, run_id = run_id, at = native.at, launch_at = launch.at}
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
