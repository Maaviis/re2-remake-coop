-- Local timing of the existing enemy damage and death APIs. No native writes.
local M = {}
local root = 'app.ropeway.'
local hp_name, enemy_hp = root .. 'HitPointController', root .. 'EnemyHitPointController'
local enemy_name = root .. 'EnemyController'
local hp_field, hp_object = '<CurrentHitPoint>k__BackingField', '<HitPoint>k__BackingField'
local capacity, max_points = 128, 512

local function method(owner, name, argument)
    local definition = assert(sdk.find_type_definition(owner))
    local resolved = assert(definition:get_method(name))
    local parameters = resolved:get_param_types()
    assert(not resolved:is_static() and resolved:get_return_type():get_full_name() == 'System.Void'
        and #parameters == (argument and 1 or 0)
        and (not argument or parameters[1]:get_full_name() == argument), 'unsupported_timing_signature')
    return resolved
end

local function field(owner, name, expected)
    local definition = assert(sdk.find_type_definition(owner))
    local member = assert(definition:get_field(name))
    assert(not member:is_static() and member:get_type():get_full_name() == expected, 'unsupported_timing_field')
end

local function signed32(raw)
    local value = sdk.to_int64(raw) & 0xffffffff
    return value <= 0x7fffffff and value or value - 0x100000000
end

function M.new()
    assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70, 'unsupported_timing_build')
    local add = method(hp_name, 'addDamage(System.Int32)', 'System.Int32')
    local apply_dead = method(enemy_name, 'applyDead')
    field(hp_name, hp_field, 'System.Int32')
    field(enemy_name, hp_object, enemy_hp)
    assert(thread and type(thread.get_hook_storage) == 'function', 'timing_storage_unavailable')

    local self = {}
    local owner, scope
    local frame, generation, sequence, call_number = 0, 0, 0, 0
    local discarded, read_errors, points, point_count, events = 0, 0, {}, 0, {}

    function self:frame(player, binding)
        local address = player and player:get_address() or nil
        if address ~= owner or binding ~= scope then
            owner, scope, points, point_count = address, binding, {}, 0
            generation = generation + 1
        end
        frame = frame + 1
    end

    local function emit(kind, phase, call, point, values)
        sequence = sequence + 1
        local row = {sequence=sequence, frame=frame, generation=generation, kind=kind,
            phase=phase, call=call, point=point}
        for key, value in pairs(values or {}) do row[key] = value end
        events[#events+1] = row
        if #events > capacity then
            table.remove(events, 1)
            discarded = discarded + 1
        end
    end

    function self:begin(kind, point, values)
        if not owner or not point or not point:get_type_definition():is_a(enemy_hp) then return nil end
        local address = point:get_address()
        local key = points[address]
        if not key then
            if point_count >= max_points then return nil end
            point_count = point_count + 1
            key, points[address] = point_count, point_count
        end
        call_number = call_number + 1
        emit(kind, 'entered', call_number, key, values)
        return {kind=kind, call=call_number, point=key, generation=generation}
    end

    function self:finish(pending, values)
        if pending and owner and pending.generation == generation then
            emit(pending.kind, 'returned', pending.call, pending.point, values)
        end
    end

    function self:callback_begin(point, values)
        local ok, result = pcall(self.begin, self, 'hit_callback', point, values)
        if ok then return result end
        read_errors = read_errors + 1
    end

    local function observe_native(native_method, kind, resolve)
        local key = {}
        sdk.hook(native_method, function(args)
            local storage = thread.get_hook_storage()
            storage[key] = nil
            if owner then
                local ok, pending = pcall(function()
                    local point, values = resolve(args)
                    if not point then return nil end
                    local hp = point:get_field(hp_field)
                    assert(math.type(hp) == 'integer', 'invalid_timing_hp')
                    values.hp = hp
                    return self:begin(kind, point, values)
                end)
                if ok then storage[key] = pending else read_errors = read_errors + 1 end
            end
            return sdk.PreHookResult.CALL_ORIGINAL
        end, function(retval)
            local storage = thread.get_hook_storage()
            local pending = storage[key]
            storage[key] = nil
            -- Do not dereference native objects after a call that may retire the controller.
            self:finish(pending)
            return retval
        end)
    end

    observe_native(add, 'point_damage', function(args)
        return sdk.to_managed_object(args[2]), {requested=signed32(args[3])}
    end)
    observe_native(apply_dead, 'apply_dead', function(args)
        local target = sdk.to_managed_object(args[2])
        return target and target:get_field(hp_object), {}
    end)

    function self:snapshot()
        local copy = {}
        for index, row in ipairs(events) do
            local values = {}
            for key, value in pairs(row) do values[key] = value end
            copy[index] = values
        end
        return {active=owner ~= nil, generation=generation, frame=frame,
            sequence=sequence, discarded=discarded, read_errors=read_errors, events=copy}
    end
    return self
end

return M
