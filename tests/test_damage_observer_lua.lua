local module_path = 'reframework/autorun/re2_coop/damage_observer.lua'
local controller = 'app.ropeway.EnemyController'
local damage = 'app.Collision.HitController.DamageInfo'
local field_types = {}
local function fields(owner, values)
    field_types[owner] = values
end
fields(controller, {['<ContextGUID>k__BackingField'] = 'System.Guid',
    ['<HitPoint>k__BackingField'] = 'app.ropeway.EnemyHitPointController'})
fields('app.ropeway.HitPointController', {['<CurrentHitPoint>k__BackingField'] = 'System.Int32'})
fields(damage, {})
for _, name in ipairs({'OriginalDamage', 'Damage', 'Wince', 'Break', 'IsKill', 'IsArmored', 'AttackOwnerObject', 'WeaponGameObject'}) do
    field_types[damage]['<' .. name .. '>k__BackingField'] =
        (name == 'IsKill' or name == 'IsArmored') and 'System.Boolean' or
        (name == 'AttackOwnerObject' or name == 'WeaponGameObject') and 'via.GameObject' or 'System.Int32'
end
fields('System.Guid', {mData1 = 'System.UInt32', mData2 = 'System.UInt16', mData3 = 'System.UInt16'})
for i = 0, 7 do field_types['System.Guid']['mData4_' .. i] = 'System.Byte' end
local function kind(name) return {get_full_name = function() return name end} end
local hooks, stack, wrong_signature = {}, {}, false
reframework = {get_game_name = function() return 're2' end}
thread = {get_hook_storage = function() return assert(stack[#stack], 'missing hook frame') end}
sdk = {get_tdb_version = function() return 70 end, PreHookResult = {CALL_ORIGINAL = 123},
    to_managed_object = function(value) return value end,
    find_type_definition = function(owner)
        assert(field_types[owner], owner)
        return {is_value_type = function() return false end,
            get_method = function(_, name)
                assert(owner == controller and name == 'HitController_OnHitDamage')
                return {is_static = function() return false end,
                    get_return_type = function() return kind('System.Void') end,
                    get_param_types = function() return {kind(wrong_signature and 'System.Int32' or damage)} end}
            end,
            get_field = function(_, name)
                local actual = assert(field_types[owner][name], owner .. '.' .. name)
                return {is_static = function() return false end, get_type = function() return kind(actual) end}
            end}
    end,
    hook = function(_, pre, post) hooks[#hooks + 1] = {pre = pre, post = post} end}
local function object(values, address)
    return {values = values, get_address = function() return address or 1 end,
        get_field = function(self, name)
            if self.fail then error('transient native read') end
            return self.values[name]
        end,
        call = function() error('native getter re-entry inside damage hook') end}
end
local player = object({}, 77)
local function pair(id, hp)
    local guid = {mData1 = id, mData2 = 0xabcd, mData3 = 0xffff}
    for i = 0, 7 do guid['mData4_' .. i] = i end
    local health = object({['<CurrentHitPoint>k__BackingField'] = hp})
    local target = object({['<ContextGUID>k__BackingField'] = object(guid), ['<HitPoint>k__BackingField'] = health})
    local data = {['<OriginalDamage>k__BackingField'] = 100, ['<Damage>k__BackingField'] = 90,
        ['<Wince>k__BackingField'] = 12, ['<Break>k__BackingField'] = 3,
        ['<IsKill>k__BackingField'] = false, ['<IsArmored>k__BackingField'] = false,
        ['<AttackOwnerObject>k__BackingField'] = player, ['<WeaponGameObject>k__BackingField'] = object({})}
    return target, object(data), health
end
local function enter(hook, target, info)
    stack[#stack + 1] = {}
    assert(hook.pre({nil, target, info}) == 123, 'original native damage call must run')
end
local function leave(hook)
    local sentinel = {}
    assert(hook.post(sentinel) == sentinel, 'native return value changed')
    stack[#stack] = nil
end

wrong_signature = true
assert(not pcall(function() dofile(module_path).new() end))
assert(#hooks == 0, 'bad interfaces installed a partial observer')
wrong_signature = false
local reader = dofile(module_path).new()
reader:set_local_player(player)
local hook = hooks[1]
local target, info, hp = pair(0xffffffff, 770)
enter(hook, target, info)
info.values['<Damage>k__BackingField'] = 80
hp.values['<CurrentHitPoint>k__BackingField'] = 690
leave(hook)
local snapshot = reader:snapshot()
assert(snapshot.sequence == 1 and snapshot.events[1].id == 'ffffffff-abcd-ffff-0001-020304050607')
local event = snapshot.events[1]
assert(event.hp_on_entry == 770 and event.hp_on_exit == 690)
assert(event.before.Damage == 90 and event.after.Damage == 80 and event.after.attacker == 'local_player')
assert(event.after.IsKill == false and event.after.weapon_present == true)
snapshot.events[1].before.Damage = -99
assert(reader:snapshot().events[1].before.Damage == 90, 'snapshot shares mutable event storage')

local outer, outer_info = pair(1, 100)
local inner, inner_info = pair(2, 200)
enter(hook, outer, outer_info)
enter(hook, inner, inner_info)
leave(hook)
leave(hook)
snapshot = reader:snapshot()
assert(snapshot.events[2].id:sub(1, 8) == '00000002' and snapshot.events[3].id:sub(1, 8) == '00000001',
    'nested callback overwrote its caller')

info.fail = true
enter(hook, target, info); leave(hook)
info.fail = false
enter(hook, target, info); info.fail = true; leave(hook)
info.fail = false
snapshot = reader:snapshot()
assert(snapshot.sequence == 3 and snapshot.read_errors == 2, 'failed read emitted a partial event')

reader:set_local_player(nil)
hp.values['<CurrentHitPoint>k__BackingField'] = 0
enter(hook, target, info); leave(hook)
event = reader:snapshot().events[4]
assert(event.after.attacker == 'unknown' and event.after.IsKill == false,
    'zero HP or missing local binding invented a kill/attacker')
for _ = 1, 130 do enter(hook, target, info); leave(hook) end
snapshot = reader:snapshot()
assert(snapshot.sequence == 134 and #snapshot.events == 128 and snapshot.discarded == 6)
reader:stop()
enter(hook, target, info); leave(hook)
assert(reader:snapshot().sequence == 134, 'stopped observer emitted another callback')
print('Passive damage observer: native pass-through, nested calls, copied fields, read failures and bounded history passed')
