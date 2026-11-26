-- Display the verified partner during a released campaign, with a separate opt-in test mode.
if reframework:get_game_name() ~= "re2" then return end

local campaign = require("re2_coop.campaign_pose_scope")
local avatar_ok, avatar_module = pcall(require, "re2_coop.campaign_avatar")
local avatar
if avatar_ok and type(avatar_module) == "table" and type(avatar_module.new) == "function"
    and type(avatar_module.valid_motion) == "function" then
    local started, actor = pcall(avatar_module.new)
    if started then avatar = actor end
end
local filename = "re2_coop_guest_pose.json"
local command_filename = "re2_coop_guest_pose_command.json"
local max_age = 5
local max_component = 3.4028234663852886e38
local color = 0xFF64E8FF
local axis_length = 0.7
local mannequin_base = "objectroot/setmodel/sm3x_artifactprops/sm32/sm32_256_mannequin01a/"
    .. "sm32_256_mannequin01a_00ms"
local mannequin_mesh = mannequin_base .. ".mesh"
local mannequin_material = mannequin_base .. "_mat.mdf2"
local updates = 0
local marker
local test_enabled = false
local mannequin_enabled = false
local test_status = "Disabled"
local owned_object
local destroy_object
local mannequin_renderer
local accepted_pose
local pending_readback
local local_player_address
local local_scene_address
local cleanup_error
local last_command_nonce
local campaign_id
local campaign_retired = false
local campaign_verified = false
local campaign_area
local waiting_for_campaign_area = false
local departure_pose
local avatar_visible, avatar_failed = false, false
local avatar_cleanup_error
local last_admission_reason, last_render_reason

local function valid_number(n)
    return type(n) == "number" and n >= -max_component and n <= max_component
end

local function valid_vector(value, size)
    if type(value) ~= "table" or #value ~= size then return false end
    for i = 1, size do
        if not valid_number(value[i]) then return false end
    end
    return true
end

local function fresh(timestamp, limit)
    if type(timestamp) ~= "number" then return false end
    local age = os.time() - timestamp
    return timestamp % 1 == 0 and age >= 0 and age <= (limit or max_age)
end

local function read_marker()
    local contents = fs.read(filename)
    if type(contents) ~= "string" or contents == "" or #contents > 4096 then return nil end
    local data = json.load_string(contents)
    if type(data) ~= "table" or data.schema ~= 1 or data.connected ~= true
        or not fresh(data.written_at) or (data.observed_at ~= nil and not fresh(data.observed_at))
        or type(data.player_id) ~= "string" or data.player_id == ""
        or type(data.pose) ~= "table" then
        return nil
    end

    local position, rotation = data.pose.position, data.pose.rotation
    if not valid_vector(position, 3) or not valid_vector(rotation, 4) then return nil end
    local x, y, z, w = rotation[1], rotation[2], rotation[3], rotation[4]
    local length = math.sqrt(x^2 + y^2 + z^2 + w^2)
    if length == 0 then return nil end
    x, y, z, w = x / length, y / length, z / length, w / length

    -- Rotate the local +Z diagnostic axis by the received (x, y, z, w) quaternion.
    local dx, dy, dz = 2 * (x*z + w*y), 2 * (y*z - w*x), 1 - 2 * (x*x + y*y)
    local motion
    local candidate = data.pose.motion
    if avatar and data.pose.campaign_attempt_id and avatar_module.valid_motion(candidate) then
        motion = {bank=candidate.bank, id=candidate.id, name=candidate.name,
            frame=candidate.frame, end_frame=candidate.end_frame}
    end
    return {
        label = "Remote pose: " .. data.player_id,
        timestamp = data.written_at,
        observed_at = data.observed_at,
        session_id = data.session_id,
        sequence = data.sequence,
        player_id = data.player_id,
        campaign_attempt_id = data.pose.campaign_attempt_id,
        campaign_area = data.pose.campaign_area,
        observer_run_id = data.pose.observer_run_id,
        observer_sequence = data.pose.observer_sequence,
        motion = motion,
        rotation = {x = x, y = y, z = z, w = w},
        origin = Vector3f.new(position[1], position[2], position[3]),
        tip = Vector3f.new(position[1] + axis_length * dx, position[2] + axis_length * dy,
            position[3] + axis_length * dz),
    }
