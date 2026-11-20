-- Opt-in local callback export. No game commands, native getters or I/O in onDead hooks.
if reframework:get_game_name()~='re2' then return end
local ok,reader=pcall(function() return require('re2_coop.death_observer').new() end)
local run_id=string.format('death-%d-%.6f',os.time(),os.clock())
local frames,sequence,stopped=0,0,false
local function publish(available,reason)
    sequence=sequence+1
    pcall(json.dump_file,'re2_coop_death_observer.json',{schema=1,source='re2',tdb=sdk.get_tdb_version(),
        scope='native_em0000_on_dead_callbacks',run_id=run_id,sequence=sequence,observed_at=os.time(),
        available=available,reason=reason,state=available and reader:snapshot() or nil})
end
if not ok then
    publish(false,'unsupported_interfaces')
    pcall(log.info,'RE2_COOP_DEATH_OBSERVER unavailable: ' .. tostring(reader))
    return
end
re.on_application_entry('UpdateBehavior',function()
    if stopped then return end
    frames=frames+1
    if frames%6==0 then
        local started,reason=reader:start()
        publish(started,started and 'ok' or reason)
    end
end)
re.on_script_reset(function() stopped=true;reader:stop();publish(false,'script_reset') end)
