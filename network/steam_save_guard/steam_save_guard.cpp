#include <windows.h>
#include <bcrypt.h>
#include <reframework/API.h>
#include "runtime_save_locks.h"
#include "storage_guard.h"
#include "checkpoint_import.h"
#include "checkpoint_title.h"
#include <algorithm>
#include <charconv>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <utility>

namespace {
const REFrameworkPluginFunctions* ref{};
const REFrameworkSDKData* engine_sdk{};
coop::CheckpointImport checkpoint_import;
const char* import_rejection = "";
std::unique_ptr<coop::RuntimeSaveLocks> runtime_locks;
coop::StorageGuard guard;
std::mutex control_mutex;
std::filesystem::path directory;
std::string run_id;
std::string accepted_challenge;
using Clock = std::chrono::steady_clock;
Clock::time_point next_report{};
constexpr std::uint32_t app_id = 883710;
constexpr std::int32_t build_id = 11636119;
const char* last_reason = "";

bool lowercase_hex(char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
}

std::string lua_challenge() {
    std::ifstream file(directory / L"re2_coop_save_guard_challenge.txt", std::ios::binary);
    std::string value(41, '\0');
    if (!file.read(value.data(), static_cast<std::streamsize>(value.size()))
            || file.peek() != std::char_traits<char>::eof()
            || value[8] != ':' || !std::all_of(value.begin() + 9, value.end(), lowercase_hex)) {
        return accepted_challenge;
    }
    if (value != accepted_challenge) {
        DWORD owner{};
        const auto end = value.data() + 8;
        const auto decoded = std::from_chars(value.data(), end, owner, 16);
        if (decoded.ec == std::errc{} && decoded.ptr == end && owner != 0) {
            const auto handle = OpenThread(THREAD_QUERY_LIMITED_INFORMATION, FALSE, owner);
            if (handle) {
                const auto process = GetProcessIdOfThread(handle);
                CloseHandle(handle);
                if (process == GetCurrentProcessId()) accepted_challenge = std::move(value);
            }
        }
    }
    return accepted_challenge;
}

template<typename Function>
Function resolve(HMODULE module, const char* name) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(GetProcAddress(module, name));
}

void publish(bool active, const char* reason) {
    if (std::string(reason) != last_reason) {
        ref->log_info("RE2_COOP_NATIVE_SAVE_GUARD active=%d reason=%s", active ? 1 : 0, reason);
        last_reason = reason;
    }
    try {
        std::filesystem::create_directories(directory);
        const auto temp = directory / L"re2_coop_native_save_guard.json.tmp";
        const auto target = directory / L"re2_coop_native_save_guard.json";
        const auto counts = coop::storage_counts();
        std::uint64_t total{};
        for (const auto count : counts) total += count;
        {
            std::ofstream file(temp, std::ios::binary | std::ios::trunc);
            file << "{\"schema\":1,\"source\":\"steam_storage_guard\",\"at\":" << std::time(nullptr)
                 << ",\"game_pid\":" << GetCurrentProcessId() << ",\"run_id\":\"" << run_id
                 << "\",\"lua_challenge\":\"" << lua_challenge()
                 << "\",\"app_id\":" << app_id
                 << ",\"build_id\":" << build_id << ",\"interface\":\"014\",\"active\":"
                 << (active ? "true" : "false") << ",\"reason\":\"" << reason
                 << "\",\"guarded_methods\":" << coop::guarded_methods
                 << ",\"blocked_calls\":" << total << ",\"counters\":{";
            for (std::size_t i = 0; i != counts.size(); ++i) {
                if (i) file << ',';
                file << '"' << coop::storage_methods()[i].name << "\":" << counts[i];
            }
            file << '}';
            const auto campaign = guard.campaign_namespace();
            if (active && !campaign.empty()) file << ",\"campaign_namespace\":\"" << campaign << '"';
            if (runtime_locks) {
                // Steam returns a Windows path. The generic spelling uses
                // forward slashes and Windows forbids quotes and controls.
                file << ",\"runtime_locked_files\":" << runtime_locks->size()
                     << ",\"runtime_save_path\":\"" << runtime_locks->directory().generic_u8string() << '"';
            }
            if (!checkpoint_import.request().request_id.empty()) {
                const auto& request = checkpoint_import.request();
                file << ",\"checkpoint_import\":{\"request_id\":\"" << request.request_id
                     << "\",\"workspace\":\"" << request.workspace << "\",\"archive_namespace\":\""
                     << request.archive_namespace << "\",\"generation\":\"" << request.generation
                     << "\",\"phase\":\"" << checkpoint_import.phase() << "\",\"error\":\"" << checkpoint_import.error()
                     << "\",\"file_index\":" << checkpoint_import.file_index()
                     << ",\"native_result\":" << checkpoint_import.native_result() << '}';
            }
            if (*import_rejection) file << ",\"checkpoint_import_rejection\":\"" << import_rejection << '\"';
            file << '}';
            if (!file) return;
        }
        MoveFileExW(temp.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    } catch (...) {
        ref->log_error("RE2_COOP_NATIVE_SAVE_GUARD status export failed");
    }
}

bool trusted_table(void* object) {
    const auto client = GetModuleHandleW(L"steamclient64.dll");
    const auto api = GetModuleHandleW(L"steam_api64.dll");
    if (!object || !client || !api) return false;
    const auto table = *reinterpret_cast<void***>(object);
    for (std::size_t index = 0; index != coop::storage_prefix_size; ++index) {
        HMODULE owner{};
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCWSTR>(table[index]), &owner) || (owner != client && owner != api)) return false;
    }
    return true;
}