end

local function campaign_for_pose(pose, player)
    local scope, release_reason = campaign.read_release()
    if not scope and not campaign_id then return nil, nil, release_reason end
    local scene_address = campaign.scene_address()
    local player_address = player and player:get_address()
    local live_area = campaign.read_area()
    if campaign_area and live_area and not campaign.same_area(campaign_area, live_area) then
        departure_pose = departure_pose or accepted_pose
    end
    if campaign_area and ((scene_address and scene_address ~= 0 and scene_address ~= local_scene_address)
        or (player_address and player_address ~= 0 and player_address ~= local_player_address)) then
        waiting_for_campaign_area = true
        departure_pose = departure_pose or accepted_pose
    end
    if not scope then return nil, nil, release_reason or 'release_unavailable' end
    if pose == nil or type(pose.observer_run_id) ~= "string" or pose.observer_run_id == ""
        or #pose.observer_run_id > 128 or math.type(pose.observer_sequence) ~= "integer"
        or pose.observer_sequence < 1 or pose.observer_sequence > 9007199254740991 then
        return scope, nil, 'waiting_for_scoped_pose'
    end
    local context = campaign.observed_context(scope)
    local matches = context ~= nil and scope.session_id == pose.session_id
        and scope.attempt_id == pose.campaign_attempt_id and fresh(pose.observed_at, 3)
        and context.scene_address == scene_address and context.player_address == player_address
        and not (waiting_for_campaign_area and campaign.same_area(campaign_area, context.area))
        and (departure_pose == nil or pose.observer_run_id ~= departure_pose.observer_run_id
            or pose.observer_sequence > departure_pose.observer_sequence)
        and campaign.same_area(context.area, pose.campaign_area)
        and campaign.same_area(context.area, live_area)
        and campaign.peer_matches(scope)
    if matches then return scope, context end
    return scope, nil, context and 'pose_or_peer_binding_mismatch' or 'current_observer_unavailable'
end

local function campaign_enabled()
    return campaign_id ~= nil and not campaign_retired
end

local function current_player()
    if reframework:get_game_name() ~= "re2" then return nil end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    if manager ~= nil then return manager:call("get_CurrentPlayer") end
end

local function clear_avatar()
    if not avatar then return true end
    local ok, error_message = pcall(avatar.clear, avatar)
    if not ok then
        if avatar_cleanup_error ~= error_message then
            log.info("RE2_COOP_CAMPAIGN_AVATAR cleanup failed: " .. tostring(error_message))
        end
        avatar_cleanup_error = error_message
        return false
    end
    avatar_cleanup_error = nil
    return true
end

local function remove_test_object()
    pending_readback = nil
    campaign_verified = false
    local avatar_cleared = clear_avatar()
    avatar_visible, avatar_failed = false, false
    if owned_object == nil then return avatar_cleared end
    local ok, err = pcall(function()
        if sdk.is_managed_object(owned_object) then
            destroy_object:call(nil, owned_object)
        end
    end)
    if not ok then
        test_enabled = false
        test_status = "Cleanup failed. See the REFramework log."
        if cleanup_error ~= err then
            cleanup_error = err
            log.info("RE2_COOP_GUEST_OBJECT cleanup failed: " .. tostring(err))
        end
        return false
    end
    owned_object, destroy_object, mannequin_renderer, cleanup_error = nil, nil, nil, nil
    return avatar_cleared
end

local function same_vector(a, b)
    return a.x == b.x and a.y == b.y and a.z == b.z
end

local function same_motion(a, b)
    if not a or not b then return a == b end
    return a.bank == b.bank and a.id == b.id and a.name == b.name
        and a.frame == b.frame and a.end_frame == b.end_frame
