local script = 'reframework/autorun/re2_coop/campaign_avatar.lua'
local exact = 'pl00_0160_KFF_Gazing_Idle_F_Loop'

local function fixture(scenario, preview)
    local f = {now=100, clock=1, ready=true, drawn=true, created=0, destroyed=0, changes=0, paths={}, banks={},
        parts={}, parts_ready=true, removed_parts=0}
    local resource, joints, dynamic_holder, list_holder = {}, {}, {}, {}
    local dynamic = {call=function(_, name)
        if name=='get_MotionBank' then return dynamic_holder end
        assert(name=='get_MotionList')
        return list_holder
    end}
    local source = {get_address=function() return 10 end, call=function(_, name, arg)
        if name=='get_MotionBankAsset' then return resource end
        if name=='get_JointMap' then return joints end
        if name=='get_TargetBankType' then return 31 end
        if name=='getDynamicMotionBankCount' then return 2 end
        assert(name=='getDynamicMotionBank(System.Int32)', 'attempted write on the local animation source')
        if arg==1 then return dynamic end
    end}
    local player = {get_address=function() return 50 end, call=function(_, name, argument)
        assert(name=='getComponent(System.Type)' and argument=='via.motion.Motion')
        return source
    end}
    local node = {call=function(_, name)
        if name=='get_MotionBankID' then return 1000 end
        if name=='get_MotionID' then return f.motion_id or 160 end
        assert(name=='get_MotionName')
        if f.variant and f.bank_type~=4 then return 'wrong_native_variant' end
        return f.clip_name or exact
    end}
    local layer = {get_address=function() return 22 end, call=function(_, name, a, b, c, frames, mode, curve)
        if name=='set_LocalBankType' then f.bank_type=a
        elseif name=='changeMotion(System.UInt32, System.UInt32, System.Single)' then
            assert(a==1000 and b==160 and c==0.0)
            f.changes=f.changes+1
        elseif name=='changeMotion(System.UInt32, System.UInt32, System.Single, System.Single, via.motion.InterpolationMode, via.motion.InterpolationCurve)' then
            assert(a==1000 and (b==160 or b==f.extra_motion) and c==0.0 and frames>0 and mode==2 and curve==1)
            f.blends=(f.blends or 0)+1
            f.changes=f.changes+1
        elseif name=='get_HighestWeightMotionNode' then return node
        elseif name=='get_EndFrame' then return 100
        elseif name=='get_Frame' then return f.frame or 0
        elseif name=='set_Frame(System.Single)' then f.frame=a
        else
            assert(name=='set_BlendRate' or name=='set_Speed' or name=='setup()')
        end
    end}
    local bank = {call=function(_, name)
        if name=='get_BankID' then return 1000 end
        assert(name=='get_BankType')
        return 4
    end}
    local owned_motion = {get_address=function() return 20 end, call=function(_, name, a, b, c)
        if name=='set_JointMap' then assert(a==joints)
        elseif name=='set_TargetBankType' then assert(a==31)
        elseif name=='set_MotionBankAsset' then assert(a==resource)
        elseif name=='setDynamicMotionBankCount(System.Int32)' then assert(a==2)
        elseif name=='setDynamicMotionBank(System.Int32, via.motion.DynamicMotionBank)' then
            assert(b~=dynamic and b.bank==dynamic_holder and b.list==list_holder)
            f.banks[a]=b
        elseif name=='getLayer(System.UInt32)' then return layer
        elseif name=='get_JointsConstructed' then return f.ready
        elseif name=='set_RootMotion' then assert(a==0); f.root_mode=a
        elseif name=='get_RootMotion' then return f.root_mode
        elseif name=='hasMotion(System.UInt32, System.UInt32)' then
            f.motion_lookups=(f.motion_lookups or 0)+1
            return a==1000 and (b==160 or b==f.extra_motion)
        elseif name=='hasMotion(System.UInt32, System.UInt32, System.Int32)' then
            return f.variant and a==1000 and b==160 and c==4
        elseif name=='getActiveMotionBankCount' then return f.variant and 1 or 0
        elseif name=='getActiveMotionBank(System.UInt32)' then assert(a==0); return bank
        elseif name=='setupMotionBank()' then f.bank_setups=(f.bank_setups or 0)+1
        else assert(name=='setLayerCount(System.UInt32)') end
    end}
    local renderer = {call=function(_, name)
        if name=='get_MeshReady' or name=='get_MaterialReady' or name=='get_SkinningMesh' then return f.ready end
        assert(name=='setMesh(via.render.MeshResourceHolder)' or name=='set_Material(via.render.MeshMaterialResourceHolder)')
    end}
    local head_joint = {get_address=function() return 80 end}
    local transform = {
        get_address=function() return 31 end,
        call=function(_, name, value)
            assert(name=='getJointByName' and value=='head')
            return head_joint
        end,
        set_position=function(_, p) f.position_writes=(f.position_writes or 0)+1; if not f.ignore_position then f.position=p end end,
        set_rotation=function(_, q) f.rotation=q end,
        get_position=function() return f.position or {x=0,y=0,z=0} end,
        get_rotation=function() return f.rotation end,
    }
    local object = {get_address=function() return 30 end, call=function(_, name, argument)
        if name=='get_DrawSelf' then return f.drawn end
        if name=='set_DrawSelf' then f.drawn=argument; return end
        if name=='get_Transform' then return transform end
        assert(name=='createComponent(System.Type)')
        return argument=='via.render.Mesh' and renderer or owned_motion
    end}
    local function attachment(label)
        local part={drawn=true,alive=true}
        f.parts[#f.parts+1]=part
        local part_index=#f.parts
        part.renderer={call=function(_,name,value)
            if name=='get_MeshReady' or name=='get_MaterialReady' or name=='get_SkinningMesh' then
                return f.parts_ready
            end
            if name=='setMesh(via.render.MeshResourceHolder)' then part.mesh=value
            else assert(name=='set_Material(via.render.MeshMaterialResourceHolder)'); part.material=value end
        end}
        local joint={call=function(_,name)
            assert(name=='get_ConstraintJoint')
            if not f.unbound_parts then return head_joint end
        end}
        part.transform={get_address=function() return 40+part_index end, call=function(_,name,value,world)
            if name=='setParent(via.Transform, System.Boolean)' then assert(world==false); part.parent=value
            elseif name=='get_Parent' then return part.parent
            elseif name=='set_SameJointsConstraint' then part.constraint=value
            elseif name=='get_SameJointsConstraint' then return part.constraint
            else assert(name=='getJointByName' and value=='head'); return joint end
        end}
        part.object={get_address=function() return 60+part_index end, call=function(_,name,value)
            if name=='get_DrawSelf' then return part.drawn end
            if name=='set_DrawSelf' then part.drawn=value; return end
            if name=='get_Transform' then return part.transform end
            assert(name=='createComponent(System.Type)' and value=='via.render.Mesh', label)
            return part.renderer
        end}
        return part.object
    end
    local env = setmetatable({
        sdk={
            get_tdb_version=function() return 70 end,
            typeof=function(name) return name end,
            find_type_definition=function(kind)
                if kind=='via.motion.InterpolationMode' or kind=='via.motion.InterpolationCurve' then
                    return {get_field=function(_, key)
                        assert(key=='CrossFade' or key=='Smooth')
                        return {get_data=function() return key=='CrossFade' and 2 or 1 end}
                    end}
                end
                return {get_method=function(_, method)
                    if method=='.ctor()' then return nil end
                    assert(kind=='via.GameObject')
                    return {is_static=function() return true end, call=function(_, receiver, argument)
                        assert(receiver==nil)
                        if method=='create(System.String)' then
                            local label=preview and 'RE2CoopSoloPreview' or 'RE2CoopCampaignAvatar'
                            if argument~=label then
                                assert(argument==label..'Head' or argument==label..'Hair')
                                return attachment(argument)
                            end
                            f.created=f.created+1
                            return object
                        end
                        assert(method=='destroy(via.GameObject)')
                        if argument==object then f.destroyed=f.destroyed+1; return end
                        for _,part in ipairs(f.parts) do
                            if argument==part.object then
                                assert(part.alive)
                                part.alive=false
                                f.removed_parts=f.removed_parts+1
                                return
                            end
                        end
                        error('attempted to destroy an object the avatar does not own')
                    end}
                end}
            end,
            is_managed_object=function(value)
                if value==object or value==owned_motion or value==renderer or value==layer then return true end
                for _,part in ipairs(f.parts) do
                    if value==part.object or value==part.renderer then return part.alive end
                end
                return false
            end,
            create_resource=function(_, path)
                f.paths[#f.paths+1]=path
                return {create_holder_global=function() return path end}
            end,
            create_instance=function(name)
                assert(name=='via.motion.DynamicMotionBank')
                return {call=function(self, key, value)
                    if key=='set_MotionBank' then self.bank=value else
                        assert(key=='set_MotionList')
                        self.list=value
                    end
                end}
            end,
        },
        os={time=function() return f.now end},
        Vector4f={new=function(x,y,z,w) return {x=x,y=y,z=z,w=w} end},
        Quaternion={new=function(w,x,y,z) return {x=x,y=y,z=z,w=w} end},
    }, {__index=_G})
    local module = assert(loadfile(script, 't', env))()
    f.instance, f.module = module.new(preview,function() return f.clock end), module
    f.pose={motion={bank=1000,id=160,name=exact,frame=25,end_frame=50}, campaign_area={scenario=scenario},
        observer_sequence=1, origin={x=1,y=2,z=3}, rotation={x=0,y=0,z=0,w=1}}
    function f.update(viewer_role)
        return f.instance:update(player,f.pose,viewer_role or (preview and 'H' or 'G'))
    end
    return f
end

for scenario=0,3 do
    local f=fixture(scenario)
    assert(not f.update('H') and not f.drawn)
    local partner=scenario%2==0 and 'pl1001' or 'pl0001'
    assert(f.paths[1]:find(partner,1,true) and f.paths[2]:find(partner,1,true),
        'the host must see the guest character within the shared scenario')
end

for _,spec in ipairs({{'H','pl1050','pl1070'}, {'G','pl0050','pl0070'}}) do
    local f=fixture(0)
    assert(not f.update(spec[1]))
    assert(#f.parts==2 and #f.paths==6, 'a complete avatar requires separate face and hair meshes')
    for i,part in ipairs(f.parts) do
        assert(part.mesh:find(spec[i+1],1,true) and part.material:find(spec[i+1],1,true))
        assert(part.constraint==true and not part.drawn, 'visual parts must bind to the skeleton while hidden')
    end
    f.parts_ready=false
    assert(not f.update(spec[1]) and not f.drawn)
    f.parts_ready=true
    f.unbound_parts=true
    assert(not f.update(spec[1]) and not f.drawn)
    f.unbound_parts=false
    assert(f.update(spec[1]) and f.drawn)
    assert(f.parts[1].drawn and f.parts[2].drawn)
    f.instance:clear()
    assert(f.removed_parts==2 and f.destroyed==1 and not f.parts[1].drawn and not f.parts[2].drawn)
end

do
    local f=fixture(0)
    local visible, reason = f.update('unknown')
    assert(not visible and reason=='avatar_role_missing' and #f.paths==0)
end

do
    local f=fixture(0)
    f.pose.observer_run_id='remote-run'
    f.update()
    f.update()
    assert(f.update() and f.position.x==1)
    f.clock=1.1
    f.pose.origin.x=3
    f.pose.rotation={x=0,y=-1,z=0,w=0}
    f.pose.observer_sequence=2
    assert(f.update() and f.position.x==1, 'new network pose snapped instead of interpolating')
    f.clock=1.15
    f.instance:advance()
    assert(math.abs(f.position.x-2)<0.001 and math.abs(math.abs(f.rotation.y)-0.7071)<0.001)
    assert(f.update() and math.abs(f.position.x-2)<0.001, 'duplicate poses must not restart smoothing')
    f.clock=1.21
    f.instance:advance()
    assert(f.position.x==3, 'the renderer must stop at the last known position')
    f.clock=1.3
    f.pose.origin.x=30
    f.pose.observer_sequence=3
    assert(f.update() and f.position.x==30, 'large corrections must not run through scenery')
    f.clock=1.4
    f.pose.origin.x=31
    f.pose.observer_run_id='replacement-run'
    f.pose.observer_sequence=1
    assert(f.update() and f.position.x==31, 'new observer stream must not inherit old coordinates')
    f.clock=1.5
    f.pose.origin.x, f.pose.rotation.y, f.pose.observer_sequence=32, 1, 2
    assert(f.update())
    f.clock=1.55
    f.instance:advance()
    assert(math.abs(f.position.x-31.5)<0.001 and math.abs(f.rotation.y)==1,
        'equivalent antipodal rotations must not spin or collapse')
    f.clock=2
    f.pose.origin.x, f.pose.observer_sequence=33, 3
    assert(f.update() and f.position.x==33, 'recovery after a long gap must not replay the old trajectory')
    f.instance:clear()
    f.clock=2.05
    f.instance:advance()
    assert(not f.drawn)
end

do
    local f=fixture(0)
    f.update()
    f.update()
    assert(f.update())
    f.pose.observer_sequence=2
    f.pose.motion.name='new_clip'
    f.clock=1.1
    assert(f.update() and f.drawn and f.blends==1, 'a valid clip change must blend while the avatar stays visible')
    f.clip_name='new_clip'
    f.clock=1.2
    assert(f.update() and f.drawn and f.blends==1)
end

do
    local f=fixture(0)
    f.update('H')
    f.update('H')
    assert(f.update('H') and f.drawn)
    assert(not f.update('G') and f.destroyed==1 and not f.drawn)
    assert(f.paths[7]:find('pl0001',1,true), 'a changed role must rebuild the partner model')
end

for scenario=0,3 do
    local f=fixture(scenario)
    assert(not f.update() and not f.drawn and f.root_mode==0)
    assert(f.paths[1]:find(scenario%2==0 and 'pl0001' or 'pl1001',1,true))
    assert(f.banks[0]==nil and f.banks[1].bank~=nil)
    assert(not f.update() and not f.drawn and f.changes==1)
    assert(f.update() and f.drawn and f.frame==50 and f.position.x==1)
    f.clock=1.1
    f.pose.origin.x, f.pose.observer_sequence, f.pose.motion.frame = 3, 2, 10
    assert(f.update() and f.frame==20 and f.changes==1)
    f.pose.motion=nil
    assert(not f.update() and f.destroyed==1 and not f.drawn)
end

for scenario=0,3 do
    local f=fixture(scenario,true)
    assert(not f.update() and not f.drawn)
    local partner=scenario%2==0 and 'pl1001' or 'pl0001'
    assert(f.paths[1]:find(partner,1,true) and f.paths[2]:find(partner,1,true),
        'the solo preview must load the partner body and material')
    assert(not f.update() and f.update() and f.drawn and f.frame==50)
end

do
    local f=fixture(0)
    f.variant=true
    f.update()
    f.update()
    for _=1,3 do assert(not f.update() and not f.drawn) end
    assert(f.bank_type==4 and f.changes==2)
    assert(f.update() and f.drawn)
    f.pose.motion.id=9000
    assert(f.update() and f.drawn and f.changes==2)
end

for _, role in ipairs({'H','G'}) do
    local f=fixture(0)
    f.update(role)
    f.update(role)
    assert(f.update(role) and f.drawn)
    f.pose.motion = {bank=1000,id=9000,name='new_walk_loop',frame=10,end_frame=50}
    f.pose.origin.x, f.pose.observer_sequence, f.clock = 3, 2, 1.1
    local visible, reason = f.update(role)
    assert(visible and reason=='clip_unavailable_using_previous' and f.drawn,
        'an unavailable motion must not replace a verified character with the fallback object')
    assert(f.parts[1].drawn and f.parts[2].drawn and f.frame==50)
    local lookups, setups = f.motion_lookups, f.bank_setups
    f.clock = 1.15
    f.instance:advance()
    assert(math.abs(f.position.x-2)<0.001, 'an unavailable motion must not interrupt position smoothing')
    assert(f.update(role) and f.motion_lookups==lookups and f.bank_setups==setups,
        'repeated packets must not rescan a missing bank each frame')
    f.now, f.clock = 106, 7
    assert(f.update(role) and f.destroyed==0 and f.position.x==3, 'valid previous motion must survive the startup deadline')
    f.extra_motion = 9000
    f.now, f.clock = 107, 8
    assert(f.update(role) and f.blends==1 and f.destroyed==0)
    f.motion_id, f.clip_name = 9000, 'new_walk_loop'
    f.clock = 8.1
    assert(f.update(role) and f.drawn and f.frame==20, 'an available clip must take over and align its frame')
end

do
    local f=fixture(0)
    f.update()
    f.update()
    assert(f.update())
    f.pose.motion.id = 9000
    f.unbound_parts = true
    assert(not f.update() and not f.drawn, 'a broken head constraint must still hide the character')
    f.unbound_parts = false
    f.clip_name = 'unexpected_native_clip'
    assert(not f.update() and not f.drawn, 'fallback requires the previously verified native motion')
end

do
    local f=fixture(0)
    f.pose.motion.name='pl00_0160_OFF_Gazing_Idle_F_Loop'
    f.update()
    f.update()
    assert(f.update() and f.drawn and f.frame==50)
    f.pose.motion.name='a_different_clip'
    assert(f.update() and f.drawn)
    f.clock=2
    assert(not f.update() and not f.drawn)
end

do
    local f=fixture(0)
    assert(not f.update())
    assert(not f.update())
    f.pose.origin.x=5
    f.pose.observer_sequence=2
    f.clock=1.4
    f.ignore_position=true
    assert(not f.update() and not f.drawn)
    assert(not f.module.valid_motion({bank=0xffffffff+1,id=1,name='Game/Assets',frame=1,end_frame=5}))
end

do
    local f=fixture(0)
    f.update()
    f.update()
    assert(f.update() and f.drawn)
    f.ready=false
    local visible, reason = f.update()
    assert(not visible and not f.drawn, 'a lost mesh suppressed the visible fallback')
    assert(reason == 'mesh_or_skeleton_pending', 'missing render readiness was invisible to diagnostics')
    f.ready=true
    assert(f.update() and f.drawn)
end

do
    local f=fixture(0)
    f.update(); f.update(); assert(f.update())
    local before=f.position_writes
    for i=1,120 do
        f.clock=f.clock+1/120
        if i%6==0 then
            f.pose.observer_sequence=f.pose.observer_sequence+1
            assert(f.update())
        else
            f.instance:advance()
        end
    end
    assert(f.position_writes==before, 'stationary avatar incurred '..(f.position_writes-before)..' transform writes')
    f.position={x=2,y=2,z=3}
    assert(f.update() and f.position.x==1, 'external displacement must be repaired')
    f.pose.origin.x=2
    for i=1,48 do
        f.clock=f.clock+1/120
        if i%6==0 then
            f.pose.observer_sequence=f.pose.observer_sequence+1
            assert(f.update())
        else
            f.instance:advance()
        end
        if i==24 then before=f.position_writes end
    end
    assert(f.position.x==2 and f.position_writes==before, 'repeat packets kept a completed movement alive')
end
print('Campaign avatar: stock models, owned bank copy, native clip readback, phase and motion fallback passed')
