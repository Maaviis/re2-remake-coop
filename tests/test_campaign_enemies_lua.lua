local script = 'reframework/autorun/re2_coop_campaign_enemies.lua'
local area = {scenario=1, map=4, area=2}
local scope = {role='H', attempt_id=string.rep('a', 32), request_id=string.rep('b', 32),
    session_id=string.rep('c', 32), snapshot_epoch=string.rep('d', 16)}
local current, connected, native_area = nil, true, area
local installed, sealed, capture_count = false, false, 0
local frame, reset, authorize, latest
local now = 100
local player = {get_address=function() return 12 end}

local campaign = {
    read_release=function() return current end,
    peer_matches=function() return connected end,
    observed_context=function() return {player_address=12, scene_address=21, area=area} end,
    read_area=function() return native_area end,
    scene_address=function() return 21 end,
    same_area=function(a, b)
        return a and b and a.scenario == b.scenario and a.map == b.map and a.area == b.area
    end,
}
local modules = {
    ['re2_coop.campaign_pose_scope']=campaign,
    ['re2_coop.enemy_state']={new=function() return {capture=function()
        capture_count = capture_count + 1
        return {checkpoint={scenario=1}}, 'ok'
    end} end},
    ['re2_coop.damage_observer']={new=function(options) assert(options.scoped); return {} end},
    ['re2_coop.campaign_hits']={new=function()
        return {update=function() end, reset=function() end}
    end},
    ['re2_coop.guest_enemy_hp']={new=function(options)
        assert(options.damage_only)
        authorize = options.authorize
        return function() end
    end},
    ['re2_coop.guest_enemy_readback']={install=function(_, options)
        assert(not sealed and options.campaign)
        installed = true
    end},
}
local environment = setmetatable({
    require=function(name) assert(not sealed, 'late native module load'); return assert(modules[name]) end,
    os={time=function() return now end},
    reframework={get_game_name=function() return 're2' end},
    sdk={get_tdb_version=function() return 70 end, game_namespace=function(name) return name end,
        get_managed_singleton=function() return {call=function() return player end} end},
    re={on_pre_application_entry=function(name, callback) assert(name=='UpdateBehavior'); frame=callback end,
        on_script_reset=function(callback) reset=callback end},
    json={dump_file=function(name, value)
        assert(name=='re2_coop_campaign_enemy_state.json')
        latest=value
    end},
}, {__index=_G})
assert(loadfile(script, 't', environment))()
assert(installed and frame and reset)
sealed = true
local function tick()
    for _ = 1, 6 do frame() end
end

tick()
assert(not latest and capture_count == 0)
current = scope
tick()
assert(capture_count == 1 and latest.available and latest.state.campaign_area == area)
local first_visit = latest.state.campaign_visit
local receipt = {load={request_id=scope.request_id}, session_id=scope.session_id,
    campaign_attempt=scope.attempt_id, view={campaign_area=area}}
assert(not authorize(receipt))
scope.role = 'G'
assert(authorize(receipt))
receipt.campaign_attempt = string.rep('e', 32)
assert(not authorize(receipt))
receipt.campaign_attempt = scope.attempt_id
native_area = {scenario=1, map=4, area=3}
assert(not authorize(receipt))
now = 101
tick()
assert(not latest.available and capture_count == 1)
native_area = area
connected = false
tick()
assert(not latest.available and not authorize(receipt))
connected = true
tick()
assert(latest.available and capture_count == 2 and latest.state.campaign_visit ~= first_visit)
reset()
assert(not latest.available and latest.reason=='script_reset')
print('Campaign enemies: autorun initialization, host observation, guest scope, area changes and disconnect passed')
