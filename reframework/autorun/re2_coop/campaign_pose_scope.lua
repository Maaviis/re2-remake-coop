local M = {}
local root = 'app.ropeway.'
local flow_name = root .. 'gamemastering.MainFlowManager'
local area_methods

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

local function id32(value)
    return math.type(value) == 'integer' and value >= 0 and value <= 0x7fffffff
end

local function address(value)
    local resolved = type(value) == 'string' and tonumber(value)
    if math.type(resolved) == 'integer' and resolved > 0 then return resolved end
end

local function area_valid(area)
    return type(area) == 'table' and id32(area.scenario) and area.scenario <= 3
        and id32(area.map) and id32(area.area)
end

function M.same_area(a, b)
    return area_valid(a) and area_valid(b) and a.scenario == b.scenario and a.map == b.map and a.area == b.area
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
        or not token(scope.attempt_id, 32) or not token(scope.snapshot_epoch, 16)
        or not id32(scope.scenario) or scope.scenario > 3 then return nil end
    local player, scene = address(scope.local_player), address(scope.local_scene)
    if not player or not scene then return nil end
    return {request_id = id, session_id = scope.session_id, attempt_id = scope.attempt_id,
        game_pid = scope.game_pid, role = scope.role, revision = scope.revision, snapshot_epoch = scope.snapshot_epoch,
        player_address = player, scene_address = scene, scenario = scope.scenario}
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

local function area_metadata()
    assert(sdk.get_tdb_version() == 70)
    local flow_type = assert(sdk.find_type_definition(flow_name))
    local enemy_type = assert(sdk.find_type_definition(root .. 'EnemyManager'))
    local function getter(type_definition, name, result, static)
        local method = assert(type_definition:get_method(name))
        assert(method:is_static() == static and #method:get_param_types() == 0
            and method:get_return_type():get_full_name() == result)
        return method
    end
    return {
        title = getter(flow_type, 'get_IsInTitle', 'System.Boolean', false),
        loading = getter(flow_type, 'get_IsInLoadGameData', 'System.Boolean', false),
        finished = getter(flow_type, 'get_IsFinishedLoadScene', 'System.Boolean', false),
        scenario = getter(flow_type, 'get_CurrentScenarioType', flow_name .. '.ScenarioType', false),
        map = getter(enemy_type, 'get_LastPlayerStaySceneID', root .. 'gamemastering.Map.ID', true),
        area = getter(enemy_type, 'get_LastPlayerStaySceneArea', root .. 'gamemastering.Map.Area', true),
    }
end

function M.supports_area()
    if area_methods == nil then
        local ok, methods = pcall(area_metadata)
        area_methods = ok and methods or false
    end
    return area_methods ~= false
end

function M.read_area()
    if not M.supports_area() then return nil end
    local flow = sdk.get_managed_singleton(flow_name)
    if not flow or area_methods.title:call(flow) ~= false or area_methods.loading:call(flow) ~= false
        or area_methods.finished:call(flow) ~= true then return nil end
    local result = {scenario = area_methods.scenario:call(flow), map = area_methods.map:call(nil),
        area = area_methods.area:call(nil)}
    if area_valid(result) then return result end
end

function M.observed_context(scope)
    local sample = read_document('re2_coop_observer.json', 4096)
    if sample == nil or sample.source ~= 're2' or sample.tdb ~= 70 or sample.available ~= true
        or not fresh(sample.observed_at, 2) or sample.campaign_attempt_id ~= scope.attempt_id
        or not area_valid(sample.campaign_area) or sample.campaign_area.scenario ~= scope.scenario then return nil end
    local context = sample.campaign_local_context
    if type(context) ~= 'table' or context.request_id ~= scope.request_id then return nil end
    local player, scene = address(context.player), address(context.scene)
    if player and scene then return {player_address = player, scene_address = scene, area = sample.campaign_area} end
end

return M
