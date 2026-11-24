local f = {scene=11, area={scenario=0,map=174,area=0}, active=false, samples={}, clears=0, logs={}, text={}}
local node_values = {get_MotionBankID=1000,get_MotionID=160,get_MotionName='observed_idle',get_Frame=8,get_EndFrame=200}
local node = {call=function(_,name) return node_values[name] end}
local layer = {call=function(_,name) assert(name=='get_HighestWeightMotionNode'); return node end}
local motion = {call=function(_,name)
    if name=='getLayerCount' then return 1 end
    assert(name=='getLayer(System.UInt32)'); return layer
end}
local transform = {get_position=function() return {x=2,y=3,z=4} end,
    get_rotation=function() return f.rotation or {x=0,y=0,z=0,w=1} end}
local player = {get_address=function() return 10 end,call=function(_,name)
    if name=='get_Transform' then return transform end
    assert(name=='getComponent(System.Type)'); return motion
end}
local env = setmetatable({
    reframework={get_game_name=function() return 're2' end},
    re={on_pre_application_entry=function(entry,fn) assert(entry=='UpdateBehavior'); f.update=fn end,
        on_script_reset=function(fn) f.reset=fn end,on_frame=function(fn) f.draw=fn end},
    sdk={get_tdb_version=function() return 70 end,typeof=function() return 'motion' end,
        game_namespace=function(name) return name end,get_managed_singleton=function(name)
            if name=='PlayerManager' then return {call=function() if not f.no_player then return player end end} end
        end},
    draw={text=function(s) f.text[#f.text+1]=s end},
    log={info=function(s) f.logs[#f.logs+1]=s end},
    require=function(name)
        if name=='re2_coop.cutscene_test_peer' then return {active=function() return f.active end} end
        if name=='re2_coop.campaign_pose_scope' then
            return {scene_address=function() return f.scene end, read_area=function() return f.area end,
                same_area=function(a,b) return a and b and a.scenario==b.scenario and a.map==b.map and a.area==b.area end}
        end
        assert(name=='re2_coop.campaign_avatar')
        return {valid_motion=function(m) return m and m.name=='observed_idle' end,new=function()
            return {update=function(_,p,sample) assert(p==player); f.samples[#f.samples+1]=sample; return true,'visible' end,
                clear=function() f.clears=f.clears+1 end}
        end}
    end}, {__index=_G})
local script=loadfile('reframework/autorun/re2_coop_guest_preview.lua','t',env)
if script then script() end
assert(f.update and f.reset and f.draw,'solo guest renderer is missing')
local function tick() for _=1,6 do f.update() end; f.draw() end
tick(); assert(#f.samples==0 and #f.text==0)
f.active=true
tick()
local sample=assert(f.samples[1],'explicit solo session did not render')
assert(sample.motion.bank==1000 and sample.motion.frame==8 and sample.campaign_area.map==174)
assert(sample.origin.x>2 and sample.origin.y==3 and sample.origin.z>4)
assert(f.text[#f.text]:find('Simulierter Gast',1,true))
assert(not sample.campaign_attempt_id and not sample.session_id)
f.rotation={x=0,y=math.sqrt(0.5),z=0,w=math.sqrt(0.5)}
tick(); assert(f.samples[2].origin.z<4,'offset did not follow player rotation')
f.scene=12
tick(); assert(f.clears==1,'the old scene retained its preview')
f.no_player=true
tick()
local count=#f.samples
tick(); assert(#f.samples==count,'missing player supplied a preview')
f.no_player=false
tick(); assert(#f.samples>count)
local before=f.clears
f.active=false
tick(); assert(f.clears==before+1,'preview survived real lobby or opt-out')
local after=#f.samples
tick(); assert(#f.samples==after)
f.active=true
tick(); before=f.clears
f.reset(); assert(f.clears==before+1,'preview survived script reset')
print('ok - local preview follows the observed player, remains visibly simulated and clears on scope or scene loss')
