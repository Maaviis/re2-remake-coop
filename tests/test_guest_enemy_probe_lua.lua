local script = 'reframework/diagnostics/re2_coop_guest_enemy_probe.lua'
local input, output = 're2_coop_guest_enemies.json', 're2_coop_guest_enemy_readback.json'
local native, guard = 're2_coop_enemy_state.json', 're2_coop_save_guard.json'
local id = '00000001-ffff-abcd-f0f1-f2f3f4f5f6f7'
local request = string.rep('d', 32)

local function copy(value)
    if type(value) ~= 'table' then return value end
    local result = {}
    for key, member in pairs(value) do result[key] = copy(member) end
    return result
end

local function fixture(game, tdb)
    local f = {now=100, files={}, decoded={}, reports={}, serial=0}
    local function put(name, document)
        f.serial = f.serial + 1
        local bytes = tostring(f.serial)
        f.files[name], f.decoded[bytes] = bytes, copy(document)
    end
    f.put = put
    local checkpoint = {game_guid='ffffffff-ffff-abcd-f0f1-f2f3f4f5f6f7',
        save_guid='00000002-ffff-abcd-f0f1-f2f3f4f5f6f7', scenario=1, location=16}
    f.receipt = {schema=1, source='steam_enemy_live', tdb=70, session_id=string.rep('a', 32),
        generation=100000001, sequence=1, received_at=100,
        load={request_id=request, slot_id=4, checkpoint=checkpoint,
            observer_run_id='native-enemy-run', observer_sequence=10},
        view={schema=1, scope='active_enemy_controller_observations', available=true, reason='ok',
            continuous=true, observer_sequence=11, observed_at=500, enemies={
                [id]={kind_id=4, inherit_id=-1, hp=0, default_hp=100, is_live=true, is_dead=false},
            }},
    }
    f.native = {schema=1, source='re2', tdb=70, scope='registered_and_stored_enemy_contexts',
        available=true, reason='ok', observed_at=100, sequence=10, run_id='native-enemy-run',
        state={checkpoint=checkpoint, registered_count=1, active_count=1, entries={
            {id=id, kind_id=4, live={present=true, active=true, inherit_id=-1, hp=17, is_live=true, is_dead=false}},
        }},
    }
    f.guard = {schema=1, active=true, hooks=26, at=100, load_request_id=request, policy_id=request,
        load_phase='scene_loaded', load_error='', load_started_at=98, load_index=4, allowed_slot=4,
        allowed_load_calls=1, denied_loads=0}
    put(input, f.receipt)
    put(native, f.native)
    put(guard, f.guard)
    local env = setmetatable({
        os={time=function() return f.now end},
        reframework={get_game_name=function() return game or 're2' end},
        sdk={get_tdb_version=function() return tdb or 70 end},
        re={on_pre_application_entry=function(name, fn) assert(name=='UpdateBehavior'); f.tick=fn end,
            on_script_reset=function(fn) f.reset=fn end},
        fs={read=function(name) return f.files[name] end},
        json={load_string=function(bytes) return f.decoded[bytes] end,
            dump_file=function(name, report) assert(name==output); f.reports[#f.reports+1]=report end},
    }, {__index=_G})
    assert(loadfile(script, 't', env))()
    function f.pass()
        for _=1,6 do f.tick() end
        return f.reports[#f.reports]
    end
    return f
end

do
    local f = fixture()
    local value = f.pass()
    assert(value.available and value.state.eligible==1)
    local pair = value.state.enemies[id]
    assert(pair.host_hp==0 and pair.local_hp==17 and not pair.host_is_dead and not pair.local_is_dead)
    -- Same receipt, newer local observation. The Lua probe must resolve the live identity again.
    f.native.sequence=11
    f.native.state.entries[1].live.inherit_id=-2
    f.put(native, f.native)
    value = f.pass()
    assert(value.available and value.state.eligible==0 and value.state.skipped==1)
    f.reset()
    assert(f.reports[#f.reports].reason=='script_reset' and not f.reports[#f.reports].available)
end

do
    local f=fixture()
    assert(f.pass().available)
    f.receipt.view.enemies[id].hp=4
    f.put(input, f.receipt)
    assert(f.pass().reason=='replayed_receipt')
    f.receipt.sequence=2
    f.put(input, f.receipt)
    assert(f.pass().available)
    f.now=104
    assert(f.pass().reason=='invalid_or_expired_receipt')
    f.now=100
    assert(f.pass().reason=='clock_moved_backwards')
end

do
    local f=fixture()
    assert(f.pass().available)
    local older = f.files[input]
    local next_receipt = {schema=1, source='steam_enemy_live', tdb=70,
        generation=100000002, session_id=string.rep('b',32), sequence=1, received_at=100,
        view={schema=1, scope='active_enemy_controller_observations', available=false},
    }
    f.put(input, next_receipt)
    assert(f.pass().reason=='peer_unavailable')
    f.files[input] = older
    assert(f.pass().reason=='replayed_receipt')
end

for _, fault in ipairs({'stale_native', 'new_load', 'new_checkpoint', 'new_run', 'torn_file', 'guard_write'}) do
    local f=fixture()
    if fault=='stale_native' then f.native.observed_at=96 end
    if fault=='new_load' then f.guard.load_request_id=string.rep('c',32) end
    if fault=='new_checkpoint' then f.native.state.checkpoint={} end
    if fault=='new_run' then f.native.run_id='different' end
    if fault=='guard_write' then f.guard.writes={autosave=1} end
    f.put(native, f.native)
    f.put(guard, f.guard)
    if fault=='torn_file' then f.files[input]='{ invalid JSON' end
    local value=f.pass()
    assert(not value.available and value.state==nil, fault)
end

assert(not fixture('re3').tick)
assert(not fixture('re2',71).tick)
print('Guest enemy readback: local identity, independent HP/death flags, replay, missing evidence and reset passed')