end

local function pose_is_fresh(pose)
    return pose ~= nil and fresh(pose.timestamp)
        and (pose.observed_at == nil or fresh(pose.observed_at))
end

local function validate_test_pose(pose)
    if sdk.get_tdb_version() ~= 70 then error("requires RE2 TDB 70") end
    if type(pose.session_id) ~= "string" or pose.session_id == "" or
        type(pose.sequence) ~= "number" or pose.sequence < 0 or
        pose.sequence > 9007199254740991 or pose.sequence % 1 ~= 0 then
        error("missing verified session metadata")
    end
    if owned_object ~= nil and not sdk.is_managed_object(owned_object) then
        error("test object no longer exists")
    end
    local same_pose = false
    if accepted_pose ~= nil then
        if pose.session_id ~= accepted_pose.session_id or pose.player_id ~= accepted_pose.player_id then
            error("remote session or player changed")
        elseif pose.sequence < accepted_pose.sequence then
            error("remote pose sequence moved backwards")
        end
        local a, b = pose.rotation, accepted_pose.rotation
        same_pose = same_vector(pose.origin, accepted_pose.origin) and same_vector(a, b) and a.w == b.w
        if pose.sequence == accepted_pose.sequence and (not same_pose or not same_motion(pose.motion, accepted_pose.motion)) then
            error("remote pose changed at the same sequence")
        end
    end
    return same_pose
end

local function instance_method(object_type, signature, param_count)
    local method = object_type and object_type:get_method(signature)
    if method == nil or method:is_static() or method:get_num_params() ~= param_count then
        error(signature .. " unavailable")
    end
    return method
end

local function load_holder(resource_type, path)
    local resource = sdk.create_resource(resource_type, path)
    -- Keep a Lua-tracked holder while the renderer can use the resource.
    local holder = resource and resource:create_holder_global(resource_type .. "Holder")
    if holder == nil then error("could not load " .. path) end
    return holder
end

local function prepare_mannequin(object_type)
    local mesh_type = sdk.find_type_definition("via.render.Mesh")
    local runtime_type = mesh_type and mesh_type:get_runtime_type()
    if runtime_type == nil then error("via.render.Mesh unavailable") end
    local add_component = instance_method(object_type, "createComponent(System.Type)", 1)
    local set_mesh = instance_method(mesh_type, "setMesh(via.render.MeshResourceHolder)", 1)
    local set_material = instance_method(mesh_type, "set_Material(via.render.MeshMaterialResourceHolder)", 1)
    local get_mesh = instance_method(mesh_type, "getMesh()", 0)
    local get_material = instance_method(mesh_type, "get_Material()", 0)
    local mesh = load_holder("via.render.MeshResource", mannequin_mesh)
    local material = load_holder("via.render.MeshMaterialResource", mannequin_material)

    return function(object)
        local component = add_component:call(object, runtime_type)
        if component == nil then error("could not create mannequin render component") end
        set_mesh:call(component, mesh)
        set_material:call(component, material)
        return {
            component = component, get_mesh = get_mesh, get_material = get_material,
            mesh = mesh, material = material,
        }
    end
end

local function holds_resource(holder, expected_holder, path, version)
    if holder == nil then return false end
    if holder:get_address() == expected_holder:get_address() then return true end
    -- A getter may wrap the same native resource in a different holder.
    local label = holder:call("ToString()")
    if type(label) ~= "string" then return false end
    local normalized = label:lower():gsub("\\", "/")
    local resource_path = normalized:match("%[@?([^%]]+)%]$") or normalized
    resource_path = resource_path:gsub("^natives/stm/", "")
    return resource_path == path or resource_path == path .. version
end

local function verify_mannequin()
    local renderer = mannequin_renderer
    local component = renderer.component
    if not sdk.is_managed_object(component)
        or not holds_resource(renderer.get_mesh:call(component), renderer.mesh, mannequin_mesh, ".2109108288")
        or not holds_resource(renderer.get_material:call(component), renderer.material, mannequin_material, ".21") then
        error("mannequin resource readback mismatch")
    end
