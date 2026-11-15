local now, tick, reset, output = 100, nil, nil, nil
local busy, accessible, tdb, call_count = false, true, 70, 0
local detail = {slot = 4, stamp = 639300365010000000, scenario = 1}
function detail:call(method)
    local values = {get_EmptyData = false, get_Slot = self.slot, get_LastUpdateTimeStamp = self.stamp,
        get_Title = "Test", get_SubTitle = "Test save 4", get_Detail = "Test metadata"}
    assert(values[method] ~= nil, "unexpected detail mutation or unknown call: " .. method)
    return values[method]
end
local list = {}
function list:call(method, index)
    if method == "get_Count" then return 21 end
    assert(method == "get_Item(System.Int32)")
    return index == 4 and detail or nil
end
local manager = {}
function manager:call(method, value)
    call_count = call_count + 1
    if method == "get_IsBusy" then return busy end
    if method == "get_IsEnableAccessSaveFileDetailTbl" then return accessible end
    if method == "getSaveFileDetailList" then assert(value == 1); return list end
    if method == "getScenarioTypeFromDetailString" then assert(value == detail); return detail.scenario end
    error("unexpected save/load/remove or setter call: " .. method)
end
os.time = function() return now end
os.clock = function() return now / 10 end
reframework = {get_game_name = function() return "re2" end}
re = {on_pre_application_entry = function(name, fn) assert(name == "UpdateBehavior"); tick = fn end,
      on_script_reset = function(fn) reset = fn end}
sdk = {get_tdb_version = function() return tdb end,
       get_managed_singleton = function(name) assert(name == "app.ropeway.gamemastering.SaveDataManager"); return manager end}
json = {dump_file = function(path, value) assert(path == "re2_coop_save_catalog.json"); output = value; return true end}
log = {info = function() end}
dofile("reframework/autorun/re2_coop_save_catalog.lua")
tick()
assert(output.available and #output.entries == 1)
assert(output.entries[1].slot_id == 4 and output.entries[1].timestamp == "639300365010000000")
local first_sequence = output.sequence
tick()
assert(output.sequence == first_sequence, "same second must not be read again")
now = now + 1; busy = true; tick()
assert(not output.available and output.reason == "save_service_busy" and #output.entries == 0)
now = now + 1; busy = false; accessible = false; tick()
assert(not output.available and output.reason == "save_table_unavailable")
now = now + 1; accessible = true; detail.slot = 30; tick()
assert(not output.available and output.reason == "save_metadata_read_failed")
now = now + 1; detail.slot = 4; tdb = 69
local before = call_count; tick()
assert(not output.available and output.reason == "unsupported_tdb" and call_count == before)
reset()
assert(not output.available and output.reason == "probe_reset")
print("Native save catalog: read-only calls, null slots, busy table, invalid slot and TDB guards passed")
