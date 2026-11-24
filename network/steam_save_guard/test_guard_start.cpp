#include <windows.h>
#include <reframework/API.h>

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <string>
#include <string_view>
#include <sstream>

namespace {
int hooks{};
REFOnPreApplicationEntryCb tick{};
void log(const char*, ...) {}
bool register_update(const char* name, REFOnPreApplicationEntryCb callback) {
    if (std::string_view(name) != "UpdateBehavior" || !callback) {
        return false;
    }
    ++hooks;
    tick = callback;
    return true;
}

std::string proof(DWORD thread, char nonce) {
    std::ostringstream result;
    result << std::hex << std::setfill('0') << std::setw(8) << thread << ':' << std::string(32, nonce);
    return result.str();
}

std::string read(const std::filesystem::path& path) {
    std::ifstream file(path, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>{file}, {});
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) {
        return 1;
    }
    const auto plugin = LoadLibraryW(argv[1]);
    if (!plugin) {
        return 1;
    }
    using Initialize = bool (*)(const REFrameworkPluginInitializeParam*);
#pragma warning(suppress : 4191)
    const auto initialize = reinterpret_cast<Initialize>(GetProcAddress(plugin, "reframework_plugin_initialize"));
    using SetNamespace = bool (*)(const wchar_t*, const char*);
#pragma warning(suppress : 4191)
    const auto set_namespace = reinterpret_cast<SetNamespace>(GetProcAddress(plugin, "re2_coop_set_campaign_namespace"));
    if (!initialize || !set_namespace || !set_namespace(nullptr, nullptr) ||
        set_namespace(nullptr, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")) {
        return 1;
    }

    REFrameworkPluginFunctions api{};
    api.log_error = log;
    api.log_info = log;
    api.on_pre_application_entry = register_update;
    REFrameworkPluginInitializeParam parameters{};
    parameters.functions = &api;
    constexpr auto environment = "RE2_COOP_SAVE_GUARD_RUN_ID";
    const auto data = std::filesystem::absolute(argv[0]).parent_path() / L"reframework" / L"data";
    const auto report = data / L"re2_coop_native_save_guard.json";
    const auto challenge = data / L"re2_coop_save_guard_challenge.txt";
    std::filesystem::create_directories(data);
    std::ofstream(report, std::ios::binary) << "previous-process-proof";
    const auto owned_challenge = proof(GetCurrentThreadId(), 'b');
    std::ofstream(challenge, std::ios::binary) << owned_challenge;

    for (const auto token : {static_cast<const char*>(nullptr), "bad", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}) {
        if (!SetEnvironmentVariableA(environment, token) || !initialize(&parameters) || hooks != 0) {
            std::cerr << "Ordinary launch registered a native storage hook\n";
            return 1;
        }
        if (read(report) != "previous-process-proof") {
            std::cerr << "Ordinary launch activated the native guard publisher\n";
            return 1;
        }
    }
    if (!SetEnvironmentVariableA(environment, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        || !initialize(&parameters) || hooks != 1) {
        std::cerr << "Explicit protected launch did not register the native guard\n";
        return 1;
    }
    const auto content = read(report);
    if (content.find("\"lua_challenge\":\"" + owned_challenge + "\"") == std::string::npos ||
        content.find("\"active\":false") == std::string::npos) {
        std::cerr << "Protected launch did not export the exact Lua challenge while waiting for Steam\n";
        return 1;
    }
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION child{};
    if (!CreateProcessW(argv[0], nullptr, nullptr, nullptr, FALSE, CREATE_SUSPENDED | CREATE_NO_WINDOW,
                        nullptr, nullptr, &startup, &child)) {
        return 1;
    }
    const auto foreign_challenge = proof(child.dwThreadId, 'c');
    std::ofstream(challenge, std::ios::binary) << foreign_challenge;
    // The plugin heartbeat is once a second.
    Sleep(1150);
    tick();
    TerminateProcess(child.hProcess, 0);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    const auto latest = read(report);
    if (latest.find("\"lua_challenge\":\"" + owned_challenge + "\"") == std::string::npos ||
        latest.find(foreign_challenge) != std::string::npos) {
        std::cerr << "Native guard accepted a challenge from another live process\n";
        return 1;
    }
    return 0;
}
