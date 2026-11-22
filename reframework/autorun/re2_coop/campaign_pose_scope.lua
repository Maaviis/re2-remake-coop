local M = {}

local function read_document(path, limit)
    local read, contents = pcall(fs.read, path)
    if not read or type(contents) ~= 'string' or #contents == 0 or #contents > limit then return nil end
    local decoded, document = pcall(json.load_string, contents)
    if decoded and type(document) == 'table' and document.schema == 1 then return document end
end

local function fresh(at, seconds)
    if type(at) ~= 'number' or at % 1 ~= 0 then return false end
    local age = os.time() - at
    return age >= 0 and age <= seconds
end

local function token(value, length)
    return type(value) == 'string' and #value == length and value:match('^[0-9a-f]+$') ~= nil
end

local function u32(value)
    return type(value) == 'number' and value % 1 == 0 and value >= 1 and value <= 0xffffffff
end

function M.read_release()
    local guard = read_document('re2_coop_save_guard.json', 32768)
    if guard == nil or not fresh(guard.at, 3) or guard.active ~= true or guard.protection_active ~= true
        or guard.in_title ~= false or guard.load_phase ~= 'scene_loaded'
        or guard.load_error ~= '' or type(guard.protection) ~= 'table' then return nil end
    local hold, id = guard.load_hold, guard.load_request_id
    if not token(id, 32) or guard.policy_id ~= id or type(hold) ~= 'table' or hold.schema ~= 1
        or hold.scope ~= 'prepared_load_native_pause' or not fresh(hold.observed_at, 3)
        or hold.phase ~= 'released' or hold.native_phase ~= 'released' or hold.load_request_id ~= id
        or hold.pause_id ~= id or type(guard.guard_run_id) ~= 'string' or guard.guard_run_id == ''
        or hold.guard_run_id ~= guard.guard_run_id then return nil end
    local scope = hold.campaign
    if type(scope) ~= 'table' or type(scope.session_id) ~= 'string' or scope.session_id == ''
        or not u32(scope.game_pid) or scope.game_pid ~= guard.protection.game_pid
        or (scope.role ~= 'H' and scope.role ~= 'G') or not u32(scope.revision)
        or not token(scope.protection_run_id, 32) or scope.protection_run_id ~= guard.protection.run_id
        or not token(scope.attempt_id, 32) or not token(scope.snapshot_epoch, 16) then return nil end
    local player = type(scope.local_player) == 'string' and tonumber(scope.local_player)
    local scene = type(scope.local_scene) == 'string' and tonumber(scope.local_scene)
    if math.type(player) ~= 'integer' or player <= 0 or math.type(scene) ~= 'integer' or scene <= 0 then return nil end
    return {request_id = id, session_id = scope.session_id, attempt_id = scope.attempt_id,
        game_pid = scope.game_pid, role = scope.role, revision = scope.revision, snapshot_epoch = scope.snapshot_epoch,
        player_address = player, scene_address = scene}
end

function M.peer_matches(scope)
    local peer = read_document('re2_coop_native_peer.json', 1024)
    return peer ~= nil and fresh(peer.at, 2) and peer.game_pid == scope.game_pid and peer.role == scope.role
        and peer.revision == scope.revision and peer.snapshot_epoch == scope.snapshot_epoch
end

function M.scene_address()
    local manager = sdk.get_native_singleton('via.SceneManager')
    local scene_type = sdk.find_type_definition('via.SceneManager')
    local scene = manager and scene_type and sdk.call_native_func(manager, scene_type, 'get_CurrentScene')
    return scene and scene:get_address()
end

return M
