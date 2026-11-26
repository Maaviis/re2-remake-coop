-- Local display for the explicit protected solo test. The source is the native player.
if reframework:get_game_name() ~= 're2' or sdk.get_tdb_version() ~= 70 then return end
local test_peer = require('re2_coop.cutscene_test_peer')
local campaign = require('re2_coop.campaign_pose_scope')
local renderer = require('re2_coop.campaign_avatar')
local motion_type
local avatar, context, status, hide_at
local clearing = false
local updates = 0
local key_down
local labels = {visible='Figur sichtbar · F5 zum Ausblenden', waiting_player='Nach dem Intro im freien Spiel F5 drücken',
    motion_or_scenario_missing='Warte auf eine Spieleranimation', clip_pending='Animation wird geladen',
    mesh_or_skeleton_pending='Körpermodell wird geladen', clip_readback_pending='Animation wird geprüft',
    avatar_parts_pending='Kopf und Haare werden geladen'}

local function show(reason)
    if reason ~= status then
        status = reason
        if reason then log.info('RE2_COOP_SOLO_AVATAR ' .. reason) end
    end
end

local function clear()
    if avatar then
        clearing = true
        avatar:clear()
    end
    clearing = false
    avatar, context = nil, nil
end

local function stop(reason)
    clear()
    show(reason)
    hide_at = reason and os.time()+3 or nil
end

local function read_pose(player, area)
    motion_type = motion_type or sdk.typeof('via.motion.Motion')
    local transform = player:call('get_Transform')
    local motion = player:call('getComponent(System.Type)', motion_type)
    local layer = motion and motion:call('getLayerCount') > 0 and motion:call('getLayer(System.UInt32)',0)
    local node = layer and layer:call('get_HighestWeightMotionNode')
    if not transform or not node then return end
    local clip = {bank=node:call('get_MotionBankID'),id=node:call('get_MotionID'),
        name=node:call('get_MotionName'),frame=node:call('get_Frame'),end_frame=node:call('get_EndFrame')}
    if not renderer.valid_motion(clip) then return end
    local p,q = transform:get_position(),transform:get_rotation()
    if not p or not q then return end
    for _, n in ipairs({p.x,p.y,p.z}) do if not (n > -math.huge and n < math.huge) then return end end
    local norm = math.sqrt(q.x^2+q.y^2+q.z^2+q.w^2)
    if not (norm > 0 and norm < math.huge) then return end
    local x,y,z,w = q.x/norm,q.y/norm,q.z/norm,q.w/norm
    -- Place the preview to the player's right and slightly ahead on the horizontal plane.
    local right_x, right_z = 1-2*(y*y+z*z),2*(x*z-w*y)
    local forward_x, forward_z = 2*(x*z+w*y),1-2*(x*x+y*y)
    return {origin={x=p.x+1.35*right_x+forward_x,y=p.y,z=p.z+1.35*right_z+forward_z},
        rotation={x=x,y=y,z=z,w=w},campaign_area=area,motion=clip,observer_sequence=updates}
end

local function update(toggle)
    if clearing or (avatar and toggle) then stop(nil); return end
    if not test_peer.active() then stop(nil); return end
    if not test_peer.preview_ready() then stop('waiting_player'); return end
    local area = campaign.read_area()
    local flow = area and sdk.get_managed_singleton('app.ropeway.gamemastering.MainFlowManager')
    if not flow or flow:call('get_IsInGameNotPause') ~= true then stop('waiting_player'); return end
    local manager = sdk.get_managed_singleton(sdk.game_namespace('PlayerManager'))
    local player = manager and manager:call('get_CurrentPlayer')
    local address = player and player:get_address()
    local scene = address and address ~= 0 and campaign.scene_address()
    if not scene or scene == 0 then
        stop('waiting_player'); return
    end
    if context and (context.player ~= address or context.scene ~= scene or not campaign.same_area(context.area,area)) then
        stop('waiting_player'); return
    end
    local pose = read_pose(player,area)
    if not pose then stop('motion_or_scenario_missing'); return end
    if not avatar then
        hide_at = nil
        show('creating_renderer')
        avatar = assert(renderer.new(true),'renderer_unavailable')
        context = {player=address,scene=scene,area=area}
        show('starting_avatar_update')
    end
    local visible, reason = avatar:update(player,pose,'H')
    show(visible and 'visible' or reason or 'renderer_pending')
end

re.on_pre_application_entry('UpdateBehavior',function()
    updates = updates + 1
    local down = reframework:is_key_down(0x74)
    local toggle = down and key_down == false
    key_down = down
    if not toggle and (not avatar or updates % 6 ~= 0) then return end
    local ok, err = pcall(update,toggle)
    if not ok then
        local cleaned, failure = pcall(clear)
        show(cleaned and tostring(err) or tostring(failure))
        hide_at = os.time()+3
    end
end)
re.on_frame(function()
    if hide_at and os.time() >= hide_at then show(nil); hide_at=nil end
    if status then draw.text('Simulierter Gast · ' .. (labels[status] or 'Details im REFramework-Log'),20,140,0xFFFFFFFF) end
end)
re.on_script_reset(function() clear(); show(nil) end)