const char* refresh_storage_guard(bool runtime = false) {
    const auto module = GetModuleHandleW(L"steam_api64.dll");
    if (!module) return "waiting_for_steam";
    using GetHandle = int(*)();
    using GetInterface = void*(*)();
    using FindInterface = void*(*)(int, const char*);
    using GetApp = std::uint32_t(*)(void*);
    using GetBuild = std::int32_t(*)(void*);
    const auto user = resolve<GetHandle>(module, "SteamAPI_GetHSteamUser");
    const auto storage = resolve<GetInterface>(module, "SteamAPI_SteamRemoteStorage_v014");
    const auto find = resolve<FindInterface>(module, "SteamInternal_FindOrCreateUserInterface");
    const auto utils = resolve<GetInterface>(module, "SteamAPI_SteamUtils_v010");
    const auto apps = resolve<GetInterface>(module, "SteamAPI_SteamApps_v008");
    const auto app = resolve<GetApp>(module, "SteamAPI_ISteamUtils_GetAppID");
    const auto build = resolve<GetBuild>(module, "SteamAPI_ISteamApps_GetAppBuildId");
    if (!user || !storage || !find || !utils || !apps || !app || !build || !user()) {
        return "waiting_for_steam";
    }
    auto* const utilities = utils();
    auto* const application = apps();
    if (!utilities || !application) return "waiting_for_steam";
    if (app(utilities) != app_id || build(application) != build_id) {
        return "unsupported_game_build";
    }
    auto* const current = storage();
    auto* const direct = find(user(), "STEAMREMOTESTORAGE_INTERFACE_VERSION014");
    if (!current || current != direct) return "storage_context_mismatch";
    if (runtime) {
        using Cloud = bool(*)(void*);
        const auto account = resolve<Cloud>(module, "SteamAPI_ISteamRemoteStorage_IsCloudEnabledForAccount");
        const auto app_cloud = resolve<Cloud>(module, "SteamAPI_ISteamRemoteStorage_IsCloudEnabledForApp");
        if (!account || !app_cloud || (account(current) && app_cloud(current))) return "steam_cloud_enabled_or_unavailable";
    }
    if (!guard.table()) {
        if (!trusted_table(current)) return "untrusted_storage_table";
        if (!guard.attach(current)) return guard.error();
    }
    if (*reinterpret_cast<void***>(current) != guard.table() || !guard.intact()) {
        return "storage_table_changed";
    }
    return nullptr;
}

