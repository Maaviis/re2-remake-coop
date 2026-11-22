local path = "reframework/autorun/re2_coop_guest_pose.lua"

local function fixture(with_avatar)
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
        stock_drawn = true,
        avatar_updates = 0,
        avatar_clears = 0,
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
    function object:call(method, argument)
        if method == "set_DrawSelf" then f.stock_drawn = argument; return end
        if method == "get_DrawSelf" then return f.stock_drawn end
        assert(method == "get_Transform")
        return transform
    end
    local local_player = {get_address = function() return f.player_address or 10 end}
    local env
    env = setmetatable({
        require = function(name)
            if with_avatar and name == "re2_coop.campaign_avatar" then
                return {
                    valid_motion = function(candidate) return type(candidate) == "table" and candidate.id == 160 end,
                    new = function()
                        return {
                            update = function(_, player, pose)
                                assert(player == local_player)
                                f.avatar_updates = f.avatar_updates + 1
                                f.avatar_pose = pose
                                return f.avatar_ready == true and pose.motion ~= nil
                            end,
                            clear = function()
                                if f.fail_avatar_clear then error('avatar still belongs to the departed room') end
                                f.avatar_clears = f.avatar_clears + 1
                            end,
                        }
                    end,
                }
            end
            assert(name == "re2_coop.campaign_pose_scope")
            return assert(loadfile("reframework/autorun/re2_coop/campaign_pose_scope.lua", "t", env))()
        end,
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
                                local expected = f.campaign_object and "RE2CoopRemotePlayer" or "RE2CoopRemotePoseTest"
                                assert(receiver == nil and object_name == expected)
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
            if filename == "re2_coop_guest_pose_command.json" then
                return f.command and "command" or nil
            end
            if filename == "re2_coop_save_guard.json" then return f.guard and "guard" or nil end
            if filename == "re2_coop_native_peer.json" then return f.peer and "peer" or nil end
            if filename == "re2_coop_observer.json" then return f.observer and "observer" or nil end
            assert(filename == "re2_coop_guest_pose.json")
            if f.bad_read then error("invalid file") end
            return "fixture"
        end},
        json = {load_string = function(contents)
            if contents == "command" then return f.command end
            if contents == "guard" then return f.guard end
            if contents == "peer" then return f.peer end
            if contents == "observer" then return f.observer end
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
    dofile("tests/campaign_area_fixture.lua")(env.sdk, f)
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

guest = fixture()
guest.command = {schema = 1, action = "start", nonce = "start-mannequin-01", issued_at = guest.now}
render(guest)
assert(guest.created == 1 and guest.mesh_components == 1, "terminal start did not attach the mannequin")
guest.update()
assert(guest.logs[#guest.logs]:find("mannequin resources assigned", 1, true))
guest.document.sequence = 2
guest.document.pose.position[1] = 5
guest.document.pose.rotation = {0, math.sqrt(0.5), 0, math.sqrt(0.5)}
render(guest)
guest.update()
assert(guest.created == 1 and guest.writes == 2 and guest.logs[#guest.logs]:find("sequence=2", 1, true))
guest.command = {schema = 1, action = "stop", nonce = "stop-mannequin-001", issued_at = guest.now}
render(guest)
assert(guest.destroyed == 1)
print("ok - terminal start tracks pose and rotation and terminal stop removes the mannequin")

guest = fixture()
guest.command = {schema = 1, action = "start", nonce = "start-mannequin-02", issued_at = guest.now - 6}
render(guest)
assert(guest.created == 0, "accepted an expired command")
guest.command.issued_at = guest.now
guest.player = false
render(guest)
assert(guest.created == 0 and guest.logs[#guest.logs]:find("loaded campaign player", 1, true))
guest.player = true
render(guest)
assert(guest.created == 0, "replayed terminal start after loading the player")
guest.command.nonce = "start-mannequin-03"
render(guest)
assert(guest.created == 1)
guest.document.connected = false
render(guest)
assert(guest.destroyed == 1)
print("ok - terminal start requires a fresh command and a campaign player and still clears on disconnect")

local function campaign_peer(role, with_avatar)
    local guest = fixture(with_avatar)
    guest.campaign_object = true
    local id, native_epoch, attempt = string.rep('a', 32), string.rep('b', 16), string.rep('e', 32)
    guest.guard = {schema=1, at=guest.now, active=true, protection_active=true, in_title=false, has_player=true,
        load_phase='scene_loaded', load_error='', policy_id=id, load_request_id=id,
        guard_run_id='current-guard', protection={game_pid=123, run_id=string.rep('d', 32)},
        load_hold={schema=1, scope='prepared_load_native_pause', observed_at=guest.now, phase='released',
            native_phase='released', load_request_id=id, pause_id=id, guard_run_id='current-guard',
            campaign={session_id=guest.document.session_id, attempt_id=attempt, scenario=1, game_pid=123, role=role, revision=7,
                snapshot_epoch=native_epoch, protection_run_id=string.rep('d', 32),
                local_player='10', local_scene='20'}}}
    guest.peer = {schema=1, at=guest.now, game_pid=123, role=role, revision=7, snapshot_epoch=native_epoch}
    guest.document.observed_at = guest.now
    guest.document.pose.campaign_attempt_id = attempt
    guest.document.pose.observer_run_id = 'peer-observer'
    guest.document.pose.observer_sequence = 1
    guest.native_area = {scenario=1, map=112, area=5}
    guest.observer = {schema=1, source='re2', tdb=70, available=true, observed_at=guest.now,
        campaign_attempt_id=attempt, campaign_area=guest.native_area,
        campaign_local_context={request_id=id, player='10', scene='20'}}
    guest.document.pose.campaign_area = guest.native_area
    return guest
end

for _, role in ipairs({'H', 'G'}) do
    local guest = campaign_peer(role)
    guest.guard.load_hold.phase = 'releasing'
    render(guest)
    assert(guest.created == 0, 'campaign displayed a peer before native release')
    guest.guard.load_hold.phase = 'released'
    local peer_attempt = guest.document.pose.campaign_attempt_id
    guest.document.pose.campaign_attempt_id = nil
    render(guest)
    assert(guest.created == 0 and #guest.markers == 0, 'unreleased remote pose appeared in the campaign')
    guest.document.pose.campaign_attempt_id = peer_attempt
    render(guest)
    guest.update()
    assert(guest.created == 1 and guest.mesh_components == 1 and guest.writes == 1)
    guest.document.sequence = 2
    guest.document.pose.position = {3, 4, 5}
    render(guest)
    guest.update()
    assert(guest.writes == 2 and guest.destroyed == 0)
    guest.document.connected = false
    render(guest)
    assert(guest.destroyed == 1 and #guest.markers == 0)
    guest.document.connected = true
    guest.document.sequence = 3
    render(guest)
    guest.update()
    assert(guest.created == 2 and guest.writes == 3)
    guest.player = false
    render(guest)
    assert(guest.destroyed == 2 and #guest.markers == 0)
    guest.player = true
    render(guest)
    guest.update()
    assert(guest.created == 3, 'the original player may resume after a temporary read gap')
    guest.peer.snapshot_epoch = string.rep('c', 16)
    render(guest)
    assert(guest.destroyed == 3 and #guest.markers == 0)
end
print("ok - both campaign roles show the partner after release and remove it when the native link changes")

do
    local guest = campaign_peer('G', true)
    guest.document.pose.motion = {bank=1000,id=160,name='source_idle',frame=8,end_frame=48}
    guest.guard.load_hold.phase = 'releasing'
    render(guest)
    assert(guest.avatar_updates==0)
    guest.guard.load_hold.phase = 'released'
    render(guest)
    assert(guest.avatar_updates==1 and guest.stock_drawn)
    guest.avatar_ready = true
    render(guest)
    assert(guest.avatar_pose.motion.name=='source_idle' and not guest.stock_drawn)
    guest.document.sequence, guest.document.pose.motion = 2, nil
    render(guest)
    assert(guest.stock_drawn, 'missing clip left the mannequin hidden')
    local clears = guest.avatar_clears
    guest.document.connected=false
    render(guest)
    assert(guest.destroyed==1 and guest.avatar_clears>clears)
end

do
    local guest = campaign_peer('H', true)
    guest.document.pose.motion = {bank=1000,id=160,name='source_idle',frame=8,end_frame=48}
    guest.avatar_ready = true
    render(guest)
    local prior = guest.avatar_updates
    assert(prior==1 and guest.created==1)
    guest.fail_avatar_clear = true
    guest.scene_address = 21
    guest.native_area = {scenario=1,map=119,area=9}
    guest.observer.campaign_area = guest.native_area
    guest.observer.campaign_local_context.scene = '21'
    guest.document.pose.campaign_area = guest.native_area
    guest.document.pose.observer_sequence, guest.document.sequence = 2, 2
    render(guest)
    render(guest)
    assert(guest.avatar_updates==prior and guest.created==1, 'a live avatar crossed into a new scene')
    guest.fail_avatar_clear = false
    render(guest)
    assert(guest.created==2 and guest.avatar_updates==prior+1)
end

local transition = campaign_peer('H')
transition.campaign_object = false
transition.guard.load_hold.phase = 'held'
transition.toggle = true
transition.ui()
render(transition)
transition.update()
assert(transition.created == 1 and transition.mesh_components == 0)
transition.campaign_object = true
transition.guard.load_hold.phase = 'released'
render(transition)
transition.update()
assert(transition.destroyed == 1 and transition.created == 2 and transition.mesh_components == 1,
    'a campaign must replace the bare diagnostic object with the visible partner')
print("ok - authorized campaign playback replaces an existing diagnostic object")

for _, invalid in ipairs({
    function(guest) guest.guard.at = guest.now - 4 end,
    function(guest) guest.guard.protection_active = false end,
    function(guest) guest.guard.in_title = true end,
    function(guest) guest.guard.load_hold.guard_run_id = 'previous-run' end,
    function(guest) guest.guard.protection.run_id = string.rep('e', 32) end,
    function(guest) guest.peer.game_pid = 124 end,
    function(guest) guest.peer.revision = 8 end,
    function(guest) guest.peer.at = guest.now + 1 end,
    function(guest) guest.document.session_id = 'previous-session' end,
    function(guest) guest.document.pose.campaign_attempt_id = string.rep('f', 32) end,
    function(guest) guest.document.observed_at = nil end,
}) do
    local guest = campaign_peer('H')
    invalid(guest)
    render(guest)
    assert(guest.created == 0 and guest.resource_loads == 0)
end
local guest = campaign_peer('G')
render(guest)
guest.update()
guest.scene_address = 21
guest.player = false
render(guest)
guest.player, guest.scene_address = true, 20
render(guest)
assert(guest.created == 1 and guest.destroyed == 1, 'old campaign evidence survived a local scene replacement')
guest = campaign_peer('H')
guest.document.connected = false
render(guest)
guest.scene_address = 21
guest.document.connected = true
render(guest)
assert(guest.created == 0, 'a first delayed pose must bind to the scene that was released')
print("ok - campaign actor rejects stale, foreign or missing evidence and hides on a local scene change")

guest = campaign_peer('G')
render(guest)
guest.update()
guest.scene_address = 21
guest.native_area = {scenario=1, map=119, area=9}
render(guest)
assert(guest.created == 1 and guest.destroyed == 1, 'stale local area retained the partner')
guest.observer.campaign_area = guest.native_area
guest.observer.campaign_local_context.scene = '21'
render(guest)
assert(guest.created == 1, 'peer in the previous area was displayed in the new scene')
guest.document.sequence = 2
guest.document.pose.observer_sequence = 2
guest.document.pose.campaign_area = guest.native_area
render(guest)
guest.update()
assert(guest.created == 2 and guest.mesh_components == 2, 'the partner did not join the confirmed new area')
print("ok - both peers must report the new native map and area before the partner appears again")

guest = campaign_peer('H')
render(guest)
guest.update()
local original_area = guest.native_area
guest.native_area = {scenario=1, map=112, area=6}
render(guest)
assert(guest.destroyed == 1)
guest.native_area = original_area
guest.document.sequence = 2 -- A local-only replica event advances the envelope sequence.
render(guest)
assert(guest.created == 1, 'replayed peer observation after returning to its area')
guest.document.sequence = 3
guest.document.pose.observer_sequence = 2
render(guest)
guest.update()
assert(guest.created == 2, 'the next actual peer observation should restore the partner')
print("ok - returning to an area requires a new peer observation, even if the old pose is still fresh")
print("25 Lua guest pose test groups, 0 failures")
