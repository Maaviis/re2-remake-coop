-- Developer opt-in. The consumer package does not load this script.
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end

local function actor(object)
    if not object then return {present=false} end
    local result = {present=true, draw_self=object:call("get_DrawSelf")}
    local mesh = object:call("getComponent(System.Type)", sdk.typeof("via.render.Mesh"))
    if mesh then
        result.mesh_ready = mesh:call("get_MeshReady")
        if result.mesh_ready then
            local resource = mesh:call("getMesh")
            local path = resource and resource:call("ToString()")
            result.mesh_id = type(path) == "string" and path:lower():match("/(pl%d%d%d%d)%.mesh") or nil
        end
    end
    local motion = object:call("getComponent(System.Type)", sdk.typeof("via.motion.Motion"))
    if motion then
        result.joints_constructed = motion:call("get_JointsConstructed")
        local layer = motion:call("getLayerCount") > 0 and motion:call("getLayer(System.UInt32)", 0)
        local node = layer and layer:call("get_HighestWeightMotionNode")
        if node then
            result.bank = node:call("get_MotionBankID")
            result.clip = node:call("get_MotionID")
            result.frame = node:call("get_Frame")
        end
    end
    return result
end

local function observe()
    local manager = sdk.get_native_singleton("via.SceneManager")
    local scene = manager and sdk.call_native_func(manager, sdk.find_type_definition("via.SceneManager"), "get_CurrentScene")
    if not scene then return {status="scene_unavailable"} end
    local find = sdk.find_type_definition("via.Scene"):get_method("findGameObject(System.String)")
    local players = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    local function read(object)
        local ok, value = pcall(actor, object)
        return ok and value or {read_error=true}
    end
    return {status="sampled", player=read(players and players:call("get_CurrentPlayer")),
        partner=read(find:call(scene, "RE2CoopCampaignAvatar")),
        preview=read(find:call(scene, "RE2CoopSoloPreview"))}
end

local previous
re.on_pre_application_entry("UpdateBehavior", function()
    local now = os.time()
    if previous == now then return end
    previous = now
    local ok, result = pcall(observe)
    if not ok then result = {status="read_error"} end
    result.schema, result.at = 1, now
    pcall(json.dump_file, "re2_coop_dev_inspector.json", result)
end)