void tick() {
    std::lock_guard<std::mutex> lock(control_mutex);
    const auto now = Clock::now();
    if (now < next_report) return;
    next_report = now + std::chrono::seconds(1);
    const auto reason = refresh_storage_guard();
    publish(!reason, reason ? reason : "ok");
}

bool completed(std::uint64_t call) {
    const auto module = GetModuleHandleW(L"steam_api64.dll");
    if (!module) return false;
    using GetUtils = void*(*)();
    using Complete = bool(*)(void*, std::uint64_t, bool*);
    const auto get = resolve<GetUtils>(module, "SteamAPI_SteamUtils_v010");
    const auto check = resolve<Complete>(module, "SteamAPI_ISteamUtils_IsAPICallCompleted");
    auto* const utils = get ? get() : nullptr;
    bool failed{};
    return utils && check && check(utils, call, &failed);
}

std::filesystem::path registered_userdata() {
    wchar_t value[32768]{};
    DWORD size = sizeof(value);
    if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", L"SteamPath", RRF_RT_REG_SZ, nullptr,
                     value, &size) != ERROR_SUCCESS) return {};
    return std::filesystem::path(value) / L"userdata";
}

bool campaign_healthy() {
    return runtime_locks && runtime_locks->matches(runtime_locks->directory()) && !refresh_storage_guard(true);
}
} // namespace

extern "C" __declspec(dllexport) void reframework_plugin_required_version(REFrameworkPluginVersion* version) {
    *version = {REFRAMEWORK_PLUGIN_VERSION_MAJOR, REFRAMEWORK_PLUGIN_VERSION_MINOR,
                REFRAMEWORK_PLUGIN_VERSION_PATCH, nullptr};
}

extern "C" __declspec(dllexport) bool reframework_plugin_initialize(const REFrameworkPluginInitializeParam* param) {
    ref = param->functions;
    engine_sdk = param->sdk;
    wchar_t path[32768]{};
    const auto length = GetModuleFileNameW(nullptr, path, static_cast<DWORD>(std::size(path)));
    if (!length || length >= std::size(path)) return false;
    const std::filesystem::path executable(path);
    if (_wcsicmp(executable.filename().c_str(), L"re2.exe") != 0) return false;
    directory = executable.parent_path() / L"reframework" / L"data";
    char token[33]{};
    if (GetEnvironmentVariableA("RE2_COOP_SAVE_GUARD_RUN_ID", token, sizeof(token)) != 32
            || !std::all_of(token, token + 32, lowercase_hex)) {
        // Ordinary Steam starts only activate after the existing lobby
        // plugin supplies the opted-in and already protected save directory.
        return true;
    }
    run_id.assign(token, 32);
    tick();
    return ref->on_pre_application_entry("UpdateBehavior", tick);
}

