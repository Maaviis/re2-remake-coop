-- Draw the selected remote pose. The optional write test owns a separate empty object.
if reframework:get_game_name() ~= "re2" then return end

local filename = "re2_coop_guest_pose.json"
local max_age = 5
local max_component = 3.4028234663852886e38
local color = 0xFF64E8FF
local axis_length = 0.7
local updates = 0
local marker
local test_enabled = false
local test_status = "Disabled"
local owned_object
local destroy_object
local accepted_pose
local pending_readback
local local_player_address
local local_scene_address
local cleanup_error

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

local function fresh(timestamp)
    if type(timestamp) ~= "number" then return false end
    local age = os.time() - timestamp
    return age >= 0 and age <= max_age
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
    return {
        label = "Remote pose: " .. data.player_id,
        timestamp = data.written_at,
        observed_at = data.observed_at,
        session_id = data.session_id,
        sequence = data.sequence,
        player_id = data.player_id,
        rotation = {x = x, y = y, z = z, w = w},
        origin = Vector3f.new(position[1], position[2], position[3]),
        tip = Vector3f.new(position[1] + axis_length * dx, position[2] + axis_length * dy,
            position[3] + axis_length * dz),
    }
end

local function current_player()
    if reframework:get_game_name() ~= "re2" then return nil end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    if manager ~= nil then return manager:call("get_CurrentPlayer") end
end

local function remove_test_object()
    pending_readback = nil
    if owned_object == nil then return true end
    local ok, err = pcall(function()
        if sdk.is_managed_object(owned_object) then
            destroy_object:call(owned_object)
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
    owned_object, destroy_object, cleanup_error = nil, nil, nil
    return true
end

local function same_vector(a, b)
    return a.x == b.x and a.y == b.y and a.z == b.z
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
        if pose.sequence == accepted_pose.sequence and not same_pose then
            error("remote pose changed at the same sequence")
        end
    end
    return same_pose
end

local function apply_test_pose(pose, same_pose)
    if owned_object ~= nil and same_pose then
        accepted_pose = pose
        return
    end
    if owned_object == nil then
        local object_type = sdk.find_type_definition("via.GameObject")
        local create = object_type and object_type:get_method("create(System.String)")
        local destroy = object_type and (object_type:get_method("destroy()") or object_type:get_method("destroy"))
        if create == nil or not create:is_static() or destroy == nil or
            destroy:is_static() or destroy:get_num_params() ~= 0 then
            error("GameObject creation or cleanup API unavailable")
        end
        local transform_type = sdk.find_type_definition("via.Transform")
        if transform_type == nil or transform_type:get_method("set_Position") == nil
            or transform_type:get_method("set_Rotation") == nil then
            error("Transform setters unavailable")
        end
        owned_object = create:call(nil, "RE2CoopRemotePoseTest")
        destroy_object = destroy
        if owned_object == nil then error("could not create test object") end
    end

    local transform = owned_object:call("get_Transform")
    if transform == nil then error("test object has no transform") end
    local p, q = pose.origin, pose.rotation
    transform:set_position(Vector4f.new(p.x, p.y, p.z, 1), false)
    transform:set_rotation(Quaternion.new(q.w, q.x, q.y, q.z))

    accepted_pose = pose
    pending_readback = pose
    test_status = "Waiting for the next engine update"
end

local function verify_test_pose(pose)
    if not sdk.is_managed_object(owned_object) then error("test object no longer exists") end
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

    pending_readback = nil
    test_status = "Transform verified at sequence " .. tostring(pose.sequence)
    log.info(string.format("RE2_COOP_GUEST_OBJECT verified tdb=70 sequence=%s position=(%.3f,%.3f,%.3f) "
        .. "rotation=(%.5f,%.5f,%.5f,%.5f)", tostring(pose.sequence), read_p.x, read_p.y, read_p.z,
        read_q.x, read_q.y, read_q.z, read_q.w))
end

local function update_test(player, pose, sample_due)
    if not test_enabled then
        if remove_test_object() then accepted_pose = nil end
        local_player_address, local_scene_address = nil, nil
        return
    end
    local address = player and player:get_address()
    if address == nil or address == 0 or (local_player_address ~= nil and address ~= local_player_address) then
        error("local campaign player unavailable or changed")
    end
    local_player_address = address
    local scene_manager = sdk.get_native_singleton("via.SceneManager")
    local scene_type = sdk.find_type_definition("via.SceneManager")
    local scene = scene_manager and scene_type
        and sdk.call_native_func(scene_manager, scene_type, "get_CurrentScene")
    local scene_address = scene and scene:get_address()
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
    if sample_due then apply_test_pose(pose, same_pose) end
end

re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    local sample_due = updates % 6 == 0
    if not sample_due and pending_readback == nil then return end
    local ok, player = pcall(current_player)
    marker = nil
    if ok and player ~= nil then
        local read_ok, result = pcall(read_marker)
        if read_ok then marker = result end
    end
    local pose = pose_is_fresh(marker) and marker or nil
    local test_ok, err = pcall(update_test, ok and player or nil, pose, sample_due)
    if not test_ok then
        test_enabled = false
        local_player_address, local_scene_address = nil, nil
        test_status = "Test stopped. See the REFramework log."
        log.info("RE2_COOP_GUEST_OBJECT " .. tostring(err))
        if remove_test_object() then accepted_pose = nil end
    end
end)

re.on_draw_ui(function()
    if not imgui.tree_node("RE2 Coop - remote pose") then return end
    local changed, enabled = imgui.checkbox("Apply pose to an empty test object (TDB 70)", test_enabled)
    if changed and cleanup_error == nil then
        test_enabled = enabled
        test_status = enabled and "Waiting for a fresh remote pose" or "Disabled"
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
