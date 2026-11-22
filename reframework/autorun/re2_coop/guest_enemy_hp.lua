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

function M.new(options)
    options = options or {}
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

    local function current_point(row, expected, controller, relative)
        local live = row.live
        if not live.present or not live.active or not live.is_live or live.is_dead
            or row.kind_id ~= expected.kind_id or live.inherit_id ~= expected.inherit_id
            or live.hp <= 0 or live.hp > live.default_hp or live.default_hp ~= expected.default_hp
            or not controller or controller:call('get_IsActiveEnemy') ~= true
            or controller:call('get_IsLive') ~= true or no_damage:call(controller) ~= false
            or controller:call('get_KindID') ~= expected.kind_id
            or controller:call('get_InheritID') ~= expected.inherit_id
            or guid(controller:get_field('<ContextGUID>k__BackingField')) ~= row.id then return nil end
        local point = controller:get_field('<HitPoint>k__BackingField')
        if not is_object(point, point_name) or is_dead:call(point) ~= false
            or get_default:call(point) ~= expected.default_hp then return nil end
        local hp = get_hp:call(point)
        if hp > 0 and hp <= expected.default_hp and (relative or hp == live.hp) then return point, hp end
    end

    local function write_hp(point, target)
        set_hp:call(point, target)
        local after_hp, after_is_dead = get_hp:call(point), is_dead:call(point)
        assert(after_hp == target and after_is_dead == false, 'hp_readback_failed')
        return after_hp, after_is_dead
    end

    local function apply_hit(hit, receipt)
        if not options.authorize_hit or not options.authorize_hit(receipt)
            or not readback.fresh(hit.at, os.time()) or math.type(hit.damage) ~= 'integer' or hit.damage < 1 then return end
        local native = capture()
        if not native or not readback.same_checkpoint(native.checkpoint, receipt.checkpoint) then return end
        local active = resolve(native.active_count)
        if not active or not active[hit.id] then return end
        for _, row in ipairs(native.entries) do
            if row.id == hit.id then
                if options.authorize_hit(receipt) and readback.fresh(hit.at, os.time()) then
                    local point, hp = current_point(row, hit, active[hit.id], true)
                    if point and hp > hit.damage then return {before_hp=hp, after_hp=write_hp(point, hp-hit.damage)} end
                end
                return
            end
        end
    end

    local function apply_view(state, receipt, record_write)
        if options.authorize and not options.authorize(receipt) then
            return {reason='campaign_scope_changed', applied=0}
        end
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
            local host, live = candidates[row.id], row.live
            local point = host and current_point(row, host, active[row.id])
            if point then
                if live.hp == host.hp then
                    handled[row.id] = true
                    identical = identical + 1
                elseif options.damage_only and host.hp > live.hp then
                    handled[row.id] = true
                else
                    if not readback.fresh(receipt.received_at, os.time()) then
                        return {reason='receipt_expired', applied=applied, identical=identical,
                            skipped=state.eligible-applied-identical}
                    end
                    if options.authorize and not options.authorize(receipt) then
                        return {reason='campaign_scope_changed', applied=applied, identical=identical,
                            skipped=state.eligible-applied-identical}
                    end
                    point = current_point(row, host, active[row.id])
                    if point then
                        -- Consume before any write attempt that might partially succeed.
                        handled[row.id] = true
                        local after_hp, after_is_dead = write_hp(point, host.hp)
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
    return apply_view, apply_hit
end

return M