extern "C" __declspec(dllexport) bool re2_coop_begin_runtime_save_protection(const wchar_t* save_directory) {
    std::lock_guard<std::mutex> lock(control_mutex);
    if (!ref || directory.empty() || !save_directory || !run_id.empty()) return false;
    try {
        unsigned char seed[16]{};
        if (BCryptGenRandom(nullptr, seed, sizeof(seed), BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0) return false;
        std::string token;
        token.reserve(32);
        constexpr char hex[] = "0123456789abcdef";
        for (const auto byte : seed) {
            token += hex[byte >> 4];
            token += hex[byte & 0x0f];
        }
        auto locks = std::make_unique<coop::RuntimeSaveLocks>();
        if (!locks->acquire(save_directory)) return false;
        const auto reason = refresh_storage_guard(true);
        if (reason && !guard.table()) return false;
        // If Steam's table was partially changed, retain the file locks until
        // game exit and publish failure instead of enabling campaign loading.
        runtime_locks = std::move(locks);
        run_id = std::move(token);
        publish(!reason, reason ? reason : "ok");
        return !reason;
    } catch (const std::exception&) {
        return false;
    }
}

extern "C" __declspec(dllexport) void re2_coop_poll_runtime_save_protection(const wchar_t* current_directory) {
    std::lock_guard<std::mutex> lock(control_mutex);
    if (!runtime_locks) return;
    try {
        const auto reason = !current_directory || !runtime_locks->matches(current_directory)
            ? "runtime_save_protection_lost" : refresh_storage_guard(true);
        if (reason) guard.set_campaign({}, nullptr);
        else guard.retire_completed(completed);
        publish(!reason, reason ? reason : "ok");
    } catch (const std::exception&) {
        guard.set_campaign({}, nullptr);
        publish(false, "runtime_save_protection_lost");
    }
}

extern "C" __declspec(dllexport) bool re2_coop_set_campaign_namespace(const wchar_t* save_directory, const char* token) {
    std::lock_guard<std::mutex> lock(control_mutex);
    guard.set_campaign({}, nullptr);
    if (!runtime_locks) return token == nullptr;
    try {
        const auto reason = !runtime_locks->intact() ? "runtime_save_protection_lost" : refresh_storage_guard(true);
        bool accepted = !token;
        if (token && !reason && save_directory && runtime_locks->matches(save_directory)) {
            accepted = guard.set_campaign(runtime_locks->directory(), token, registered_userdata(), campaign_healthy, completed);
        }
        publish(!reason, reason ? reason : "ok");
        return accepted;
    } catch (const std::exception&) {
        guard.set_campaign({}, nullptr);
        publish(false, "runtime_save_protection_lost");
        return false;
    }
}

namespace {
int checkpoint_write_result(std::uint64_t call) {
    const auto module = GetModuleHandleW(L"steam_api64.dll");
    using GetUtils = void*(*)();
    using Result = bool(*)(void*, std::uint64_t, void*, int, int, bool*);
    const auto get = module ? resolve<GetUtils>(module, "SteamAPI_SteamUtils_v010") : nullptr;
    const auto result = module ? resolve<Result>(module, "SteamAPI_ISteamUtils_GetAPICallResult") : nullptr;
    auto* const utils = get ? get() : nullptr;
    // Pinned RemoteStorageFileWriteAsyncComplete_t: callback 1331, one EResult.
    std::int32_t code{};
    bool failed{};
    return utils && result && result(utils, call, &code, sizeof(code), 1331, &failed) && !failed ? code : -1;
}
}

extern "C" __declspec(dllexport) bool re2_coop_import_checkpoint(const char* command) {
    std::lock_guard<std::mutex> lock(control_mutex);
    if (!runtime_locks || !command || strnlen_s(command, 513) > 512) return false;
    const auto selection = coop::parse_checkpoint_import(command);
    if (!selection || !campaign_healthy()) return false;
    const auto title = coop::checkpoint_title(engine_sdk);
    import_rejection = title.ready ? "" : title.check;
    const bool accepted = checkpoint_import.start(*selection, guard, title.ready);
    if (!accepted && title.ready) import_rejection = "checkpoint_binding_or_job_changed";
    publish(true, "ok");
    return accepted;
}

// Called only by the lobby's UpdateBehavior entry, never its window timer.
extern "C" __declspec(dllexport) void re2_coop_poll_checkpoint_import() {
    std::lock_guard<std::mutex> lock(control_mutex);
    if (!checkpoint_import.active()) return;
    const auto title = coop::checkpoint_title(engine_sdk);
    if (!title.ready) import_rejection = title.check;
    checkpoint_import.tick(guard, {completed, checkpoint_write_result}, title.ready);
    const auto reason = refresh_storage_guard(true);
    publish(!reason, reason ? reason : "ok");
}

extern "C" __declspec(dllexport) bool re2_coop_cancel_checkpoint_import(const char* request_id) {
    std::lock_guard<std::mutex> lock(control_mutex);
    if (!request_id || strnlen_s(request_id, 33) != 32) return false;
    const bool cancelled = checkpoint_import.cancel(request_id);
    if (cancelled) {
        const auto reason = refresh_storage_guard(true);
        publish(!reason, reason ? reason : "ok");
    }
    return cancelled;
}
