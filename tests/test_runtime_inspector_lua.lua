local script = "reframework/diagnostics/re2_coop_runtime_inspector.lua"
local output, reset, writes, now = nil, nil, 0, 21
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

local renderer = {}
local env = setmetatable({os={time=function() return now end},
    require=function(module) assert(module=="re2_coop.campaign_avatar"); return renderer end,
    reframework={get_game_name=function() return "re2" end},
    re={on_script_reset=function(fn) reset=fn end},
    json={dump_file=function(path, data)
        assert(path=="re2_coop_dev_inspector.json"); writes=writes+1; output=data
    end},
    sdk={get_tdb_version=function() return 70 end, typeof=function(name) return name end}}, {__index=_G})
assert(loadfile(script, "t", env))()
assert(writes==0)
renderer.on_inspector_sample(true,player,player)
renderer.on_inspector_sample(true,player,player)
assert(writes==1 and output.player.joints_constructed and output.preview.mesh_id=="pl0001")
assert(output.player.frame==2.5 and output.preview.draw_self and output.partner==nil)
renderer.on_inspector_sample(false,player,nil)
assert(writes==2 and output.partner.present==false and output.preview.present==true)
now=22; renderer.on_inspector_sample(false,player,getter({}))
assert(output.partner.read_error and output.preview==nil)
reset(); assert(renderer.on_inspector_sample==nil)
print("Runtime inspector: owned actors, mesh and animation readback, sampling limit and teardown passed")
