local path = "reframework/autorun/re2_coop_guest_pose.lua"

local function fixture()
    local f = {
        now = 100,
        game = "re2",
        player = true,
        markers = {},
        lines = {},
        logs = {},
        created = 0,
        destroyed = 0,
        resource_loads = 0,
        mesh_components = 0,
        document = {
            schema = 1, player_id = "claire", connected = true, written_at = 100,
            session_id = "test", sequence = 1,
            pose = {position = {1, 2, 3}, rotation = {0, 0, 0, 1}},
        },
    }
    local transform = {
        set_position = function(self, value, no_dirty)
            assert(value.w == 1 and no_dirty == false)
            if not f.ignore_position then self.position = value end
            f.writes = (f.writes or 0) + 1
        end,
        set_rotation = function(self, value) self.rotation = value end,
        get_position = function(self)
            if f.overwrite_position then return {x = 0, y = 0, z = 0} end
            return self.position or {x = 0, y = 0, z = 0}
        end,
        get_rotation = function(self)
            local q = self.rotation
            -- Native readback may use the equivalent opposite quaternion.
            return {x = -q.x, y = -q.y, z = -q.z, w = -q.w}
        end,
    }
    local mannequin_path = "objectroot/setmodel/sm3x_artifactprops/sm32/sm32_256_mannequin01a/"
        .. "sm32_256_mannequin01a_00ms"
    local mesh_holder = "via.render.MeshResourceHolder"
    local material_holder = "via.render.MeshMaterialResourceHolder"
    local function instance_method(param_count, call)
        return {
            get_num_params = function() return param_count end,
            is_static = function() return false end,
            call = call,
        }
    end
    local object, component = {}, {}
    function object:call(method)
        assert(method == "get_Transform")
        return transform
    end
    local local_player = {get_address = function() return f.player_address or 10 end}
    local env = setmetatable({
        reframework = {get_game_name = function() return f.game end},
        sdk = {
            get_tdb_version = function() return f.tdb or 70 end,
            is_managed_object = function(value) return value == object or value == component end,
            get_native_singleton = function(name)
                assert(name == "via.SceneManager")
                return {}
            end,
            call_native_func = function(_, scene_type, method)
                assert(scene_type.name == "via.SceneManager" and method == "get_CurrentScene")
                return {get_address = function() return f.scene_address or 20 end}
            end,
            find_type_definition = function(name)
                if name == "via.SceneManager" then return {name = name} end
                if name == "via.Transform" then
                    return {get_method = function(_, method)
                        assert(method == "set_Position" or method == "set_Rotation")
                        if not f.no_setters then return {} end
                    end}
                end
                if name == "via.render.Mesh" then
                    return {
                        get_runtime_type = function() return name end,
                        get_method = function(_, method)
                            if method == "setMesh(" .. mesh_holder .. ")" then
                                return instance_method(1, function(_, receiver, value)
                                    assert(receiver == component and value.type == mesh_holder)
                                    component.mesh = value
                                end)
                            elseif method == "set_Material(" .. material_holder .. ")" then
                                if f.no_material_setter then return nil end
                                return instance_method(1, function(_, receiver, value)
                                    assert(receiver == component and value.type == material_holder)
                                    if f.fail_material_setter then error("material assignment failed") end
                                    component.material = value
                                end)
                            elseif method == "getMesh()" then
                                return instance_method(0, function(_, receiver)
                                    assert(receiver == component)
                                    return component.mesh
                                end)
                            end
                            assert(method == "get_Material()")
                            return instance_method(0, function(_, receiver)
                                assert(receiver == component)
                                if not f.lose_material then
                                    if f.material_label then
                                        return {
                                            get_address = function() return 32 end,
                                            call = function() return "Resource [@" .. f.material_label .. "]" end,
                                        }
                                    end
                                    return component.material
                                end
                            end)
                        end,
                    }
                end
                assert(name == "via.GameObject")
                return {get_method = function(_, method)
                    if method == "create(System.String)" then
                        return {is_static = function() return true end,
                            call = function(_, receiver, object_name)
                                assert(receiver == nil and object_name == "RE2CoopRemotePoseTest")
                                f.created = f.created + 1
                                return object
                            end}
                    end
                    if method == "createComponent(System.Type)" then
                        return instance_method(1, function(_, receiver, runtime_type)
                            assert(receiver == object and runtime_type == "via.render.Mesh")
                            f.mesh_components = f.mesh_components + 1
                            return component
                        end)
                    end
                    if method ~= "destroy(via.GameObject)" then return nil end
                    if f.no_destroy then return nil end
                    return {
                        is_static = function() return true end,
                        get_num_params = function() return 1 end,
                        call = function(_, receiver, target)
                            assert(receiver == nil and target == object)
                            if f.fail_destroy then error("cleanup failed") end
                            f.destroyed = f.destroyed + 1
                        end,
                    }
                end}
            end,
            create_resource = function(resource_type, path)
                f.resource_loads = f.resource_loads + 1
                local is_mesh = resource_type == "via.render.MeshResource"
                assert(is_mesh or resource_type == "via.render.MeshMaterialResource")
                assert(path == mannequin_path .. (is_mesh and ".mesh" or "_mat.mdf2"))
                if f.no_material_resource and not is_mesh then return nil end
                local function create_holder(_, holder_type)
                    assert(holder_type == (is_mesh and mesh_holder or material_holder))
                    return {
                        type = holder_type,
                        get_address = function() return is_mesh and 30 or 31 end,
                    }
                end
                return {create_holder = create_holder, create_holder_global = create_holder}
            end,
            game_namespace = function(name) return name end,
            get_managed_singleton = function(name)
                assert(name == "PlayerManager")
                return {call = function(_, method)
                    assert(method == "get_CurrentPlayer")
                    if f.player then return local_player end
                end}
            end,
        },
        os = {time = function() return f.now end},
        re = {
            on_pre_application_entry = function(name, callback)
                assert(name == "UpdateBehavior")
                f.update = callback
            end,
            on_frame = function(callback) f.draw = callback end,
            on_draw_ui = function(callback) f.ui = callback end,
            on_script_reset = function(callback) f.reset = callback end,
        },
        fs = {read = function(filename)
            assert(filename == "re2_coop_guest_pose.json")
            if f.bad_read then error("invalid file") end
            return "fixture"
        end},
        json = {load_string = function(contents)
            assert(contents == "fixture")
            return f.document
        end},
        Vector3f = {new = function(x, y, z) return {x = x, y = y, z = z} end},
        Vector4f = {new = function(x, y, z, w) return {x = x, y = y, z = z, w = w} end},
        Quaternion = {new = function(w, x, y, z) return {w = w, x = x, y = y, z = z} end},
        imgui = {
            tree_node = function() return true end,
            tree_pop = function() end,
            text = function() end,
            checkbox = function(label, current)
                if label == "Attach the stock mannequin" then
                    if f.toggle_mannequin == nil then return false, current end
                    local next_value = f.toggle_mannequin
                    f.toggle_mannequin = nil
                    return true, next_value
                end
                if f.toggle == nil then return false, current end
                local next_value = f.toggle
                f.toggle = nil
                return true, next_value
            end,
        },
        log = {info = function(message) f.logs[#f.logs + 1] = message end},
        draw = {
            text = function(label, x, y)
                f.markers[#f.markers + 1] = {label = label, x = x, y = y}
            end,
            world_to_screen = function(position)
                if f.bad_projection then return {x = math.huge, y = 0} end
                return {x = position.x, y = position.z}
            end,
            line = function(x1, y1, x2, y2)
                f.lines[#f.lines + 1] = {x1, y1, x2, y2}
            end,
        },
    }, {__index = _G})
    assert(loadfile(path, "t", env))()
    return f
end

local function render(f)
    f.markers, f.lines = {}, {}
    for _ = 1, 6 do f.update() end
    f.draw()
end

local function close_to(actual, expected)
    assert(math.abs(actual - expected) < 0.0001, tostring(actual))
end

local f = fixture()
render(f)
assert(#f.markers == 1 and f.markers[1].label:find("claire", 1, true))
assert(f.markers[1].x == 1 and f.markers[1].y == 3)
assert(#f.lines == 1)
local length = f.lines[1][4] - f.lines[1][2]
assert(length > 0)

-- A quarter turn around +Y rotates the +Z diagnostic axis toward +X.
f.document.pose.rotation = {0, math.sqrt(0.5), 0, math.sqrt(0.5)}
render(f)
close_to(f.lines[1][3] - f.lines[1][1], length)
close_to(f.lines[1][4] - f.lines[1][2], 0)
print("ok - world marker tracks position and quaternion rotation")

f.now = 107
render(f)
assert(#f.markers == 0 and #f.lines == 0)
f.document.written_at = f.now
render(f)
assert(#f.markers == 1)
f.document.connected = false
render(f)
assert(#f.markers == 0)
print("ok - marker disappears when the lease expires or guest disconnects")

f.document.connected = true
f.player = false
render(f)
assert(#f.markers == 0)
f.player, f.bad_read = true, true
render(f)
assert(#f.markers == 0)
f.bad_read = false
f.document.pose.rotation = {0, 0, 0, 0}
render(f)
assert(#f.markers == 0)
f.document.pose.rotation = {0, 0, 0, 1}
f.document.pose.position = {1e39, 2, 3}
render(f)
assert(#f.markers == 0)
f.document.pose.position = {1, 2, 3}
f.game = "re3"
render(f)
assert(#f.markers == 0)
print("ok - marker requires RE2, a loaded player and valid pose data")

f.game, f.bad_projection = "re2", true
render(f)
assert(#f.markers == 0 and #f.lines == 0)
print("ok - rejects a non-finite screen projection")

local function enable(guest)
    guest.toggle = true
    guest.ui()
end

local guest = fixture()
render(guest)
assert(guest.created == 0)
enable(guest)
assert(guest.created == 0, "engine object created in the UI callback")
render(guest)
assert(guest.created == 1 and guest.writes == 1)
guest.update()
assert(guest.logs[#guest.logs]:find("verified", 1, true))
guest.document.written_at = 101
guest.now = 101
render(guest)
assert(guest.writes == 1, "heartbeat reapplied an unchanged transform")
guest.document.pose.position[1] = 4
guest.document.pose.rotation = {0, 0.6, 0, 0.8}
guest.document.sequence = 2
render(guest)
assert(guest.writes == 2 and guest.destroyed == 0)
guest.document.connected = false
render(guest)
assert(guest.destroyed == 1)
guest.document.connected = true
render(guest)
assert(guest.created == 2)
guest.reset()
assert(guest.destroyed == 2)
print("ok - opt-in owned engine object follows verified poses and is removed on disconnect or reset")

guest = fixture()
guest.no_destroy = true
enable(guest)
render(guest)
assert(guest.created == 0, "created an object without a cleanup method")
guest = fixture()
guest.tdb = 69
enable(guest)
render(guest)
assert(guest.created == 0)
guest = fixture()
guest.no_setters = true
enable(guest)
render(guest)
assert(guest.created == 0, "created an object without Transform setters")
guest = fixture()
guest.ignore_position = true
enable(guest)
render(guest)
render(guest)
assert(guest.created == 1 and guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("mismatch", 1, true))
print("ok - missing APIs and unsupported TDB prevent writes and readback mismatch disarms the test")

guest = fixture()
enable(guest)
render(guest)
guest.player_address = 11
guest.fail_destroy = true
render(guest)
assert(guest.created == 1 and guest.destroyed == 0)
guest.fail_destroy = false
render(guest)
assert(guest.destroyed == 1 and guest.created == 1)
print("ok - local player replacement disarms the test and retries cleanup")

guest = fixture()
enable(guest)
render(guest)
guest.document.pose.position[1] = 10
render(guest)
assert(guest.writes == 1 and guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("same sequence", 1, true))
guest = fixture()
guest.document.sequence = 2
enable(guest)
render(guest)
guest.now = 107
render(guest)
assert(guest.destroyed == 1)
guest.document.written_at = 107
guest.document.sequence = 1
render(guest)
assert(guest.created == 1 and guest.writes == 1)
assert(guest.logs[#guest.logs]:find("backwards", 1, true))
print("ok - pose sequence guards survive lease expiry and reject changed data at the same sequence")

guest = fixture()
enable(guest)
render(guest)
guest.document.session_id = "other"
guest.document.sequence = 2
render(guest)
assert(guest.writes == 1 and guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("remote session or player changed", 1, true))
print("ok - remote session replacement requires opting in again")

guest = fixture()
enable(guest)
render(guest)
guest.scene_address = 21
render(guest)
assert(guest.writes == 1 and guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("local scene", 1, true))
print("ok - scene replacement disarms even when the local player object stays the same")

f = fixture()
f.document.observed_at = 100
render(f)
assert(#f.markers == 1)
f.now = 106
f.markers, f.lines = {}, {}
f.draw()
assert(#f.markers == 0 and #f.lines == 0)
f.document.written_at = 106
render(f)
assert(#f.markers == 0)
f.document.observed_at = 106
render(f)
assert(#f.markers == 1)
print("ok - source observation expires even with a fresh local file")

guest = fixture()
enable(guest)
for _ = 1, 6 do guest.update() end
assert(guest.writes == 1)
assert(#guest.logs == 0, "reported success before the engine could update")
guest.overwrite_position = true
guest.update()
assert(guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("mismatch", 1, true))
print("ok - detects a transform overwritten between engine callbacks")

guest = fixture()
guest.document.observed_at = 95
enable(guest)
for _ = 1, 6 do guest.update() end
assert(guest.created == 1 and guest.writes == 1)
guest.now = 101
guest.update()
assert(guest.destroyed == 1 and #guest.logs == 0)
print("ok - expired source cancels pending readback and removes the test object")

guest = fixture()
enable(guest)
for _ = 1, 6 do guest.update() end
guest.document.connected = false
guest.update()
assert(guest.destroyed == 1 and #guest.logs == 0)
print("ok - a disconnect published between callbacks cancels pending readback")

guest = fixture()
guest.toggle_mannequin = true
guest.ui()
render(guest)
assert(guest.resource_loads == 0, "loaded the mannequin before starting the test")
enable(guest)
render(guest)
assert(guest.resource_loads == 2 and guest.mesh_components == 1, "missing mannequin render component")
assert(#guest.logs == 0, "verified before the engine update")
guest.update()
assert(guest.logs[#guest.logs]:find("mannequin resources assigned", 1, true))
guest.document.sequence = 2
guest.document.pose.position[1] = 4
render(guest)
assert(guest.resource_loads == 2 and guest.mesh_components == 1 and guest.writes == 2)
guest.document.connected = false
render(guest)
assert(guest.destroyed == 1)
print("ok - mannequin binds to the owned pose object and is removed on disconnect")

for _, failure in ipairs({"no_material_setter", "no_material_resource", "fail_material_setter", "lose_material"}) do
    guest = fixture()
    guest[failure] = true
    guest.toggle_mannequin = true
    guest.ui()
    enable(guest)
    render(guest)
    guest.update()
    local failed_before_create = failure == "no_material_setter" or failure == "no_material_resource"
    local expected_objects = failed_before_create and 0 or 1
    assert(guest.created == expected_objects and guest.destroyed == expected_objects)
    assert(#guest.logs == 1 and not guest.logs[1]:find("verified", 1, true))
end
print("ok - missing or lost mannequin resources stop the test and clean up")

guest = fixture()
guest.toggle_mannequin = true
guest.ui()
enable(guest)
render(guest)
guest.update()
assert(guest.logs[#guest.logs]:find("mannequin resources assigned", 1, true))
guest.lose_material = true
guest.document.written_at = 101
guest.now = 101
render(guest)
assert(guest.writes == 1 and guest.destroyed == 1)
assert(guest.logs[#guest.logs]:find("mannequin resource readback mismatch", 1, true))
print("ok - a stationary guest detects material loss after a successful readback")

for _, suffix in ipairs({"", ".backup"}) do
    guest = fixture()
    guest.material_label = "NATIVES\\STM\\OBJECTROOT\\SETMODEL\\SM3X_ARTIFACTPROPS\\SM32\\SM32_256_MANNEQUIN01A\\"
        .. "SM32_256_MANNEQUIN01A_00MS_MAT.MDF2.21" .. suffix
    guest.toggle_mannequin = true
    guest.ui()
    enable(guest)
    render(guest)
    guest.update()
    assert(guest.destroyed == (suffix == "" and 0 or 1))
end
print("ok - accepts an equivalent resource holder and rejects a similar path")
print("18 Lua guest pose tests, 0 failures")
