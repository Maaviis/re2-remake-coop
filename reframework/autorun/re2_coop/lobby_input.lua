-- RE2 TDB 70 modal input. The engine resets Inhibit each update; never clear another owner's mask.
local M = {}
local key = 're2_coop_lobby'
local input_name = 'app.ropeway.InputSystem'

function M.new()
    local self = {captured = false, wanted = false, reason = 'initializing', neutral_frames = 0}
    local owner, last_frame, last_update, last_publish, last_log
    local types, native = {}, {}

    local function report()
        local state = tostring(self.captured) .. ':' .. self.reason
        if state ~= last_log then log.info('RE2_COOP_LOBBY_INPUT ' .. state); last_log = state end
    end

    local function release()
        if owner then
            -- Remove only the two requests registered with our own key.
            pcall(owner.call, owner, 'removeShowMouseCursor', key)
            pcall(owner.call, owner, 'removeIgnoreMouseMove', key)
            owner = nil
        end
        self.captured, self.neutral_frames = false, 0
    end

    local function call(name, method, ...)
        return sdk.call_native_func(native[name], types[name], method, ...)
    end

    local function neutral(input)
        -- Engine device state may already be masked; retain the independent window events too.
        if reframework:get_first_key_down() ~= nil then return false end
        for button = 0, 4 do if imgui.is_mouse_down(button) then return false end end
        local keyboard = call('via.hid.Keyboard', 'get_Device')
        local mouse = call('via.hid.Mouse', 'get_Device')
        if not keyboard or not mouse then return false end
        if sdk.call_native_func(keyboard, types['via.hid.KeyboardDevice'], 'get_AnyKeyDown') then return false end
        if sdk.call_native_func(mouse, types['via.hid.MouseDevice'], 'get_ButtonDown') ~= 0 then return false end
        local units = input:call('get_InputUnitList')
        if not units then return false end
        local count = units:call('get_Count')
        if type(count) ~= 'number' or count < 0 or count > 5 or count % 1 ~= 0 then return false end
        for index = 0, count - 1 do
            local unit = units:call('get_Item(System.Int32)', index)
            local pad = unit and unit:call('get_Device')
            if pad then
                local def = types['via.hid.GamePadDevice']
                if sdk.call_native_func(pad, def, 'get_ButtonDown') ~= 0 then return false end
                if sdk.call_native_func(pad, def, 'get_AnyExtraButtonDown') then return false end
                for _, method in ipairs({'get_RawAxisL', 'get_RawAxisR'}) do
                    local axis = sdk.call_native_func(pad, def, method)
                    if not axis or math.abs(axis.x) > 0.25 or math.abs(axis.y) > 0.25 then return false end
                end
                if sdk.call_native_func(pad, def, 'get_AnalogL') > 0.1
                    or sdk.call_native_func(pad, def, 'get_AnalogR') > 0.1 then return false end
            end
        end
        return true
    end

    local function update()
        local now = os.time()
        local wanted = self.wanted and last_frame and now >= last_frame and now - last_frame <= 1
        local input = sdk.get_managed_singleton(input_name)
        if not input then release(); self.reason = 'input_unavailable'; last_update = nil; return end
        if owner and owner ~= input then release() end
        if wanted then self.neutral_frames = 0
        elseif self.captured then
            self.neutral_frames = neutral(input) and self.neutral_frames + 1 or 0
        end
        if wanted or self.captured and self.neutral_frames < 2 then
            if not owner then
                -- Set owner first so partial acquisition is cleaned up on any error.
                owner = input
                input:call('requestShowMouseCursor', key, input:call('get_mouseScreenPoint'))
                input:call('requestIgnoreMouseMove', key)
            end
            input:call('setInhibit(System.Boolean)', true)
            self.captured = true
            self.reason = wanted and 'captured' or 'release_held_input'
        else release(); self.reason = 'inactive' end
        last_update = now
    end

    function self:frame(wanted)
        self.wanted, last_frame = not not wanted, os.time()
        if last_frame ~= last_publish then
            last_publish = last_frame
            pcall(json.dump_file, 're2_coop_lobby_input.json', {schema = 1, observed_at = last_frame,
                wanted = self.wanted, captured = self.captured, reason = self.reason,
                framework_menu = reframework:is_drawing_ui()})
        end
    end

    function self:can_draw()
        local now = os.time()
        return self.installed and self.captured and self.wanted and self.reason == 'captured' and last_update
            and now >= last_update and now - last_update <= 1
    end

    local ok = pcall(function()
        assert(reframework:get_game_name() == 're2' and sdk.get_tdb_version() == 70)
        for _, name in ipairs({input_name, 'via.hid.Keyboard', 'via.hid.KeyboardDevice',
                'via.hid.Mouse', 'via.hid.MouseDevice', 'via.hid.GamePadDevice'}) do
            types[name] = assert(sdk.find_type_definition(name))
        end
        for _, name in ipairs({'via.hid.Keyboard', 'via.hid.Mouse'}) do
            native[name] = assert(sdk.get_native_singleton(name))
        end
        local method = assert(types[input_name]:get_method('update'))
        for _, name in ipairs({'setInhibit(System.Boolean)', 'requestShowMouseCursor', 'removeShowMouseCursor',
                'requestIgnoreMouseMove', 'removeIgnoreMouseMove', 'get_mouseScreenPoint', 'get_InputUnitList'}) do
            assert(types[input_name]:get_method(name))
        end
        for name, methods in pairs({['via.hid.Keyboard'] = {'get_Device'}, ['via.hid.Mouse'] = {'get_Device'},
                ['via.hid.KeyboardDevice'] = {'get_AnyKeyDown'}, ['via.hid.MouseDevice'] = {'get_ButtonDown'},
                ['via.hid.GamePadDevice'] = {'get_ButtonDown', 'get_AnyExtraButtonDown',
                    'get_RawAxisL', 'get_RawAxisR', 'get_AnalogL', 'get_AnalogR'}}) do
            for _, method in ipairs(methods) do assert(types[name]:get_method(method)) end
        end
        sdk.hook(method, function() end, function(retval)
            if not self.installed then return retval end
            local success = pcall(update)
            if not success then release(); last_update = nil; self.reason = 'input_unavailable' end
            report()
            return retval
        end)
        self.installed = true
        re.on_script_reset(function()
            self.wanted = false
            self.installed = false
            release()
            last_update, self.reason = nil, 'script_reset'
            report()
        end)
    end)
    if not ok then self.installed = false; self.reason = 'unsupported_input_api'; report() end
    return self
end

return M
