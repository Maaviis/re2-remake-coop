local M = dofile('reframework/autorun/re2_coop/save_protection.lua')
local now, reads, documents, challenge = 100, 0, {}, nil
local id = string.rep('a', 32)
local function reset()
    documents = {}
    for _, value in ipairs({
        {name = 'native_save_guard', source = 'steam_storage_guard', reason = 'ok', interface = '014', guarded_methods = 10},
        {name = 'protected_launch', source = 'inherited_save_locks', locked_files = 12}}) do
        value.schema, value.at, value.active = 1, 100, true
        value.run_id, value.game_pid, value.app_id, value.build_id = id, 42, 883710, 11636119
        if value.name == 'native_save_guard' then value.lua_challenge = challenge end
        documents['re2_coop_' .. value.name .. '.json'] = value
    end
end
local options = {run_id = id, thread_id = function() return 9876 end, clock = function() return now end,
    read = function(name)
        reads = reads + 1
        return documents[name]
    end,
    write = function(name, value)
        assert(name == 're2_coop_save_guard_challenge.txt' and #value == 41 and value:sub(1, 9) == '00002694:')
        challenge = value
    end}
local state = M.new(options)
assert(state.requested and not state:poll() and challenge, 'a new Lua VM did not request proof from its own plugin')
reset()
assert(state:poll() and state:matches({run_id = id, game_pid = 42}))
local before = reads
assert(state:ready())
now = 104
assert(not state:ready(), 'cached proof did not expire without polling')
assert(reads == before, 'hook-safe readiness performed file I/O')
now = 99
assert(not state:ready(), 'future cached proof accepted')
now = 100
for _, name in ipairs({'re2_coop_native_save_guard.json', 're2_coop_protected_launch.json'}) do
    for _, change in ipairs({{'at', 96}, {'at', 101}, {'active', false}, {'game_pid', 43},
        {'run_id', string.rep('b', 32)}, {'schema', true}, {'app_id', 1}, {'build_id', 0}}) do
        reset()
        documents[name][change[1]] = change[2]
        assert(not state:poll(), 'invalid protection proof accepted: ' .. name .. '/' .. change[1])
        assert(not state:ready(), 'failed polling retained earlier proof')
    end
end
reset()
documents['re2_coop_native_save_guard.json'].guarded_methods = 9
assert(not state:poll())
reset(); documents['re2_coop_protected_launch.json'].locked_files = 0
assert(not state:poll())
reset(); documents['re2_coop_native_save_guard.json'] = nil
assert(not state:poll())
reset(); assert(state:poll())
assert(not state:matches({run_id = id, game_pid = 43}))
assert(not state:matches({run_id = string.rep('b', 32), game_pid = 42}))
local previous = challenge
local another = M.new(options)
assert(not another:poll() and previous ~= challenge, 'old native proof survived a new Lua VM')
reset()
assert(another:poll() and not state:poll(), 'native proof was not bound to the active Lua VM')
local stock = M.new({run_id = '', read = function() error('stock launch read a stale guard proof') end})
assert(not stock.requested and not stock:poll(), 'a stock launch tried to activate the save guard')
print('Save protection: paired native/launch receipts, replay rejection and cached hook-safe expiry passed')
