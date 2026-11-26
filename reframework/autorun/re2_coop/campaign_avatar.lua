-- Animate an owned visual object from the local campaign's installed motion banks.
local M = {}
local root = "SectionRoot/Character/Player/"
local character_assets = {
    [0] = {folder = "pl0000", body = "pl0001", head = "pl0050", hair = "pl0070"},
    [1] = {folder = "pl1000", body = "pl1001", head = "pl1050", hair = "pl1070"},
}
character_assets[2], character_assets[3] = character_assets[0], character_assets[1]
local other_character = {[0]=1, [1]=0, [2]=3, [3]=2}
local motion_name, mesh_name = "via.motion.Motion", "via.render.Mesh"
local layer_name, bank_name = "via.motion.TreeLayer", "via.motion.DynamicMotionBank"
local max_dynamic_banks, startup_window = 64, 5
local root_motion_none = 0 -- via.motion.RootPlayMode.None on RE2 TDB 70.
local max_pose_gap, max_blend_distance_squared = 0.35, 16
local clip_blend_frames, clip_blend_window = 6.0, 0.22

local function finite(value)
    return type(value) == "number" and value > -math.huge and value < math.huge
end

local function uint32(value)
    return math.type(value) == "integer" and value >= 0 and value <= 0xffffffff
end

function M.valid_motion(value)
    return type(value) == "table" and uint32(value.bank) and uint32(value.id)
        and type(value.name) == "string" and #value.name <= 128 and value.name:match("^[%w_%-]+$") ~= nil
        and finite(value.frame) and finite(value.end_frame) and value.end_frame > 0
        and value.frame >= 0 and value.frame <= value.end_frame
end

local function same_clip(a, b)
    return a and a.bank == b.bank and a.id == b.id and a.name == b.name
end

local function holder(kind, path)
    local resource = assert(sdk.create_resource(kind, path), "missing avatar resource")
    return assert(resource:create_holder_global(kind .. "Holder"), "missing avatar holder")
end

local function mesh_ready(renderer)
    return sdk.is_managed_object(renderer) and renderer:call("get_MeshReady")
        and renderer:call("get_MaterialReady") and renderer:call("get_SkinningMesh")
end

local function instance(name)
    local object = assert(sdk.create_instance(name), "could not allocate " .. name)
    local ctor = sdk.find_type_definition(name):get_method(".ctor()")
    if ctor then ctor:call(object) end
    return object
end

local function copy_banks(source)
    local common = source:call("get_MotionBankAsset")
    local joints = source:call("get_JointMap")
    local bank_type = source:call("get_TargetBankType")
    local count = source:call("getDynamicMotionBankCount")
    if not common or not joints or not uint32(bank_type) or not uint32(count) or count > max_dynamic_banks then
        return nil
    end
    local banks = {}
    for index = 1, count do
        local source_bank = source:call("getDynamicMotionBank(System.Int32)", index - 1)
        if source_bank then
            local bank, list = source_bank:call("get_MotionBank"), source_bank:call("get_MotionList")
            if bank or list then
                local owned = instance(bank_name)
                if bank then owned:call("set_MotionBank", bank) end
                if list then owned:call("set_MotionList", list) end
                banks[index] = {object=owned, bank=bank, list=list}
            end
        end
    end
    return {common=common, joints=joints, bank_type=bank_type, count=count, banks=banks}
end

local function configure_banks(motion, source)
    motion:call("set_JointMap", source.joints)
    motion:call("set_TargetBankType", source.bank_type)
    motion:call("set_MotionBankAsset", source.common)
    motion:call("setDynamicMotionBankCount(System.Int32)", source.count)
    for index, bank in pairs(source.banks) do
        motion:call("setDynamicMotionBank(System.Int32, via.motion.DynamicMotionBank)", index - 1, bank.object)
    end
    motion:call("setupMotionBank()")
end

local function matches_node(motion, selected)
    if not motion or motion:call("get_MotionBankID") ~= selected.bank
        or motion:call("get_MotionID") ~= selected.id then return false end
    local name = motion:call("get_MotionName")
    if name == selected.name then return true end
    -- The installed BareHand bank resolves this observed Leon idle to its KFF variant.
    return selected.bank == 1000 and selected.id == 160
        and selected.name == "pl00_0160_OFF_Gazing_Idle_F_Loop"
        and name == "pl00_0160_KFF_Gazing_Idle_F_Loop"
end

local function align(layer, selected)
    local end_frame, frame = layer:call("get_EndFrame"), layer:call("get_Frame")
    if not finite(end_frame) or end_frame <= 0 or not finite(frame) then return false end
    local target = selected.frame / selected.end_frame * end_frame
    if math.abs(frame - target) > 3 then
        layer:call("set_Frame(System.Single)", target)
        local readback = layer:call("get_Frame")
        if not finite(readback) or math.abs(readback - target) > 2 then return false end
    end
    return true