end

local function apply_test_pose(pose, same_pose)
    if owned_object ~= nil and same_pose then
        if mannequin_renderer ~= nil then verify_mannequin() end
        accepted_pose = pose
        if campaign_enabled() then departure_pose = nil end
        return
    end
    if owned_object == nil then
        local object_type = sdk.find_type_definition("via.GameObject")
        local create = object_type and object_type:get_method("create(System.String)")
        local destroy = object_type and object_type:get_method("destroy(via.GameObject)")
        if create == nil or not create:is_static() or destroy == nil or
            not destroy:is_static() or destroy:get_num_params() ~= 1 then
            error("GameObject creation or cleanup API unavailable")
        end
        local transform_type = sdk.find_type_definition("via.Transform")
        if transform_type == nil or transform_type:get_method("set_Position") == nil
            or transform_type:get_method("set_Rotation") == nil then
            error("Transform setters unavailable")
        end
        local campaign_object = campaign_enabled()
        local attach_mannequin = (campaign_object or mannequin_enabled) and prepare_mannequin(object_type)
        owned_object = create:call(nil, campaign_object and "RE2CoopRemotePlayer" or "RE2CoopRemotePoseTest")
        destroy_object = destroy
        if owned_object == nil then error("could not create test object") end
        if attach_mannequin then mannequin_renderer = attach_mannequin(owned_object) end
    end

    local transform = owned_object:call("get_Transform")
    if transform == nil then error("test object has no transform") end
    local p, q = pose.origin, pose.rotation
    transform:set_position(Vector4f.new(p.x, p.y, p.z, 1), false)
    transform:set_rotation(Quaternion.new(q.w, q.x, q.y, q.z))

    accepted_pose = pose
    if campaign_enabled() then departure_pose = nil end
    pending_readback = pose
    test_status = "Waiting for the next engine update"
end

local function verify_test_pose(pose)
    if not sdk.is_managed_object(owned_object) then error("test object no longer exists") end
    if campaign_enabled() and mannequin_renderer == nil then error("campaign mannequin unavailable") end
    local transform = owned_object:call("get_Transform")
    if transform == nil then error("test object has no transform") end
    local p, q = pose.origin, pose.rotation
    local read_p, read_q = transform:get_position(), transform:get_rotation()
    local position_error = (read_p.x - p.x)^2 + (read_p.y - p.y)^2 + (read_p.z - p.z)^2
    local length = math.sqrt(read_q.x^2 + read_q.y^2 + read_q.z^2 + read_q.w^2)
    local dot = (read_q.x*q.x + read_q.y*q.y + read_q.z*q.z + read_q.w*q.w) / length
    if not (position_error <= 0.000001 and math.abs(dot) >= 0.99999 and math.abs(dot) <= 1.00001) then
        error("transform readback mismatch")
    end
    local detail = ""
    if mannequin_renderer ~= nil then
        verify_mannequin()
        detail = " mannequin resources assigned"
    end

    pending_readback = nil
    test_status = "Transform verified at sequence " .. tostring(pose.sequence)
    if mannequin_renderer ~= nil then test_status = test_status .. " (mannequin resources assigned)" end
    if not campaign_enabled() or not campaign_verified then
        log.info(string.format("RE2_COOP_GUEST_OBJECT verified tdb=70 sequence=%s position=(%.3f,%.3f,%.3f) "
            .. "rotation=(%.5f,%.5f,%.5f,%.5f)%s", tostring(pose.sequence), read_p.x, read_p.y, read_p.z,
            read_q.x, read_q.y, read_q.z, read_q.w, detail))
    end
    campaign_verified = campaign_enabled()
end

