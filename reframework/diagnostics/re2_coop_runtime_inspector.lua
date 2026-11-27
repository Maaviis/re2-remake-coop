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


-- The owning renderer calls this only from its normal campaign or preview update.
-- Never search the live scene or retain a managed object across frames.
local renderer = require("re2_coop.campaign_avatar")
local samples = {}
local function read(object)
    local ok, value = pcall(actor, object)
    return ok and value or {read_error=true}
end

local function sample(preview, player, object)
    local now = os.time()
    local key = preview and "preview" or "partner"
    if samples[key] and samples[key].at == now then return end
    samples[key] = {at=now, value=read(object)}
    local result = {schema=1, at=now, status="sampled", player=read(player)}
    for name, entry in pairs(samples) do
        if entry.at == now then result[name] = entry.value end
    end
    pcall(json.dump_file, "re2_coop_dev_inspector.json", result)
end

renderer.on_inspector_sample = sample
re.on_script_reset(function()
    if renderer.on_inspector_sample == sample then renderer.on_inspector_sample = nil end
end)
