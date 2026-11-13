-- Draw the selected remote player's diagnostic pose without changing game objects.
if reframework:get_game_name() ~= "re2" then return end

local filename = "re2_coop_guest_pose.json"
local max_age = 5
local max_component = 3.4028234663852886e38
local color = 0xFF64E8FF
local axis_length = 0.7
local updates = 0
local marker

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
        origin = Vector3f.new(position[1], position[2], position[3]),
        tip = Vector3f.new(position[1] + axis_length * dx, position[2] + axis_length * dy,
            position[3] + axis_length * dz),
    }
end

local function read_in_campaign()
    if reframework:get_game_name() ~= "re2" then return nil end
    local manager = sdk.get_managed_singleton(sdk.game_namespace("PlayerManager"))
    if manager == nil or manager:call("get_CurrentPlayer") == nil then return nil end
    return read_marker()
end

re.on_pre_application_entry("UpdateBehavior", function()
    updates = updates + 1
    if updates % 6 ~= 0 then return end
    local ok, result = pcall(read_in_campaign)
    marker = ok and result or nil
end)

re.on_frame(function()
    if marker == nil then return end
    if not fresh(marker.timestamp) or (marker.observed_at ~= nil and not fresh(marker.observed_at)) then
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