local function update_avatar(player, pose, viewer_role)
    if avatar_failed then
        if avatar_cleanup_error then clear_avatar() end
        return
    end
    if not avatar then
        if not last_render_reason then
            last_render_reason = 'renderer_unavailable'
            log.info("RE2_COOP_CAMPAIGN_AVATAR " .. last_render_reason)
        end
        return
    end
    local ok, ready, reason = pcall(avatar.update, avatar, player, pose, viewer_role)
    local detail = ok and (reason or (ready and 'visible' or 'renderer_pending')) or tostring(ready)
    if detail ~= last_render_reason then
        last_render_reason = detail
        log.info("RE2_COOP_CAMPAIGN_AVATAR " .. detail)
    end
    if ok and ready == avatar_visible then return end

    local switched = pcall(function()
        local show_mannequin = not (ok and ready)
        owned_object:call("set_DrawSelf", show_mannequin)
        assert(owned_object:call("get_DrawSelf") == show_mannequin)
    end)
    if not ok or not switched then
        avatar_failed = true
        clear_avatar()
        pcall(owned_object.call, owned_object, "set_DrawSelf", true)
        avatar_visible = false
        return
    end
    avatar_visible = ready
end

local function advance_avatar()
    if not avatar_visible then return end
    local player = current_player()
    if not pose_is_fresh(accepted_pose) or not player or player:get_address() ~= local_player_address
        or campaign.scene_address() ~= local_scene_address then
        remove_test_object()
        return
    end
    if avatar:advance() == false then
        avatar_visible = false
        if owned_object then owned_object:call("set_DrawSelf", true) end
    end
end

local function update_test(player, pose, sample_due, viewer_role)
    if not test_enabled and not campaign_enabled() then
        if remove_test_object() then accepted_pose = nil end
        local_player_address, local_scene_address = nil, nil
        return
    end
    local playing_campaign = campaign_enabled()
    if playing_campaign and pose == nil then remove_test_object(); return end
    local address = player and player:get_address()
    local scene_address = address and campaign.scene_address()
    if playing_campaign and (address ~= local_player_address or scene_address ~= local_scene_address) then
        remove_test_object()
        return
    end
    if address == nil or address == 0 or (local_player_address ~= nil and address ~= local_player_address) then
        error("local campaign player unavailable or changed")
    end
    local_player_address = address
    if scene_address == nil or scene_address == 0 or
        (local_scene_address ~= nil and scene_address ~= local_scene_address) then
        error("local scene unavailable or changed")
    end
    local_scene_address = scene_address
    if pose == nil then
        if remove_test_object() then test_status = "Waiting for a fresh remote pose" end
        return
    end
    local same_pose = validate_test_pose(pose)
    if pending_readback ~= nil then
        if pose_is_fresh(pending_readback) then
            verify_test_pose(pending_readback)
        else
            if remove_test_object() then test_status = "Waiting for a fresh remote pose" end
            return
        end
    end
    if sample_due then
        apply_test_pose(pose, same_pose)
        if playing_campaign then update_avatar(player, pose, viewer_role) end
    end
end

local function set_test_enabled(enabled)
    test_enabled = enabled
    test_status = enabled and "Waiting for a fresh remote pose" or "Disabled"
end

local function terminal_command(player)
    if campaign_enabled() then return end
    local ok, contents = pcall(fs.read, command_filename)
    if not ok or type(contents) ~= "string" or #contents > 512 then return end
    local decoded, command = pcall(json.load_string, contents)
    if not decoded or type(command) ~= "table" or command.schema ~= 1
        or (command.action ~= "start" and command.action ~= "stop")
        or type(command.nonce) ~= "string" or #command.nonce < 16 or #command.nonce > 64
        or not fresh(command.issued_at) or command.issued_at % 1 ~= 0
        or command.nonce == last_command_nonce then return end
    last_command_nonce = command.nonce
    if command.action == "stop" then
        set_test_enabled(false)
        if remove_test_object() then log.info("RE2_COOP_GUEST_OBJECT terminal stop completed") end
    elseif player == nil then
        log.info("RE2_COOP_GUEST_OBJECT terminal start requires a loaded campaign player")
    elseif test_enabled or owned_object ~= nil then
        log.info("RE2_COOP_GUEST_OBJECT terminal start requires the previous test to be stopped")
    else
        mannequin_enabled = true
        set_test_enabled(true)
        log.info("RE2_COOP_GUEST_OBJECT terminal start accepted")
    end
