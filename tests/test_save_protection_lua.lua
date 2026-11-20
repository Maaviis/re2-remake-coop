local M = dofile('reframework/autorun/re2_coop/save_protection.lua')
local now, reads, documents = 100, 0, {}
local id = string.rep('a', 32)
local function reset()
    documents = {}
    for _, value in ipairs({
        {name = 'native_save_guard', source = 'steam_storage_guard', reason = 'ok', interface = '014', guarded_methods = 10},
        {name = 'protected_launch', source = 'inherited_save_locks', locked_files = 12}}) do
        value.schema, value.at, value.active = 1, 100, true
        value.run_id, value.game_pid, value.app_id, value.build_id = id, 42, 883710, 11636119
        documents['re2_coop_' .. value.name .. '.json'] = value
    end
end
local state = M.new({run_id = id, clock = function() return now end, read = function(name)
    reads = reads + 1
    return documents[name]
end})
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
print('Save protection: paired native/launch receipts, replay rejection and cached hook-safe expiry passed')
