local now, version, post, reset, instance, fail_cursor
local keyboard, mouse, pad
local mask, requests, calls, published, window_key, window_mouse
local types = {}
local names = {'app.ropeway.InputSystem', 'via.hid.Keyboard', 'via.hid.KeyboardDevice',
    'via.hid.Mouse', 'via.hid.MouseDevice', 'via.hid.GamePadDevice'}
for _, name in ipairs(names) do types[name] = {get_method = function(_, method) return method end} end
os.time = function() return now end
reframework = {get_game_name = function() return 're2' end, is_drawing_ui = function() return false end,
    get_first_key_down = function() return window_key end}
imgui = {is_mouse_down = function(button) return button == 0 and window_mouse end}
re = {on_script_reset = function(fn) reset = fn end}
log = {info = function() end}
json = {dump_file = function(_, value) published = value end}
sdk = {
    get_tdb_version = function() return version end,
    find_type_definition = function(name) return types[name] end,
    get_native_singleton = function(name) return name end,
    get_managed_singleton = function() return instance end,
    hook = function(_, _, fn) post = fn end,
    call_native_func = function(object, _, method)
        if method == 'get_Device' then return object == 'via.hid.Keyboard' and keyboard or mouse end
        local value = object[method]
        assert(value ~= nil, 'unexpected native call: ' .. method)
        return value
    end,
}
local M = dofile('reframework/autorun/re2_coop/lobby_input.lua')
local function setup()
    now, version, post, reset, fail_cursor = 100, 70, nil, nil, false
    window_key, window_mouse = nil, false
    keyboard, mouse = {get_AnyKeyDown = false}, {get_ButtonDown = 0}
    pad = {get_ButtonDown = 0, get_AnyExtraButtonDown = false,
        get_RawAxisL = {x = 0, y = 0}, get_RawAxisR = {x = 0, y = 0}, get_AnalogL = 0, get_AnalogR = 0}
    mask, calls, requests = 0, {}, {foreign = true}
    local unit = {call = function(_, name) assert(name == 'get_Device'); return pad end}
    local units = {call = function(_, name)
        if name == 'get_Count' then return 1 end
        assert(name == 'get_Item(System.Int32)'); return unit
    end}
    instance = {call = function(_, method, key, value)
        calls[#calls + 1] = method
        if method == 'get_InputUnitList' then return units end
        if method == 'get_mouseScreenPoint' then return {x = 0, y = 0} end
        if method == 'setInhibit(System.Boolean)' then
            assert(key == true, 'must never clear an input mask owned by the game or another mod')
            mask = -1
        elseif method == 'requestShowMouseCursor' then
            requests[key .. ':cursor'] = true
            if fail_cursor then error('cursor service failed after partial acquisition') end
        elseif method == 'requestIgnoreMouseMove' then requests[key .. ':move'] = true
        elseif method == 'removeShowMouseCursor' then requests[key .. ':cursor'] = nil
        elseif method == 'removeIgnoreMouseMove' then requests[key .. ':move'] = nil
        else error('unexpected mutation: ' .. method) end
    end}
    return M.new()
end
local function tick(external_mask)
    mask = external_mask or 0 -- The original native update resets Inhibit before our post-hook.
    assert(post and post('original-return') == 'original-return')
end
local function acquire(guard)
    guard:frame(true); tick()
    assert(guard:can_draw() and guard.captured and mask == -1)
    assert(requests['re2_coop_lobby:cursor'] and requests['re2_coop_lobby:move'])
end
local guard = setup()
assert(not guard:can_draw())
acquire(guard)
guard:frame(false)
mouse.get_ButtonDown = 1
tick(); tick()
assert(guard.captured and guard.reason == 'release_held_input' and not guard:can_draw())
mouse.get_ButtonDown = 0
tick(); assert(guard.captured)
tick(4); assert(not guard.captured and mask == 4 and requests.foreign)
assert(not requests['re2_coop_lobby:cursor'] and not requests['re2_coop_lobby:move'])

for _, held in ipairs({'keyboard', 'window-keyboard', 'window-mouse', 'pad-button', 'pad-extra', 'pad-axis', 'pad-trigger'}) do
    guard = setup(); acquire(guard); guard:frame(false)
    if held == 'keyboard' then keyboard.get_AnyKeyDown = true end
    if held == 'window-keyboard' then window_key = 87 end
    if held == 'window-mouse' then window_mouse = true end
    if held == 'pad-button' then pad.get_ButtonDown = 1 end
    if held == 'pad-extra' then pad.get_AnyExtraButtonDown = true end
    if held == 'pad-axis' then pad.get_RawAxisR.x = 0.8 end
    if held == 'pad-trigger' then pad.get_AnalogR = 0.9 end
    tick(); tick(); assert(guard.captured, 'held input leaked after closing: ' .. held)
end

guard = setup(); acquire(guard)
now = 102; tick(); tick()
assert(not guard.captured and not guard:can_draw(), 'lost render heartbeat must release capture')
guard:frame(true); tick(); assert(guard:can_draw(), 'capture must recover on a fresh visible frame')
reset(); assert(not guard.captured and requests.foreign)
tick(8); assert(mask == 8, 'reset script must stop applying its mask')

guard = setup(); fail_cursor = true; guard:frame(true); tick()
assert(not guard:can_draw() and guard.reason == 'input_unavailable')
assert(not requests['re2_coop_lobby:cursor'] and requests.foreign, 'partial request leaked')
fail_cursor = false; tick(); assert(guard:can_draw())
instance = nil; tick(); assert(not guard.captured and not guard:can_draw())

setup(); version = 69; guard = M.new()
assert(not guard.installed and guard.reason == 'unsupported_input_api')
print('Lobby input: held mouse/keyboard/pad, lease, partial failure, reset and foreign masks passed')
