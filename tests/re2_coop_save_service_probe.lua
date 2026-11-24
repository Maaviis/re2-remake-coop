-- Manual isolated test only. The supervisor supplies a disposable destination.
local config = json.load_file("re2_coop_save_service_probe_request.json")
if type(config) ~= "table" or type(config.run) ~= "string" or #config.run ~= 32
        or not config.run:match("^[0-9a-f]+$") then return end
if reframework:get_game_name() ~= "re2" or sdk.get_tdb_version() ~= 70 then return end
local result_file = "re2_coop_save_service_probe_result.json"
local done = false
local function report(result)
    json.dump_file(result_file, result)
end
local function sample()
    if done then return end
    local flow = sdk.get_managed_singleton("app.ropeway.gamemastering.MainFlowManager")
    if not flow or flow:call("get_IsInTitle") ~= true then return end
    local service = sdk.find_type_definition("via.storage.saveService.SaveService")
    local result = {run=config.run, title=true, service=service ~= nil}
    if service then
        local function getter(name)
            local method = service:get_method(name)
            if not method then return {status="missing_method"} end
            if not method:is_static() or method:get_num_params() ~= 0 then return {status="signature_mismatch"} end
            local ok, value = pcall(method.call, method, nil)
            if not ok then return {status="call_failed"} end
            if value == nil then return {status="nil"} end
            if type(value) == "boolean" or type(value) == "number" or type(value) == "string" then
                return {status="ok", value=value}
            end
            return {status="unexpected_return_type"}
        end
        result.instance = getter("hasInstance")
        if result.instance.status == "ok" and result.instance.value == true then
            result.mount = getter("get_SaveMountPath")
            result.directory = getter("get_SaveDirectoryPath")
            result.state = getter("get_SaveState")
            if config.background == true and config.mount == "./coop-save-"..config.run
                    and result.mount.status == "ok" and result.mount.value == "./win64_save"
                    and result.directory.value == "SAVESERVICE-LINE-0-" then
                local setter = service:get_method("set_SaveMountPath")
                local params = setter and setter:get_param_types()
                if setter and setter:is_static() and #params == 1 and params[1]:get_full_name() == "System.String" then
                    local ok = pcall(function() setter:call(nil, config.mount) end)
                    result.redirect = ok and getter("get_SaveMountPath") or {status="call_failed"}
                    result.redirected = ok and result.redirect.value == config.mount
                    -- The protected supervisor owns the process through exit. A Lua
                    -- reset can occur with queued writes and must not rebind them.
                end
            end
        end
    end
    report(result)
    done = true
end
re.on_pre_application_entry("UpdateBehavior", sample)