end

re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    local sample_due = updates % 6 == 0
    if not sample_due and pending_readback == nil then
        local ok, err = pcall(advance_avatar)
        if not ok then
            log.info("RE2_COOP_CAMPAIGN_AVATAR interpolation stopped: " .. tostring(err))
            remove_test_object()
        end
        return
    end
    local ok, player = pcall(current_player)
    if sample_due then terminal_command(ok and player or nil) end
    marker = nil
    if ok and player ~= nil then
        local read_ok, result = pcall(read_marker)
        if read_ok then marker = result end
    end
    local pose = pose_is_fresh(marker) and marker or nil
    local viewer_role
    if not campaign_retired then
        local checked, scope, context, reason = pcall(campaign_for_pose, pose, ok and player or nil)
        if not checked then reason = 'release_scope_read_failed' end
        if reason ~= last_admission_reason then
            last_admission_reason = reason
            if reason then log.info("RE2_COOP_CAMPAIGN_POSE " .. reason) end
        end
        if checked and scope ~= nil and campaign_id == nil then
            -- Dispose any diagnostic object before giving the campaign ownership.
            set_test_enabled(false)
            if remove_test_object() then
                accepted_pose = nil
                local_player_address, local_scene_address, campaign_area = nil, nil, nil
                campaign_id = scope.request_id
            end
        end
        if campaign_enabled() then
            if not checked or not context or scope.request_id ~= campaign_id then pose = nil
            elseif context.player_address ~= local_player_address or context.scene_address ~= local_scene_address
                or not campaign.same_area(context.area, campaign_area) then
                if remove_test_object() then
                    local_player_address, local_scene_address = context.player_address, context.scene_address
                    campaign_area = context.area
                    waiting_for_campaign_area = false
                else
                    pose = nil
                end
            end
            if pose then viewer_role = scope.role end
        end
    end
    local test_ok, err = pcall(update_test, ok and player or nil, pose, sample_due, viewer_role)
    if not test_ok then
        if campaign_enabled() then campaign_retired = true end
        test_enabled = false
        local_player_address, local_scene_address = nil, nil
        test_status = "Test stopped. See the REFramework log."
        log.info("RE2_COOP_GUEST_OBJECT " .. tostring(err))
        if remove_test_object() then accepted_pose = nil end
    end
    if campaign_id ~= nil and not test_enabled then marker = nil end
end)

re.on_draw_ui(function()
    if not imgui.tree_node("RE2 Coop - remote pose") then return end
    if not campaign_enabled() and not test_enabled and owned_object == nil then
        local changed, enabled = imgui.checkbox("Attach the stock mannequin", mannequin_enabled)
        if changed then mannequin_enabled = enabled end
    end
    if not campaign_enabled() then
        local changed, enabled = imgui.checkbox("Apply pose to a test object (TDB 70)", test_enabled)
        if changed and cleanup_error == nil then set_test_enabled(enabled) end
    end
    imgui.text(test_status)
    imgui.text(owned_object == nil and "Test object: absent" or "Test object: present")
    imgui.tree_pop()
end)

re.on_script_reset(function()
    test_enabled = false
    remove_test_object()
end)

re.on_frame(function()
    if not pose_is_fresh(marker) then
        marker = nil
        return
    end
    local origin = draw.world_to_screen(marker.origin)
    if origin == nil or not (valid_number(origin.x) and valid_number(origin.y)) then return end
    draw.text(marker.label, origin.x, origin.y, color)
    local tip = draw.world_to_screen(marker.tip)
    if tip ~= nil and valid_number(tip.x) and valid_number(tip.y) then
        draw.line(origin.x, origin.y, tip.x, tip.y, color)
    end
end)
