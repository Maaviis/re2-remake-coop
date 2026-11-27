local script = "reframework/diagnostics/re2_coop_runtime_inspector.lua"
local callback, output, writes, now = nil, nil, 0, 21
local scene, fail, loading = {}, false, false
local function getter(values)
    return {call=function(_, method, arg)
        assert(values[method] ~= nil, "unexpected engine call: "..method)
        local value = values[method]
        if type(value) == "function" then return value(arg) end
        return value
    end}
end
local node = getter({get_MotionBankID=3, get_MotionID=12, get_Frame=2.5})
local layer = getter({get_HighestWeightMotionNode=node})
local motion = getter({get_JointsConstructed=true, getLayerCount=1, ["getLayer(System.UInt32)"]=layer})
local mesh = getter({get_MeshReady=true, getMesh=getter({["ToString()"]="sectionroot/pl0000/pl0001/pl0001.mesh.2109"})})
local player = getter({get_DrawSelf=true, ["getComponent(System.Type)"]=function(t)
    if t == "via.motion.Motion" then return motion end
    assert(t == "via.render.Mesh"); return mesh
end})
local env = setmetatable({os={time=function() return now end},
    reframework={get_game_name=function() return "re2" end},
    re={on_pre_application_entry=function(name, cb) assert(name=="UpdateBehavior"); callback=cb end},
    json={dump_file=function(path, data)
        assert(path=="re2_coop_dev_inspector.json"); writes=writes+1; output=data
    end},
    sdk={get_tdb_version=function() return 70 end, typeof=function(name) return name end,
        game_namespace=function(name) return name end, get_native_singleton=function() return {} end,
        call_native_func=function() if fail then error("scene changing") end; return scene end,
        get_managed_singleton=function(name)
            if name=="PlayerManager" then return getter({get_CurrentPlayer=player}) end
            assert(name=="app.ropeway.gamemastering.MainFlowManager")
            return getter({get_IsInTitle=false, get_IsInLoadGameData=loading, get_IsFinishedLoadScene=true})
        end,
        find_type_definition=function() return {get_method=function(_, method)
            assert(method=="findGameObject(System.String)")
            return {call=function(_, current, name)
                assert(current==scene)
                if name=="RE2CoopSoloPreview" then return player end
                assert(name=="RE2CoopCampaignAvatar")
            end}
        end} end}}, {__index=_G})
assert(loadfile(script, "t", env))()
callback(); callback()
assert(writes==1 and output.player.joints_constructed and output.preview.mesh_id=="pl0001")
assert(output.player.frame==2.5 and output.preview.draw_self and not output.partner.present)
now=22; scene=nil; callback(); assert(output.status=="scene_unavailable")
now=23; fail=true; callback(); assert(output.status=="read_error" and output.player==nil)
now=24; loading=true; callback(); assert(output.status=="scene_unavailable")
print("Runtime inspector: separate actors, mesh and animation readback, bounded polling and scene loss passed")