end

local function place(actor, pose)
    local transform = assert(actor:call("get_Transform"), "missing avatar transform")
    local p, q = pose.origin, pose.rotation
    transform:set_position(Vector4f.new(p.x, p.y, p.z, 1), false)
    transform:set_rotation(Quaternion.new(q.w, q.x, q.y, q.z))
    local read_p, read_q = transform:get_position(), transform:get_rotation()
    local delta = (read_p.x-p.x)^2 + (read_p.y-p.y)^2 + (read_p.z-p.z)^2
    local length = math.sqrt(read_q.x^2 + read_q.y^2 + read_q.z^2 + read_q.w^2)
    local dot = (read_q.x*q.x + read_q.y*q.y + read_q.z*q.z + read_q.w*q.w) / length
    return delta <= 0.000001 and math.abs(dot) >= 0.99999 and math.abs(dot) <= 1.00001
end

local function render_pose(track, now)
    if not track.from then return track.target end
    local fraction = (now - track.at) / track.duration
    if fraction >= 1 or fraction < 0 then
        track.from = nil
        return track.target
    end
    local a, b = track.from.origin, track.target.origin
    local p = {x=a.x+(b.x-a.x)*fraction, y=a.y+(b.y-a.y)*fraction, z=a.z+(b.z-a.z)*fraction}
    a, b = track.from.rotation, track.target.rotation
    local sign = (a.x*b.x + a.y*b.y + a.z*b.z + a.w*b.w) < 0 and -1 or 1
    local weight = fraction * sign
    local x,y,z,w = a.x*(1-fraction)+b.x*weight, a.y*(1-fraction)+b.y*weight,
        a.z*(1-fraction)+b.z*weight, a.w*(1-fraction)+b.w*weight
    local length = math.sqrt(x*x + y*y + z*z + w*w)
    return {origin=p, rotation={x=x/length,y=y/length,z=z/length,w=w/length}}
end

local function track_pose(track, pose, now)
    local run, sequence = pose.observer_run_id, pose.observer_sequence
    if track and track.run == run and sequence <= track.sequence then return track end
    local p, q = pose.origin, pose.rotation
    local target = {origin={x=p.x,y=p.y,z=p.z}, rotation={x=q.x,y=q.y,z=q.z,w=q.w}}
    local next_pose = {target=target, run=run, sequence=sequence, at=now}
    if track and track.run == run then
        local interval = now-track.at
        local previous = render_pose(track, now)
        local prior = previous.origin
        local distance = (p.x-prior.x)^2+(p.y-prior.y)^2+(p.z-prior.z)^2
        if interval > 0 and interval <= max_pose_gap and distance <= max_blend_distance_squared then
            next_pose.from, next_pose.duration = previous, math.max(0.065, math.min(interval, 0.15))
        end
    end
    return next_pose
end

local function enum_value(name, key)
    local definition = sdk.find_type_definition(name)
    local field = definition and definition:get_field(key)
    return field and field:get_data(nil)
end

