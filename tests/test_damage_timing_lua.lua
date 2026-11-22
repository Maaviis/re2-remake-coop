local hp_name = 'app.ropeway.HitPointController'
local enemy_hp = 'app.ropeway.EnemyHitPointController'
local enemy = 'app.ropeway.EnemyController'
local hp_field, point_field = '<CurrentHitPoint>k__BackingField', '<HitPoint>k__BackingField'
local function typename(name) return {get_full_name=function() return name end} end
local hooks, stack, incompatible = {}, {}, false
local function field(kind)
    return {is_static=function() return false end, get_type=function() return typename(kind) end}
end

local definitions = {
    [hp_name] = {
        get_field=function(_, name) assert(name==hp_field); return field('System.Int32') end,
    },
    [enemy] = {
        get_field=function(_, name) assert(name==point_field); return field(enemy_hp) end,
    },
}
definitions[hp_name].get_method = function(_, name)
    assert(name=='addDamage(System.Int32)')
    return {name='damage', is_static=function() return false end,
        get_param_types=function() return {typename(incompatible and 'System.UInt32' or 'System.Int32')} end,
        get_return_type=function() return typename('System.Void') end}
end
definitions[enemy].get_method = function(_, name)
    assert(name=='applyDead')
    return {name='dead', is_static=function() return false end,
        get_param_types=function() return {} end, get_return_type=function() return typename('System.Void') end}
end

local env = setmetatable({
    reframework={get_game_name=function() return 're2' end},
    sdk={get_tdb_version=function() return 70 end, find_type_definition=function(name) return definitions[name] end,
        hook=function(method, pre, post) hooks[method.name]={pre=pre, post=post} end,
        to_managed_object=function(value) return value end, to_int64=function(value) return value end,
        PreHookResult={CALL_ORIGINAL='original'}},
    thread={get_hook_storage=function() return assert(stack[#stack]) end},
}, {__index=_G})
local module = assert(loadfile('reframework/autorun/re2_coop/damage_timing.lua','t',env))()
local function pre(name, object, amount)
    stack[#stack+1] = {}
    assert(hooks[name].pre({nil, object, amount})=='original')
end
local function post(name)
    local retval = {}
    assert(hooks[name].post(retval)==retval, 'observer changed native result')
    stack[#stack] = nil
end

incompatible = true
assert(not pcall(module.new))
assert(next(hooks)==nil, 'unverified native API installed a partial trace')
incompatible = false
local trace = module.new()
local player = {get_address=function() return 19 end}
local point = {hp=770, get_address=function() return 55 end,
    get_type_definition=function() return {is_a=function(_, name) return name==enemy_hp end} end,
    get_field=function(self, name) assert(name==hp_field and not self.retired); return self.hp end}
local target = {get_field=function(_, name) assert(name==point_field); return point end}
pre('damage', point, 80)
post('damage')
assert(trace:snapshot().sequence==0)

trace:frame(player, 'same-protected-load')
-- The point worker can finish before the high-level callback observes HP.
pre('damage', point, 80)
point.hp=690
post('damage')
local callback = trace:callback_begin(point, {id='enemy-test',hp=690,attacker='local_player',damage=80})
trace:finish(callback, {hp=690,attacker='local_player'})
pre('dead', target)
point.retired = true
post('dead')
local data = trace:snapshot()
assert(data.sequence==6 and data.read_errors==0)
assert(data.events[1].kind=='point_damage' and data.events[1].hp==770 and data.events[1].requested==80)
assert(data.events[2].phase=='returned' and data.events[2].call==data.events[1].call)
assert(data.events[3].kind=='hit_callback' and data.events[3].hp==690)
assert(data.events[3].point==data.events[1].point and data.events[4].hp==690)
assert(data.events[5].kind=='apply_dead' and data.events[6].phase=='returned')
assert(data.events[6].point==data.events[1].point and data.events[6].hp==nil)
assert(data.events[1].point~=point:get_address())
data.events[1].hp = -50
assert(trace:snapshot().events[1].hp==770)

point.retired = false
pre('damage', point, 7)
trace:frame(nil)
post('damage')
assert(trace:snapshot().sequence==7, 'a return crossed the invalidated native lease')
trace:frame(player, 'second-protected-load')
for _ = 1, 80 do
    pre('damage', point, 10)
    post('damage')
end
data = trace:snapshot()
assert(data.sequence==167 and #data.events==128 and data.discarded==39)

do
    local now, tick, reset, bound
    now = 100
    local guard = {schema=1, active=true, hooks=26, protection_active=true, in_title=false, at=now,
        load_phase='scene_loaded', load_error='', denied_loads=0, load_request_id='load',
        policy_id='load', protection={run_id='sealed'}}
    local facade = {
        frame=function(_, selected, scope) bound = selected and scope or nil end,
    }
    local observer = {set_local_player=function() end, snapshot=function() return {} end,
        stop=function() end}
    local test_env = setmetatable({
        reframework=env.reframework,
        require=function(name)
            if name=='re2_coop.damage_timing' then return {new=function() return facade end} end
            return {new=function(options) assert(options.timing==facade); return observer end}
        end,
        sdk={game_namespace=function(name) return name end, get_tdb_version=function() return 70 end,
            get_managed_singleton=function() return {call=function() return player end} end},
        re={on_application_entry=function(_, callback) tick=callback end,
            on_script_reset=function(callback) reset=callback end},
        os={time=function() return now end, clock=function() return 1 end},
        fs={read=function() return 'test_guard' end},
        json={load_string=function() return guard end, dump_file=function() end},
    }, {__index=_G})
    assert(loadfile('reframework/diagnostics/re2_coop_damage_observer.lua','t',test_env))()
    tick()
    assert(bound=='sealed:load')
    now = 104
    tick()
    assert(not bound, 'expired proof left the diagnostic armed between guard reads')
    guard.at, guard.denied_loads = now, 1
    for _ = 1, 5 do tick() end
    assert(not bound)
    guard.denied_loads = 0
    for _ = 1, 6 do tick() end
    assert(bound=='sealed:load')
    reset()
    assert(not bound)
end

print('Combat timing: native signatures, passive order, scope loss, stable local point IDs, and bounded trace passed')
