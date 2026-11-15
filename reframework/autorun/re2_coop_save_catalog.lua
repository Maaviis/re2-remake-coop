-- Read the existing scenario-save metadata table; never request save/load/remove.
if reframework:get_game_name() ~= "re2" then return end
local filename = "re2_coop_save_catalog.json"
local manager_name = "app.ropeway.gamemastering.SaveDataManager"
local run_id = string.format("catalog-%d-%.6f", os.time(), os.clock())
local sequence, last_sample, last_report = 0, nil, nil

local function integer(value, low, high)
    return type(value) == "number" and value % 1 == 0 and value >= low and value <= high
end

local function text(value, limit)
    assert(type(value) == "string" and #value <= limit, "invalid_save_metadata_text")
    return value
end

local function publish(entries, reason)
    sequence = sequence + 1
    local value = {schema = 1, source = "re2", tdb = sdk.get_tdb_version(), mode = 1,
        run_id = run_id, sequence = sequence, observed_at = os.time(),
        available = reason == nil, reason = reason or "ok", entries = entries}
    local ok, result = pcall(json.dump_file, filename, value)
    if not ok or result == false then reason = "catalog_export_failed" end
    local report = reason or ("available slots=" .. #entries)
    if report ~= last_report then
        log.info("RE2_COOP_SAVE_CATALOG " .. report)
        last_report = report
    end
end

local function read_catalog()
    if sdk.get_tdb_version() ~= 70 then return {}, "unsupported_tdb" end
    local manager = sdk.get_managed_singleton(manager_name)
    if not manager then return {}, "save_manager_unavailable" end
    if manager:call("get_IsBusy") then return {}, "save_service_busy" end
    if not manager:call("get_IsEnableAccessSaveFileDetailTbl") then return {}, "save_table_unavailable" end
    -- SaveMode.SCENARIO = 1, inspected in the RE2 TDB 70 runtime.
    local list = manager:call("getSaveFileDetailList", 1)
    if not list then return {}, "save_table_unavailable" end
    local count = list:call("get_Count")
    assert(integer(count, 0, 21), "invalid_save_table_size")
    local entries, seen = {}, {}
    for index = 0, count - 1 do
        local detail = list:call("get_Item(System.Int32)", index)
        if detail and not detail:call("get_EmptyData") then
            local slot_id = detail:call("get_Slot")
            assert(integer(slot_id, 0, 20) and not seen[slot_id], "invalid_save_slot")
            seen[slot_id] = true
            local timestamp = detail:call("get_LastUpdateTimeStamp")
            assert(math.type(timestamp) == "integer" and timestamp > 0, "invalid_save_timestamp")
            local scenario = manager:call("getScenarioTypeFromDetailString", detail)
            assert(integer(scenario, 0, 3), "unsupported_save_scenario")
            entries[#entries + 1] = {slot_id = slot_id, timestamp = tostring(timestamp), scenario = scenario,
                title = text(detail:call("get_Title"), 256),
                subtitle = text(detail:call("get_SubTitle"), 512),
                detail = text(detail:call("get_Detail"), 2048)}
        end
    end
    if manager:call("get_IsBusy") or not manager:call("get_IsEnableAccessSaveFileDetailTbl") then
        return {}, "save_service_busy"
    end
    table.sort(entries, function(a, b) return a.slot_id < b.slot_id end)
    return entries
end

re.on_pre_application_entry("UpdateBehavior", function()
    local now = os.time()
    if now == last_sample then return end
    last_sample = now
    local ok, entries, reason = pcall(read_catalog)
    if ok then publish(entries, reason) else publish({}, "save_metadata_read_failed") end
end)

re.on_script_reset(function() publish({}, "probe_reset") end)
