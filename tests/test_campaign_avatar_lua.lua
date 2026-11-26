local script = 'reframework/autorun/re2_coop/campaign_avatar.lua'
local exact = 'pl00_0160_KFF_Gazing_Idle_F_Loop'

local function fixture(scenario, preview)
    local f = {now=100, ready=true, drawn=true, created=0, destroyed=0, changes=0, paths={}, banks={}}
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
        if name=='get_MotionID' then return 160 end
        assert(name=='get_MotionName')
        if f.variant and f.bank_type~=4 then return 'wrong_native_variant' end
        return f.clip_name or exact
    end}
    local layer = {get_address=function() return 22 end, call=function(_, name, a, b, c)
        if name=='set_LocalBankType' then f.bank_type=a
        elseif name=='changeMotion(System.UInt32, System.UInt32, System.Single)' then
            assert(a==1000 and b==160 and c==0.0)
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
        elseif name=='hasMotion(System.UInt32, System.UInt32)' then return a==1000 and b==160
        elseif name=='hasMotion(System.UInt32, System.UInt32, System.Int32)' then
            return f.variant and a==1000 and b==160 and c==4
        elseif name=='getActiveMotionBankCount' then return f.variant and 1 or 0
        elseif name=='getActiveMotionBank(System.UInt32)' then assert(a==0); return bank
        else assert(name=='setupMotionBank()' or name=='setLayerCount(System.UInt32)') end
    end}
    local renderer = {call=function(_, name)
        if name=='get_MeshReady' or name=='get_SkinningMesh' then return f.ready end
        assert(name=='setMesh(via.render.MeshResourceHolder)' or name=='set_Material(via.render.MeshMaterialResourceHolder)')
    end}
    local transform = {
        set_position=function(_, p) if not f.ignore_position then f.position=p end end,
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
    local env = setmetatable({
        sdk={
            get_tdb_version=function() return 70 end,
            typeof=function(name) return name end,
            find_type_definition=function(kind)
                return {get_method=function(_, method)
                    if method=='.ctor()' then return nil end
                    assert(kind=='via.GameObject')
                    return {is_static=function() return true end, call=function(_, receiver, argument)
                        assert(receiver==nil)
                        if method=='create(System.String)' then
                            assert(argument==(preview and 'RE2CoopSoloPreview' or 'RE2CoopCampaignAvatar'))
                            f.created=f.created+1
                            return object
                        end
                        assert(method=='destroy(via.GameObject)' and argument==object)
                        f.destroyed=f.destroyed+1
                    end}
                end}
            end,
            is_managed_object=function(value)
                return value==object or value==owned_motion or value==renderer or value==layer
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
    f.instance, f.module = module.new(preview), module
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

do
    local f=fixture(0)
    local visible, reason = f.update('unknown')
    assert(not visible and reason=='avatar_role_missing' and #f.paths==0)
end

do
    local f=fixture(0)
    f.update('H')
    f.update('H')
    assert(f.update('H') and f.drawn)
    assert(not f.update('G') and f.destroyed==1 and not f.drawn)
    assert(f.paths[3]:find('pl0001',1,true), 'a changed role must rebuild the partner model')
end

for scenario=0,3 do
    local f=fixture(scenario)
    assert(not f.update() and not f.drawn and f.root_mode==0)
    assert(f.paths[1]:find(scenario%2==0 and 'pl0001' or 'pl1001',1,true))
    assert(f.banks[0]==nil and f.banks[1].bank~=nil)
    assert(not f.update() and not f.drawn and f.changes==1)
    assert(f.update() and f.drawn and f.frame==50 and f.position.x==1)
    f.pose.origin.x, f.pose.observer_sequence, f.pose.motion.frame = 3, 2, 10
    assert(f.update() and f.frame==20 and f.position.x==3 and f.changes==1)
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
    assert(not f.update() and not f.drawn and f.changes==2)
end

do
    local f=fixture(0)
    f.pose.motion.name='pl00_0160_OFF_Gazing_Idle_F_Loop'
    f.update()
    f.update()
    assert(f.update() and f.drawn and f.frame==50)
    f.pose.motion.name='a_different_clip'
    assert(not f.update() and not f.drawn)
    assert(not f.update() and not f.drawn)
end

do
    local f=fixture(0)
    assert(not f.update())
    assert(not f.update())
    f.pose.origin.x=5
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

print('Campaign avatar: stock models, owned bank copy, native clip readback, phase and motion fallback passed')
