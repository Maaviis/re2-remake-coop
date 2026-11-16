-- Passive enemy damage callbacks. No gameplay setters, native method calls or I/O in hooks.
local M = {}
local controller_name = 'app.ropeway.EnemyController'
local damage_name = 'app.Collision.HitController.DamageInfo'
local hp_name = 'app.ropeway.HitPointController'
local capacity = 128

local function integer(value, low, high)
    assert(math.type(value) == 'integer' and value >= low and value <= high, 'invalid_damage_integer')
    return value
end

local function boolean(value)
    assert(type(value) == 'boolean', 'invalid_damage_boolean')
    return value
end

local function clone(value)
    if type(value) ~= 'table' then return value end
    local output = {}; for key, item in pairs(value) do output[key] = clone(item) end
    return output
end

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_damage_build')
    local function definition(name)
        return assert(sdk.find_type_definition(name), 'missing_damage_type:' .. name)
    end
    local function field(owner, name, kind)
        local member = assert(definition(owner):get_field(name), 'missing_damage_field:' .. name)
        assert(not member:is_static() and member:get_type():get_full_name() == kind,
            'unsupported_damage_field:' .. name)
    end
    local controller, damage_type = definition(controller_name), definition(damage_name)
    assert(not damage_type:is_value_type(), 'unsupported_damage_argument')
    local method = assert(controller:get_method('HitController_OnHitDamage'), 'missing_damage_callback')
    local params = method:get_param_types()
    assert(not method:is_static() and method:get_return_type():get_full_name() == 'System.Void'
        and #params == 1 and params[1]:get_full_name() == damage_name, 'unsupported_damage_callback')
    field(controller_name, '<ContextGUID>k__BackingField', 'System.Guid')
    field(controller_name, '<HitPoint>k__BackingField', 'app.ropeway.EnemyHitPointController')
    field(hp_name, '<CurrentHitPoint>k__BackingField', 'System.Int32')
    for _, name in ipairs({'OriginalDamage', 'Damage', 'Wince', 'Break'}) do
        field(damage_name, '<' .. name .. '>k__BackingField', 'System.Int32')
    end
    for _, name in ipairs({'IsKill', 'IsArmored'}) do field(damage_name, '<' .. name .. '>k__BackingField', 'System.Boolean') end
    for _, name in ipairs({'AttackOwnerObject', 'WeaponGameObject'}) do
        field(damage_name, '<' .. name .. '>k__BackingField', 'via.GameObject')
    end
    for name, kind in pairs({mData1 = 'System.UInt32', mData2 = 'System.UInt16', mData3 = 'System.UInt16'}) do
        field('System.Guid', name, kind)
    end
    for index = 0, 7 do field('System.Guid', 'mData4_' .. index, 'System.Byte') end
    assert(thread and type(thread.get_hook_storage) == 'function', 'hook_storage_unavailable')

    local self = {enabled = true, sequence = 0, discarded = 0, read_errors = 0, events = {}}
    local player_address
    local function guid(value)
        local bytes = {}; for index = 0, 7 do bytes[index + 1] = integer(value:get_field('mData4_' .. index), 0, 255) end
        return ('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
            integer(value:get_field('mData1'), 0, 0xffffffff), integer(value:get_field('mData2'), 0, 0xffff),
            integer(value:get_field('mData3'), 0, 0xffff), table.unpack(bytes))
    end
    local function sample(info)
        local result = {}
        for _, name in ipairs({'OriginalDamage', 'Damage', 'Wince', 'Break'}) do
            result[name] = integer(info:get_field('<' .. name .. '>k__BackingField'), -0x80000000, 0x7fffffff)
        end
        result.IsKill = boolean(info:get_field('<IsKill>k__BackingField'))
        result.IsArmored = boolean(info:get_field('<IsArmored>k__BackingField'))
        local owner = info:get_field('<AttackOwnerObject>k__BackingField')
        result.attacker = owner and player_address and (owner:get_address() == player_address and 'local_player' or 'other') or 'unknown'
        result.weapon_present = info:get_field('<WeaponGameObject>k__BackingField') ~= nil
        return result
    end
    sdk.hook(method, function(args)
        local storage = thread.get_hook_storage()
        storage.re2_coop_enemy_damage = nil
        if self.enabled then
            local ok, value = pcall(function()
                local target, info = assert(sdk.to_managed_object(args[2])), assert(sdk.to_managed_object(args[3]))
                local hp = assert(target:get_field('<HitPoint>k__BackingField'))
                return {id = guid(assert(target:get_field('<ContextGUID>k__BackingField'))),
                    hp_on_entry = integer(hp:get_field('<CurrentHitPoint>k__BackingField'), -0x80000000, 0x7fffffff),
                    info = info, hp = hp, before = sample(info), at = os.time()}
            end)
            if ok then storage.re2_coop_enemy_damage = value else self.read_errors = self.read_errors + 1 end
        end
        return sdk.PreHookResult.CALL_ORIGINAL
    end, function(retval)
        local storage = thread.get_hook_storage()
        local pending = storage.re2_coop_enemy_damage
        storage.re2_coop_enemy_damage = nil
        if pending and self.enabled then
            local ok, event = pcall(function()
                return {id = pending.id, at = pending.at, kind = 'enemy_damage_callback',
                    hp_on_entry = pending.hp_on_entry,
                    hp_on_exit = integer(pending.hp:get_field('<CurrentHitPoint>k__BackingField'), -0x80000000, 0x7fffffff),
                    before = pending.before, after = sample(pending.info)}
            end)
            if ok then
                self.sequence = self.sequence + 1
                event.sequence = self.sequence
                self.events[#self.events + 1] = event
                if #self.events > capacity then table.remove(self.events, 1); self.discarded = self.discarded + 1 end
            else self.read_errors = self.read_errors + 1 end
        end
        return retval
    end)
    function self:set_local_player(value)
        player_address = value and value:get_address() or nil
    end
    function self:snapshot()
        return {sequence = self.sequence, discarded = self.discarded, read_errors = self.read_errors, events = clone(self.events)}
    end
    function self:stop() self.enabled, player_address = false, nil end
    return self
end
return M