local function clip_bank_types(motion, selected)
    local variants, seen = {}, {}
    if motion:call("hasMotion(System.UInt32, System.UInt32)", selected.bank, selected.id) == true then
        variants[1], seen[-1] = -1, true
    end
    -- A shared bank ID may select a different weapon or costume variant.
    local count = motion:call("getActiveMotionBankCount")
    if not uint32(count) or count > 256 then return variants end
    for index = 0, count - 1 do
        local bank = motion:call("getActiveMotionBank(System.UInt32)", index)
        if bank and bank:call("get_BankID") == selected.bank then
            local kind = bank:call("get_BankType")
            if uint32(kind) then
                if kind > 0x7fffffff then kind = kind - 0x100000000 end
                if not seen[kind] and motion:call("hasMotion(System.UInt32, System.UInt32, System.Int32)",
                        selected.bank, selected.id, kind) == true then
                    variants[#variants+1], seen[kind] = kind, true
                end
            end
        end
    end
    return variants
end

function M.new(preview, clock)
    if sdk.get_tdb_version() ~= 70 then return nil end
    local definition = assert(sdk.find_type_definition("via.GameObject"))
    local create = assert(definition:get_method("create(System.String)"))
    local destroy = assert(definition:get_method("destroy(via.GameObject)"))
    assert(create:is_static() and destroy:is_static(), "unsupported avatar object API")
    local motion_type, mesh_type = assert(sdk.typeof(motion_name)), assert(sdk.typeof(mesh_name))
    if not clock then
        local uptime = assert(sdk.find_type_definition("via.Application"):get_method("get_UpTimeSecond"))
        clock = function() return uptime:call(nil) end
    end
    local crossfade = enum_value("via.motion.InterpolationMode", "CrossFade")
    local smooth_curve = enum_value("via.motion.InterpolationCurve", "Smooth")
    local self = {}
    local state, retry_at, retry_reason

    local function draw_object(object, enabled)
        if object:call("get_DrawSelf") ~= enabled then object:call("set_DrawSelf", enabled) end
        assert(object:call("get_DrawSelf") == enabled, "avatar visibility readback failed")
    end

    local function visible(enabled)
        draw_object(state.object, enabled)
        for _, part in ipairs(state.parts) do draw_object(part.object, enabled) end
        state.showing = enabled
    end

    function self:clear()
        if state then
            for _, part in ipairs(state.parts) do
                if sdk.is_managed_object(part.object) then
                    pcall(draw_object, part.object, false)
                    destroy:call(nil, part.object)
                end
            end
            if sdk.is_managed_object(state.object) then
                pcall(draw_object, state.object, false)
                destroy:call(nil, state.object)
            end
        end
        state, retry_at, retry_reason = nil, nil, nil
    end

    local function bind_mesh(part, model)
        local path = root .. state.assets.folder .. "/" .. model .. "/" .. model
        part.mesh = holder("via.render.MeshResource", path .. ".mesh")
        part.material = holder("via.render.MeshMaterialResource", path .. ".mdf2")
        part.renderer = assert(part.object:call("createComponent(System.Type)", mesh_type))
        part.renderer:call("setMesh(via.render.MeshResourceHolder)", part.mesh)
        part.renderer:call("set_Material(via.render.MeshMaterialResourceHolder)", part.material)
    end

    local function add_part(name, model)
        local object = assert(create:call(nil, name), "could not create avatar part")
        local part = {object=object}
        state.parts[#state.parts+1] = part
        draw_object(object, false)
        local transform = assert(object:call("get_Transform"))
        transform:call("setParent(via.Transform, System.Boolean)", state.transform, false)
        transform:call("set_SameJointsConstraint", true)
        part.transform = transform
        bind_mesh(part, model)
    end

    local function build(player, assets, pose)
        local source = player:call("getComponent(System.Type)", motion_type)
        local banks = source and copy_banks(source)
        if not banks then return false end
        local name = preview and "RE2CoopSoloPreview" or "RE2CoopCampaignAvatar"
        local object = assert(create:call(nil, name), "could not create avatar")
        assert(object:get_address() ~= player:get_address(), "avatar aliases the local player")
        state = {object=object, assets=assets, banks=banks, parts={},
            deadline=os.time()+startup_window}
        state.transform = assert(object:call("get_Transform"))
        visible(false)
        assert(place(object, pose), "initial avatar pose readback failed")
        bind_mesh(state, assets.body)
        state.motion = assert(object:call("createComponent(System.Type)", motion_type))
        assert(state.motion:get_address() ~= source:get_address(), "avatar motion aliases the local player")
        configure_banks(state.motion, banks)
        state.motion:call("set_RootMotion", root_motion_none)
        assert(state.motion:call("get_RootMotion") == root_motion_none, "could not disable avatar root motion")
        state.motion:call("setLayerCount(System.UInt32)", 1)
        if not state.motion:call("getLayer(System.UInt32)", 0) then
            state.motion:call("setLayer(System.UInt32, via.motion.TreeLayer)", 0, instance(layer_name))
        end
        add_part(name .. "Head", assets.head)
        add_part(name .. "Hair", assets.hair)
        return true
    end

    local function parts_ready()
        local head = state.transform:call("getJointByName", "head")
        if not head then return false end
        for _, part in ipairs(state.parts) do
            if not mesh_ready(part.renderer) then return false end
            local parent = part.transform:call("get_Parent")
            local joint = part.transform:call("getJointByName", "head")
            local constraint = joint and joint:call("get_ConstraintJoint")
            if not parent or parent:get_address() ~= state.transform:get_address()
                or not part.transform:call("get_SameJointsConstraint")
                or not constraint or constraint:get_address() ~= head:get_address() then return false end
        end
        return true
    end

    local function init_layer(now)
        if not sdk.is_managed_object(state.motion) then return false end
        if not mesh_ready(state.renderer) or not state.motion:call("get_JointsConstructed") then
            if state.bank_retry_at == nil or now >= state.bank_retry_at then
                state.motion:call("setupMotionBank()")
                state.bank_retry_at = now + 1
            end
            return false
        end
        local layer = state.motion:call("getLayer(System.UInt32)", 0)
        if not layer then return false end
        if state.layer and sdk.is_managed_object(state.layer)
            and layer:get_address() == state.layer:get_address() then return true end
        layer:call("set_LocalBankType", -1)
        layer:call("set_BlendRate", 1.0)
        layer:call("set_Speed", 1.0)
        layer:call("setup()")
        state.layer, state.selected = layer, nil
        return true
    end

    local function next_variant()
        local index = state.variant + 1
        local bank_type = state.variants[index]
        if bank_type == nil then return end
        local selected = state.selected
        state.variant, state.clip_checks = index, 0
        state.layer:call("set_LocalBankType", bank_type)
        if index == 1 and state.blend_until then
            state.layer:call(
                "changeMotion(System.UInt32, System.UInt32, System.Single, System.Single, via.motion.InterpolationMode, via.motion.InterpolationCurve)",
                selected.bank, selected.id, 0.0, clip_blend_frames, crossfade, smooth_curve)
        else
            state.layer:call("changeMotion(System.UInt32, System.UInt32, System.Single)", selected.bank, selected.id, 0.0)
        end
    end

    local function select_clip(selected, at)
        state.variants = clip_bank_types(state.motion, selected)
        state.blend_until = nil
        if #state.variants == 0 then
            state.motion:call("setupMotionBank()")
            return
        end
        if state.selected and state.showing and crossfade and smooth_curve then
            state.blend_until = at + clip_blend_window
        end
        state.selected = {bank=selected.bank, id=selected.id, name=selected.name}
        state.aligned, state.variant = nil, 0
        next_variant()
    end

    local function apply_pose(pose, at)
        state.track = track_pose(state.track, pose, at)
        local placed = place(state.object, render_pose(state.track, at))
        visible(placed)
        return placed
    end

    function self:advance()
        if not (state and state.showing and state.track and state.track.from) then return end
        if not (sdk.is_managed_object(state.object) and place(state.object, render_pose(state.track, clock()))) then
            self:clear()
            return false
        end
    end

    function self:update(player, pose, viewer_role)
        if viewer_role ~= 'H' and viewer_role ~= 'G' then self:clear(); return false, 'avatar_role_missing' end
        local selected = pose.motion
        local scenario = pose.campaign_area and pose.campaign_area.scenario
        if viewer_role == 'H' then scenario = other_character[scenario] end
        local assets = character_assets[scenario]
        if not assets or not M.valid_motion(selected) then self:clear(); return false, 'motion_or_scenario_missing' end
        if state and state.assets ~= assets then self:clear() end
        local now = os.time()
        if retry_at and now < retry_at then return false, retry_reason end
        if not state then
            if not build(player, assets, pose) then
                retry_at, retry_reason = now + 1, 'motion_banks_unavailable'
                return false, retry_reason
            end
            return false, 'mesh_or_skeleton_pending'
        end
        if not sdk.is_managed_object(state.object) then self:clear(); return false, 'object_lost' end
        local at = clock()
        local ready = init_layer(now)
        if not ready or not same_clip(state.selected, selected) then
            local reason = ready and 'clip_pending' or 'mesh_or_skeleton_pending'
            if now >= state.deadline then self:clear(); retry_at, retry_reason = now + 1, reason
            else
                if ready then select_clip(selected, at) end
                if ready and state.blend_until and parts_ready() then
                    return apply_pose(pose, at), 'clip_blending'
                end
                visible(false)
            end
            return false, reason
        end
        local node = state.layer:call("get_HighestWeightMotionNode")
        if not matches_node(node, selected) then
            if state.blend_until and at < state.blend_until and parts_ready() then
                return apply_pose(pose, at), 'clip_blending'
            end
            visible(false)
            state.blend_until = nil
            state.clip_checks = state.clip_checks + 1
            if now >= state.deadline then self:clear(); retry_at, retry_reason = now + 1, 'clip_readback_pending'
            elseif state.clip_checks >= 3 then next_variant() end
            return false, 'clip_readback_pending'
        end
        state.blend_until = nil
        if not parts_ready() then
            visible(false)
            local reason = 'avatar_parts_pending'
            if now >= state.deadline then self:clear(); retry_at, retry_reason = now + 1, reason end
            return false, reason
        end
        state.deadline = now + startup_window
        if state.aligned ~= pose.observer_sequence or state.aligned_run ~= pose.observer_run_id then
            if not align(state.layer, selected) then visible(false); return false, 'frame_readback_failed' end
            state.aligned, state.aligned_run = pose.observer_sequence, pose.observer_run_id
        end
        local placed = apply_pose(pose, at)
        return placed, placed and 'visible' or 'transform_readback_failed'
    end

    return self
end

return M
