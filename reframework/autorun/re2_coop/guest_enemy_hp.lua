-- Apply only positive, bounded HP to freshly resolved living campaign enemies.
local M = {}
local root = 'app.ropeway.'
local controller_name, point_name = root .. 'EnemyController', root .. 'EnemyHitPointController'
local point_base = root .. 'HitPointController'
local list_name = 'System.Collections.Generic.List`1<' .. controller_name .. '>'

local function checked_method(type_name, name, returns, argument)
    local def = assert(sdk.find_type_definition(type_name), 'missing_hp_type:' .. type_name)
    local method = assert(def:get_method(name), 'missing_hp_method:' .. name)
    local parameters = method:get_param_types()
    local result = method:get_return_type():get_full_name()
    assert(not method:is_static() and (returns == nil and result ~= 'System.Void' or result == returns)
        and #parameters == (argument and 1 or 0)
        and (not argument or parameters[1]:get_full_name() == argument), 'invalid_hp_signature:' .. name)
    return method
end

local function is_object(object, expected)
    if not object then return false end
    local def = object:get_type_definition()
    for _ = 1, 16 do
        if not def then return false end
        if def:get_full_name() == expected then return true end
        def = def:get_parent_type()
    end
    return false
end

local function guid(value)
    assert(is_object(value, 'System.Guid'), 'invalid_active_enemy_guid')
    local bytes = {}
    for i = 0, 7 do bytes[i+1] = value:get_field('mData4_' .. i) end
    return ('%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x'):format(
        value:get_field('mData1'), value:get_field('mData2'), value:get_field('mData3'), table.unpack(bytes))
end

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_hp_build')
    local capture = require('re2_coop.enemy_state').new().capture
    local readback = require('re2_coop.guest_enemy_readback')
    local set_hp = checked_method(point_base, 'set_CurrentHitPoint(System.Int32)', 'System.Void', 'System.Int32')
    local get_hp = checked_method(point_base, 'get_CurrentHitPoint', 'System.Int32')
    local get_default = checked_method(point_base, 'get_DefaultHitPoint', 'System.Int32')
    local is_dead = checked_method(point_base, 'get_IsDead', 'System.Boolean')
    local no_damage = checked_method(controller_name, 'get_NoDamage', 'System.Boolean')
    local active_list = checked_method(root .. 'EnemyManager', 'get_ActiveEnemyList', list_name)
    local count = checked_method(list_name, 'get_Count', 'System.Int32')
    local item = checked_method(list_name, 'get_Item(System.Int32)', nil, 'System.Int32')
    local generation, sequence, handled

    local function resolve(expected_count)
        local manager = sdk.get_managed_singleton(root .. 'EnemyManager')
        local list = manager and active_list:call(manager)
        if not is_object(list, list_name) or count:call(list) ~= expected_count then return nil end
        local active = {}
        for index = 0, expected_count - 1 do
            local controller = item:call(list, index)
            if not is_object(controller, controller_name) then return nil end
            local key = guid(controller:get_field('<ContextGUID>k__BackingField'))
            if active[key] then return nil end
            active[key] = controller
        end
        if count:call(list) == expected_count then return active end
    end

    return function(state, receipt, record_write)
        local host_sequence = receipt.view.observer_sequence
        if generation and (receipt.generation < generation
            or (generation == receipt.generation and host_sequence < sequence)) then
            return {reason='already_seen', applied=0}
        end
        -- Advance replay protection independently of successful local application.
        -- A transient capture/identity/protection miss must not consume this view.
        if generation ~= receipt.generation or sequence ~= host_sequence then
            generation, sequence, handled = receipt.generation, host_sequence, {}
        end
        local candidates = {}
        for id in pairs(state.enemies) do
            local host = receipt.view.enemies[id]
            if not handled[id] and host.is_live and not host.is_dead
                and host.hp > 0 and host.hp <= host.default_hp then
                candidates[id] = host
            end
        end
        if not next(candidates) then
            return {reason=next(handled) and 'already_seen' or 'no_positive_candidates', applied=0}
        end
        local native = capture()
        if not native or not readback.same_checkpoint(native.checkpoint, receipt.load.checkpoint) then
            return {reason='native_checkpoint_changed', applied=0}
        end
        local active = resolve(native.active_count)
        if not active then return {reason='native_active_list_changed', applied=0} end
        local applied, identical = 0, 0
        for _, row in ipairs(native.entries) do
            local host, live, controller = candidates[row.id], row.live, active[row.id]
            if host and live.present and live.active and live.is_live and not live.is_dead
                and row.kind_id == host.kind_id and live.inherit_id == host.inherit_id
                and live.hp > 0 and live.hp <= live.default_hp and live.default_hp == host.default_hp
                and controller and controller:call('get_IsActiveEnemy') == true
                and controller:call('get_IsLive') == true and no_damage:call(controller) == false
                and controller:call('get_KindID') == host.kind_id
                and controller:call('get_InheritID') == host.inherit_id
                and guid(controller:get_field('<ContextGUID>k__BackingField')) == row.id then
                local point = controller:get_field('<HitPoint>k__BackingField')
                if is_object(point, point_name) and is_dead:call(point) == false
                    and get_default:call(point) == host.default_hp and get_hp:call(point) == live.hp then
                    if live.hp == host.hp then
                        handled[row.id] = true
                        identical = identical + 1
                    else
                        if not readback.fresh(receipt.received_at, os.time()) then
                            return {reason='receipt_expired', applied=applied, identical=identical,
                                skipped=state.eligible-applied-identical}
                        end
                        -- Consume only after the final lease gate, before any
                        -- write attempt that might fail or partially succeed.
                        handled[row.id] = true
                        set_hp:call(point, host.hp)
                        local after_hp, after_is_dead = get_hp:call(point), is_dead:call(point)
                        assert(after_hp == host.hp and after_is_dead == false, 'hp_readback_failed')
                        applied = applied + 1
                        if record_write then
                            record_write(row.id, {kind_id=host.kind_id, inherit_id=host.inherit_id,
                                before_hp=live.hp, after_hp=after_hp, is_dead=after_is_dead})
                        end
                    end
                end
            end
        end
        return {reason='ok', applied=applied, identical=identical, skipped=state.eligible-applied-identical}
    end
end

return M
