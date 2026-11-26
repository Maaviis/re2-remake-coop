#include <windows.h>
#include <shellapi.h>

#include "bridge_start.h"
#include "command_pipe.h"
#include "invite_input.h"
#include "steam_peer_probe.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <reframework/API.h>
#include <steam/steam_api_flat.h>

namespace {

constexpr AppId_t re2_app = 883710;
constexpr int lobby_capacity = 2;
constexpr DWORD lobby_pipe_capacity = 1024;
constexpr char lobby_key[] = "re2_remake_coop_lobby";
constexpr char lobby_version[] = "1";
using Clock = std::chrono::steady_clock;
constexpr auto peer_interval = std::chrono::milliseconds(100);
const REFrameworkPluginFunctions* ref = nullptr;
std::filesystem::path native_peer_report;
std::filesystem::path game_directory;
void (*poll_runtime_save_protection)(const wchar_t*){};
Clock::time_point next_runtime_protection{};
bool runtime_save_protection_started{};
using SetCampaignNamespace = bool (*)(const wchar_t*, const char*);
SetCampaignNamespace set_campaign_namespace{};
std::string campaign_namespace;
uint64_steamid campaign_peer{};

void revoke_campaign_namespace() {
    if (!campaign_namespace.empty() && set_campaign_namespace) {
        set_campaign_namespace(nullptr, nullptr);
        campaign_namespace.clear();
        campaign_peer = 0;
    }
}

// RE2 build 11636119 exports the v021 user and v014 remote storage accessors.
// Resolve the flat calls from the same installed module using Valve's signatures.
using GetSteamUser = ISteamUser* (*)();
using GetRemoteStorage = ISteamRemoteStorage* (*)();

struct Steam {
    const decltype(&SteamAPI_GetHSteamUser) user_handle;
    const GetSteamUser user;
    const decltype(&SteamAPI_SteamMatchmaking_v009) matchmaking;
    const decltype(&SteamAPI_SteamUtils_v010) utils;
    const decltype(&SteamAPI_SteamFriends_v017) friends;
    const decltype(&SteamAPI_ISteamUser_BLoggedOn) logged_on;
    const decltype(&SteamAPI_ISteamUser_GetSteamID) steam_id;
    const decltype(&SteamAPI_ISteamUtils_GetAppID) app_id;
    const decltype(&SteamAPI_ISteamUtils_IsAPICallCompleted) completed;
    const decltype(&SteamAPI_ISteamUtils_GetAPICallResult) result;
    const decltype(&SteamAPI_ISteamUtils_GetAPICallFailureReason) failure_reason;
    const decltype(&SteamAPI_ISteamUtils_IsOverlayEnabled) overlay_enabled;
    const decltype(&SteamAPI_RegisterCallback) register_callback;
    const decltype(&SteamAPI_ISteamMatchmaking_CreateLobby) create;
    const decltype(&SteamAPI_ISteamMatchmaking_JoinLobby) join;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyData) get_data;
    const decltype(&SteamAPI_ISteamMatchmaking_SetLobbyData) set_data;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex) member;
    const decltype(&SteamAPI_ISteamMatchmaking_LeaveLobby) leave;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyOwner) owner;
    const decltype(&SteamAPI_ISteamMatchmaking_GetNumLobbyMembers) members;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit) member_limit;
    const decltype(&SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog) open_invite;
    const GetRemoteStorage remote_storage;
    const decltype(&SteamAPI_ISteamRemoteStorage_IsCloudEnabledForAccount) cloud_account;
    const decltype(&SteamAPI_ISteamRemoteStorage_IsCloudEnabledForApp) cloud_app;
    const decltype(&SteamAPI_ISteamUser_GetUserDataFolder) user_data_folder;

    bool available() const {
        return user_handle && user && matchmaking && utils && friends && logged_on &&
            steam_id && app_id && completed && result && failure_reason && overlay_enabled && create &&
            leave && owner && members && member_limit && open_invite && register_callback &&
            join && get_data && set_data && member;
    }
};

template<typename Function>
Function resolve(HMODULE module, const char* name) {
    // GetProcAddress is typed by the published Steam flat API at each call site.
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(GetProcAddress(module, name));
}

Steam load_steam(HMODULE module) {
#define STEAM(name) resolve<decltype(&name)>(module, #name)
    return {
        STEAM(SteamAPI_GetHSteamUser),
        resolve<GetSteamUser>(module, "SteamAPI_SteamUser_v021"),
        STEAM(SteamAPI_SteamMatchmaking_v009),
        STEAM(SteamAPI_SteamUtils_v010),
        STEAM(SteamAPI_SteamFriends_v017),
        STEAM(SteamAPI_ISteamUser_BLoggedOn),
        STEAM(SteamAPI_ISteamUser_GetSteamID),
        STEAM(SteamAPI_ISteamUtils_GetAppID),
        STEAM(SteamAPI_ISteamUtils_IsAPICallCompleted),
        STEAM(SteamAPI_ISteamUtils_GetAPICallResult),
        STEAM(SteamAPI_ISteamUtils_GetAPICallFailureReason),
        STEAM(SteamAPI_ISteamUtils_IsOverlayEnabled),
        STEAM(SteamAPI_RegisterCallback),
        STEAM(SteamAPI_ISteamMatchmaking_CreateLobby),
        STEAM(SteamAPI_ISteamMatchmaking_JoinLobby),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyData),
        STEAM(SteamAPI_ISteamMatchmaking_SetLobbyData),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyMemberByIndex),
        STEAM(SteamAPI_ISteamMatchmaking_LeaveLobby),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyOwner),
        STEAM(SteamAPI_ISteamMatchmaking_GetNumLobbyMembers),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit),
        STEAM(SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog),
        resolve<GetRemoteStorage>(module, "SteamAPI_SteamRemoteStorage_v014"),
        STEAM(SteamAPI_ISteamRemoteStorage_IsCloudEnabledForAccount),
        STEAM(SteamAPI_ISteamRemoteStorage_IsCloudEnabledForApp),
        STEAM(SteamAPI_ISteamUser_GetUserDataFolder),
    };
#undef STEAM
}

const Steam* steam_exports(HMODULE module) {
    if (!module) {
        return nullptr;
    }
    static HMODULE last_module = nullptr;
    static std::optional<Steam> steam;
    if (module != last_module || !steam) {
        steam.emplace(load_steam(module));
        last_module = module;
    }
    return steam->available() && steam->user_handle() ? &*steam : nullptr;
}

using coop::Invite;

std::mutex invite_mutex;
Invite invite_from_steam;

class InviteCallback final : public CCallbackBase {
public:
    void Run(void* payload) override {
        if (payload) {
            const auto& event = *static_cast<GameLobbyJoinRequested_t*>(payload);
            const auto id = event.m_steamIDLobby.ConvertToUint64();
            if (coop::valid_lobby_id(id)) {
                const auto inviter = event.m_steamIDFriend.IsValid() && event.m_steamIDFriend.BIndividualAccount()
                    ? event.m_steamIDFriend.ConvertToUint64() : 0;
                std::lock_guard<std::mutex> lock{invite_mutex};
                invite_from_steam = {id, inviter};
            }
        }
    }

    void Run(void* payload, bool failed, SteamAPICall_t) override {
        if (!failed) {
            Run(payload);
        }
    }

    int GetCallbackSizeBytes() override { return sizeof(GameLobbyJoinRequested_t); }
};

InviteCallback invite_callback;
bool callback_registered = false;
Clock::time_point next_callback_attempt{};
Clock::time_point next_membership_check{};
coop::InviteOffer offered_invite;

enum class Request { create, join };
enum class Role { none, host, guest };

struct LobbyState {
    SteamAPICall_t pending{};
    uint64_steamid joined{};
    Invite joining;
    std::uint32_t join_revision{};
    std::string_view join_error;
    bool checking_metadata{};
    Request request = Request::create;
    Role role = Role::none;
    std::uint32_t membership_revision{};
    uint64_steamid host{};
    Clock::time_point deadline{};
    bool discard_result{};
    bool leave_requested{};
};

LobbyState lobby;

void record_join_failure(std::string_view reason) {
    if (lobby.join_error.empty()) {
        lobby.join_error = reason;
    }
}

std::string_view join_refusal(uint32 response) {
    switch (response) {
    case k_EChatRoomEnterResponseDoesntExist: return "join-failed Steam lobby no longer exists";
    case k_EChatRoomEnterResponseNotAllowed: return "join-failed Steam refused access to this lobby";
    case k_EChatRoomEnterResponseFull: return "join-failed Steam lobby is full";
    default: return "join-failed Steam did not confirm the lobby join";
    }
}

void confirm_membership(Role role) {
    revoke_campaign_namespace();
    lobby.role = role;
    if (++lobby.membership_revision == 0) {
        ++lobby.membership_revision;
    }
}

void leave_lobby(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid id) {
    revoke_campaign_namespace();
    api.leave(matchmaking, id);
    lobby.joined = 0;
    lobby.checking_metadata = false;
    lobby.role = Role::none;
    lobby.host = 0;
    ref->log_info("RE2_COOP_STEAM_LOBBY LeaveLobby called for the probe lobby");
}

template <typename Result>
bool read_result(const Steam& api, ISteamUtils* utils, SteamAPICall_t call, Result& result) {
    bool failed = false;
    return api.result(utils, call, &result, sizeof(result), Result::k_iCallback, &failed) &&
        !failed;
}

bool guest_membership(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid id,
                      uint64_steamid local) {
    return api.owner(matchmaking, id) == lobby.host && local &&
        api.member_limit(matchmaking, id) == lobby_capacity &&
        api.members(matchmaking, id) == lobby_capacity &&
        ((api.member(matchmaking, id, 0) == local && api.member(matchmaking, id, 1) == lobby.host) ||
         (api.member(matchmaking, id, 1) == local && api.member(matchmaking, id, 0) == lobby.host));
}

void verify_guest(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid local) {
    const auto id = lobby.joined;
    const auto* marker = api.get_data(matchmaking, id, lobby_key);
    if ((!marker || !*marker) && Clock::now() < lobby.deadline && !lobby.discard_result) {
        return;
    }
    if (lobby.discard_result || !marker || std::string_view{marker} != lobby_version ||
        !guest_membership(api, matchmaking, id, local)) {
        record_join_failure("join-failed Steam lobby is incompatible or its membership changed");
        ref->log_warn("RE2_COOP_STEAM_LOBBY rejecting incompatible lobby or member list");
        leave_lobby(api, matchmaking, id);
        return;
    }
    lobby.checking_metadata = false;
    confirm_membership(Role::guest);
    ref->log_info("RE2_COOP_STEAM_LOBBY joined as guest; verified owner and two members");
}

void poll_lobby(const Steam& api, ISteamMatchmaking* matchmaking, ISteamUtils* utils,
                ISteamUser* user) {
    if (!lobby.pending) {
        return;
    }
    if (!lobby.discard_result && Clock::now() >= lobby.deadline) {
        lobby.discard_result = true;
        if (lobby.request == Request::join) {
            record_join_failure("join-failed Steam lobby join timed out");
        }
        ref->log_warn("RE2_COOP_STEAM_LOBBY request timed out; a late success will be left");
    }

    bool failed = false;
    if (!api.completed(utils, lobby.pending, &failed)) {
        if (lobby.discard_result &&
            api.failure_reason(utils, lobby.pending) == k_ESteamAPICallFailureInvalidHandle) {
            lobby.pending = 0;
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam lobby call handle expired");
        }
        return;
    }
    const auto call = lobby.pending;
    lobby.pending = 0;
    const auto local = api.steam_id(user);
    if (failed) {
        if (lobby.request == Request::join) {
            record_join_failure("join-failed Steam lobby request failed");
        }
        ref->log_warn("RE2_COOP_STEAM_LOBBY Steam lobby request failed");
        return;
    }

    if (lobby.request == Request::join) {
        LobbyEnter_t result{};
        if (!read_result(api, utils, call, result) ||
            result.m_EChatRoomEnterResponse != k_EChatRoomEnterResponseSuccess) {
            record_join_failure(join_refusal(result.m_EChatRoomEnterResponse));
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam join failed response=%u",
                          result.m_EChatRoomEnterResponse);
            return;
        }
        const auto id = result.m_ulSteamIDLobby;
        if (!coop::valid_lobby_id(id)) {
            record_join_failure("join-failed Steam returned an invalid lobby");
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam returned an invalid lobby ID");
            return;
        }
        lobby.host = api.owner(matchmaking, id);
        if (id != lobby.joining.lobby || lobby.discard_result || !lobby.host || lobby.host == local ||
            (lobby.joining.inviter && lobby.host != lobby.joining.inviter)) {
            record_join_failure("join-failed Steam lobby or owner changed");
            ref->log_warn("RE2_COOP_STEAM_LOBBY rejecting unexpected lobby or owner");
            leave_lobby(api, matchmaking, id);
            return;
        }
        lobby.joined = id;
        lobby.checking_metadata = true;
        lobby.deadline = Clock::now() + std::chrono::seconds(3);
        verify_guest(api, matchmaking, local);
        return;
    }

    LobbyCreated_t result{};
    if (!read_result(api, utils, call, result) || result.m_eResult != k_EResultOK ||
        !result.m_ulSteamIDLobby) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY create failed result=%d",
                      static_cast<int>(result.m_eResult));
        return;
    }
    const auto id = result.m_ulSteamIDLobby;
    const bool local_owner = local != 0 && api.owner(matchmaking, id) == local;
    const int members = api.members(matchmaking, id);
    const int limit = api.member_limit(matchmaking, id);
    if (lobby.discard_result || !local_owner || members != 1 || limit != lobby_capacity ||
        !api.set_data(matchmaking, id, lobby_key, lobby_version)) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY discarding lobby local_owner=%d members=%d limit=%d",
                      local_owner, members, limit);
        leave_lobby(api, matchmaking, id);
        return;
    }
    lobby.joined = id;
    confirm_membership(Role::host);
    lobby.host = local;
    ref->log_info("RE2_COOP_STEAM_LOBBY created app=%u local_owner=1 members=1 limit=2", re2_app);
}

enum class Command { none, create, join, ping };
coop::SteamPeerProbe peer_probe;
Clock::time_point next_peer_tick{};

uint64_steamid current_peer(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid local) {
    const auto id = lobby.joined;
    if (!id || !local || lobby.role == Role::none || api.owner(matchmaking, id) != lobby.host ||
        (lobby.role == Role::host && local != lobby.host) ||
        api.members(matchmaking, id) != lobby_capacity) {
        return 0;
    }
    const auto first = api.member(matchmaking, id, 0);
    const auto second = api.member(matchmaking, id, 1);
    const auto peer = first == local ? second : second == local ? first : 0;
    if (!peer || peer == local || (lobby.role == Role::guest && peer != lobby.host)) {
        return 0;
    }
    return peer;
}
coop::CommandPipe controls;
coop::CommandPipe pose_controls;
coop::CommandPipe snapshot_controls;
coop::CommandPipe combat_controls;

char payload_role() {
    return lobby.role == Role::host ? 'H' : lobby.role == Role::guest ? 'G' : '-';
}

std::string_view execute_pose(std::string_view request) {
    return peer_probe.pose_request(request, payload_role());
}

std::string_view execute_snapshot(std::string_view request) {
    return peer_probe.snapshot_request(request, payload_role());
}

std::string_view execute_combat(std::string_view request) {
    return peer_probe.combat_request(request, payload_role());
}
Command requested = Command::none;

std::string_view cloud_status() {
    const auto* api = steam_exports(GetModuleHandleW(L"steam_api64.dll"));
    if (!api || !api->remote_storage || !api->cloud_account || !api->cloud_app) {
        return "cloud-unavailable";
    }
    auto* const utils = api->utils();
    auto* const user = api->user();
    if (!utils || !user || api->app_id(utils) != re2_app || !api->logged_on(user)) {
        return "cloud-unavailable";
    }
    auto* const storage = api->remote_storage();
    if (!storage) {
        return "cloud-unavailable";
    }
    if (!api->cloud_account(storage)) {
        return "cloud-account-disabled";
    }
    return api->cloud_app(storage) ? "cloud-enabled" : "cloud-app-disabled";
}

std::string_view user_data_folder() {
    const auto* api = steam_exports(GetModuleHandleW(L"steam_api64.dll"));
    if (!api || !api->user_data_folder) {
        return "user-data-unavailable";
    }
    auto* const utils = api->utils();
    auto* const user = api->user();
    if (!utils || !user || api->app_id(utils) != re2_app || !api->logged_on(user)) {
        return "user-data-unavailable";
    }
    // This reply stays on the owner-only local pipe.
    constexpr std::string_view prefix = "user-data-folder ";
    static std::array<char, lobby_pipe_capacity> reply{};
    const auto start = reply.data() + prefix.size();
    const auto limit = reply.data() + reply.size();
    std::fill(start, limit, '\0');
    if (!api->user_data_folder(user, start, static_cast<int>(limit - start))) {
        return "user-data-unavailable";
    }
    const auto end = std::find(start, limit, '\0');
    if (end == start || end == limit) {
        return "user-data-unavailable";
    }
    prefix.copy(reply.data(), prefix.size());
    return {reply.data(), static_cast<std::size_t>(end - reply.data())};
}

std::filesystem::path active_save_directory() {
    constexpr std::string_view prefix = "user-data-folder ";
    const auto reported = user_data_folder();
    if (reported.substr(0, prefix.size()) != prefix) return {};
    try {
        const auto local = std::filesystem::u8path(reported.begin() + prefix.size(), reported.end());
        if (local.is_absolute() && _wcsicmp(local.filename().c_str(), L"local") == 0 &&
            local.parent_path().filename() == L"883710") {
            return local.parent_path() / L"remote" / L"win64_save";
        }
    } catch (const std::exception&) {
        // An invalid Steam path supplies no local protection.
    }
    return {};
}

std::string_view protect_campaign() {
    const auto cloud = cloud_status();
    if (cloud != "cloud-app-disabled" && cloud != "cloud-account-disabled") {
        return "error disable RE2 Steam Cloud before securing the prepared save";
    }
    const auto path = active_save_directory();
    if (path.empty() || game_directory.empty()) return "error active RE2 Steam save directory unavailable";
    if (runtime_save_protection_started) return "accepted protect-campaign";
    try {
        const auto save_guard = GetModuleHandleW(
            (game_directory / L"reframework" / L"plugins" / L"re2_coop_steam_save_guard.dll").c_str());
        if (!save_guard) return "error installed campaign save guard unavailable";
        using Begin = bool (*)(const wchar_t*);
        const auto begin = resolve<Begin>(save_guard, "re2_coop_begin_runtime_save_protection");
        const auto poll = resolve<void (*)(const wchar_t*)>(save_guard, "re2_coop_poll_runtime_save_protection");
        if (!begin || !poll) return "error installed campaign save guard unavailable";
        poll_runtime_save_protection = poll;
        if (!begin(path.c_str())) return "error active save copy could not be protected";
        runtime_save_protection_started = true;
        native_peer_report = game_directory / L"reframework/data/re2_coop_native_peer.json";
        return "accepted protect-campaign";
    } catch (const std::exception&) {
        return "error active save copy could not be protected";
    }
}

std::string_view open_invite_dialog() {
    if (lobby.role != Role::host || !lobby.joined || lobby.leave_requested) {
        return "error an owned Steam lobby is required to invite";
    }
    const auto* api = steam_exports(GetModuleHandleW(L"steam_api64.dll"));
    if (!api) {
        return "error RE2 Steam context is unavailable";
    }
    auto* const matchmaking = api->matchmaking();
    auto* const utils = api->utils();
    auto* const user = api->user();
    if (!matchmaking || !utils || !user || api->app_id(utils) != re2_app) {
        return "error RE2 Steam context is unavailable";
    }
    if (!api->logged_on(user)) {
        return "error Steam user is offline";
    }
    const auto local = api->steam_id(user);
    if (!local || api->owner(matchmaking, lobby.joined) != local) {
        return "error an owned Steam lobby is required to invite";
    }
    auto* const friends = api->friends();
    if (!friends || !api->overlay_enabled(utils)) {
        return "error Steam overlay is unavailable";
    }
    api->open_invite(friends, lobby.joined);
    ref->log_info("RE2_COOP_STEAM_LOBBY requested invite dialog");
    return "accepted invite-dialog";
}

std::string_view prepare_new_game(std::string_view arguments) {
    const auto space = arguments.find(' ');
    if (space == std::string_view::npos) return "error invalid campaign membership";
    const auto revision = coop::parse_lobby_revision(arguments.substr(0, space));
    const auto token = arguments.substr(space + 1);
    if (!revision || revision != lobby.membership_revision || !lobby.joined || lobby.leave_requested ||
            lobby.role == Role::none || lobby.checking_metadata) return "error Steam lobby membership changed";
    if (token.size() != 32 || token.find_first_not_of("0123456789abcdef") != std::string_view::npos) {
        return "error invalid campaign namespace";
    }
    if (!campaign_namespace.empty() && token != campaign_namespace) return "error campaign already prepared";
    const auto* api = steam_exports(GetModuleHandleW(L"steam_api64.dll"));
    if (!api || !api->user() || !api->logged_on(api->user()) || !api->matchmaking())
        return "error Steam lobby membership unavailable";
    const auto local = api->steam_id(api->user());
    if (!local || (lobby.role == Role::host ? api->owner(api->matchmaking(), lobby.joined) != local :
            !guest_membership(*api, api->matchmaking(), lobby.joined, local)))
        return "error Steam lobby membership changed";
    const auto guard_module = GetModuleHandleW(
        (game_directory / L"reframework" / L"plugins" / L"re2_coop_steam_save_guard.dll").c_str());
    if (!guard_module) return "error direct campaign save guard unavailable";
    set_campaign_namespace = resolve<SetCampaignNamespace>(guard_module, "re2_coop_set_campaign_namespace");
    if (!set_campaign_namespace) return "error direct campaign save guard unavailable";
    const auto protection = protect_campaign();
    if (protection != "accepted protect-campaign") return protection;
    const auto path = active_save_directory();
    const std::string key(token);
    if (path.empty() || !set_campaign_namespace(path.c_str(), key.c_str())) {
        revoke_campaign_namespace();
        return "error exclusive coop save directory unavailable";
    }
    campaign_namespace = key;
    return "accepted prepare-new-game";
}

std::string_view execute(std::string_view command) {
    constexpr std::string_view current_prefix = "current-campaign ";
    if (command.substr(0, current_prefix.size()) == current_prefix) {
        if (!lobby.joined || lobby.leave_requested || lobby.role == Role::none ||
                coop::parse_lobby_revision(command.substr(current_prefix.size())) != lobby.membership_revision)
            return "error Steam lobby membership changed";
        return campaign_namespace.empty() ? std::string_view("none") : std::string_view(campaign_namespace);
    }
    constexpr std::string_view prepare_prefix = "prepare-new-game ";
    if (command.substr(0, prepare_prefix.size()) == prepare_prefix) {
        return prepare_new_game(command.substr(prepare_prefix.size()));
    }
    constexpr std::string_view revoke_prefix = "revoke-new-game ";
    if (command.substr(0, revoke_prefix.size()) == revoke_prefix) {
        if (command.substr(revoke_prefix.size()) == campaign_namespace) revoke_campaign_namespace();
        return "accepted revoke-new-game";
    }
    if (command == "cloud-status") {
        return cloud_status();
    }
    if (command == "user-data-folder") {
        return user_data_folder();
    }
    if (command == "protect-campaign") {
        return protect_campaign();
    }
    if (command == "peer-status") {
        return peer_probe.status();
    }
    if (command == "ping") {
        const auto status = peer_probe.status();
        if (status != "peer-ready" && status != "peer-round-trip-verified") {
            return "error ping requires an eligible peer and no pending ping";
        }
        requested = Command::ping;
        return "accepted ping";
    }
    if (command == "status") {
        if (lobby.pending) {
            if (lobby.discard_result) {
                return "canceling";
            }
            return lobby.request == Request::join ? "joining" : "creating";
        }
        if (lobby.leave_requested) {
            return "leaving";
        }
        if (lobby.checking_metadata) {
            return "verifying";
        }
        if (lobby.role == Role::host) {
            return "owned";
        }
        if (lobby.role == Role::guest) {
            return "joined";
        }
        return offered_invite.revision() ? "invite-pending" : "idle";
    }
    if (command == "invite-revision") {
        if (lobby.pending || lobby.joined || lobby.leave_requested || !offered_invite.revision()) {
            return "none";
        }
        static std::string reply;
        reply = std::to_string(offered_invite.revision());
        return reply;
    }
    constexpr std::string_view join_error_prefix = "join-error ";
    if (command.substr(0, join_error_prefix.size()) == join_error_prefix) {
        const auto revision = coop::parse_lobby_revision(command.substr(join_error_prefix.size()));
        return revision && revision == lobby.join_revision && !lobby.join_error.empty() ? lobby.join_error : "none";
    }
    const bool active_membership = lobby.joined && lobby.role != Role::none && !lobby.leave_requested;
    if (command == "membership-revision") {
        if (!active_membership) {
            return "none";
        }
        static std::string reply;
        reply = std::to_string(lobby.membership_revision);
        return reply;
    }
    constexpr std::string_view leave_prefix = "leave ";
    const bool scoped_leave = command.substr(0, leave_prefix.size()) == leave_prefix;
    if (command == "leave" || scoped_leave) {
        if (scoped_leave && (!active_membership ||
            coop::parse_lobby_revision(command.substr(leave_prefix.size())) != lobby.membership_revision)) {
            return "error Steam lobby membership changed";
        }
        requested = Command::none;
        revoke_campaign_namespace();
        if (lobby.pending) {
            lobby.discard_result = true;
        }
        offered_invite.clear();
        lobby.leave_requested = lobby.joined != 0;
        return "accepted leave";
    }
    constexpr std::string_view join_prefix = "join-invite ";
    const bool scoped_join = command.substr(0, join_prefix.size()) == join_prefix;
    if (command == "join-invite" || scoped_join) {
        const auto revision = scoped_join ? coop::parse_lobby_revision(command.substr(join_prefix.size()))
                                          : offered_invite.revision();
        if (lobby.pending || lobby.joined || lobby.leave_requested || !offered_invite.match(revision).lobby) {
            return "error join requires a pending invite and an idle lobby";
        }
        lobby.join_revision = revision;
        lobby.join_error = {};
        requested = Command::join;
        return "accepted join-invite";
    }
    if (command == "invite-dialog") {
        return open_invite_dialog();
    }
    if (command == "create") {
        if (lobby.leave_requested || (lobby.discard_result && lobby.pending)) {
            return "error leave in progress";
        }
        requested = Command::create;
        return "accepted create";
    }
    return "error invalid command";
}

void refresh_lobby() {
    Invite incoming;
    {
        std::lock_guard<std::mutex> lock{invite_mutex};
        incoming = std::exchange(invite_from_steam, {});
    }
    if (incoming.lobby && !lobby.pending && !lobby.joined) {
        offered_invite.publish(incoming);
        ref->log_info("RE2_COOP_STEAM_LOBBY invite ready; use join-invite");
    }
    // Refresh eligibility before the pipe reports status or accepts a new ping.
    const auto command = requested;
    requested = Command::none;
    const auto now = Clock::now();
    const bool register_now = !callback_registered && now >= next_callback_attempt;
    const bool peer_tick = now >= next_peer_tick;
    if (peer_tick) {
        next_peer_tick = now + peer_interval;
    }
    const bool check_membership = lobby.role == Role::guest && now >= next_membership_check;
    if (check_membership) {
        next_membership_check = now + std::chrono::seconds(1);
    }
    if (register_now) {
        next_callback_attempt = now + std::chrono::seconds(1);
    }
    if (!register_now && !peer_tick && !check_membership && !lobby.checking_metadata &&
        command == Command::none && !lobby.pending && !lobby.leave_requested) {
        return;
    }

    const auto module = GetModuleHandleW(L"steam_api64.dll");
    if (!module) {
        revoke_campaign_namespace();
        peer_probe.suspend();
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY steam_api64.dll is not loaded");
        }
        return;
    }

    const auto* steam = steam_exports(module);
    if (!steam) {
        revoke_campaign_namespace();
        peer_probe.suspend();
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY expected Steam exports or user unavailable");
        }
        return;
    }
    const auto& api = *steam;
    auto* const matchmaking = api.matchmaking();
    auto* const utils = api.utils();
    auto* const user = api.user();
    if (!matchmaking || !utils || !user || api.app_id(utils) != re2_app) {
        revoke_campaign_namespace();
        peer_probe.suspend();
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY RE2 Steam context unavailable");
        }
        return;
    }

    if (register_now) {
        api.register_callback(&invite_callback, GameLobbyJoinRequested_t::k_iCallback);
        callback_registered = true;
        ref->log_info("RE2_COOP_STEAM_LOBBY listening for Steam join requests");
    }
    if (lobby.leave_requested) {
        peer_probe.update(0, 0);
        lobby.leave_requested = false;
        leave_lobby(api, matchmaking, lobby.joined);
    }
    if (lobby.checking_metadata) {
        verify_guest(api, matchmaking, api.steam_id(user));
    }
    poll_lobby(api, matchmaking, utils, user);
    if (check_membership && lobby.role == Role::guest &&
        !guest_membership(api, matchmaking, lobby.joined, api.steam_id(user))) {
        ref->log_info("RE2_COOP_STEAM_LOBBY guest membership ended");
        leave_lobby(api, matchmaking, lobby.joined);
    }

    const bool poll_peer = peer_tick || command == Command::ping;
    if (poll_peer && peer_probe.configure(module, api.register_callback, ref->log_info)) {
        const auto local = api.steam_id(user);
        const auto peer = api.logged_on(user) ? current_peer(api, matchmaking, local) : 0;
        if (!campaign_namespace.empty()) {
            if (!api.logged_on(user) || (campaign_peer && campaign_peer != peer)) revoke_campaign_namespace();
            else if (peer) campaign_peer = peer;
        }
        peer_probe.update(peer ? lobby.joined : 0, peer);
    } else if (poll_peer) {
        revoke_campaign_namespace();
    }

    switch (command) {
    case Command::ping:
        peer_probe.ping();
        break;
    case Command::create:
        if (lobby.pending || lobby.joined) {
            ref->log_info("RE2_COOP_STEAM_LOBBY request already pending or active");
        } else if (api.logged_on(user)) {
            offered_invite.clear();
            lobby.request = Request::create;
            lobby.pending = api.create(matchmaking, k_ELobbyTypePrivate, lobby_capacity);
            lobby.discard_result = false;
            lobby.deadline = Clock::now() + std::chrono::seconds(15);
            if (lobby.pending) {
                ref->log_info("RE2_COOP_STEAM_LOBBY requested private lobby app=%u", re2_app);
            } else {
                ref->log_warn("RE2_COOP_STEAM_LOBBY CreateLobby returned an invalid call handle");
            }
        } else {
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam user is offline");
        }
        break;
    case Command::join: {
        const auto invite = offered_invite.match(lobby.join_revision);
        if (!invite.lobby) {
            record_join_failure("join-failed Steam invitation changed");
            ref->log_warn("RE2_COOP_STEAM_LOBBY join skipped; offered invite changed");
            break;
        }
        if (!api.logged_on(user)) {
            record_join_failure("join-failed Steam user is offline");
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam user is offline");
            break;
        }
        lobby.joining = invite;
        lobby.request = Request::join;
        lobby.pending = api.join(matchmaking, invite.lobby);
        lobby.discard_result = false;
        lobby.deadline = now + std::chrono::seconds(15);
        if (lobby.pending) {
            offered_invite.clear();
            ref->log_info("RE2_COOP_STEAM_LOBBY requested guest join");
        } else {
            record_join_failure("join-failed Steam could not start the lobby join");
            ref->log_warn("RE2_COOP_STEAM_LOBBY JoinLobby returned an invalid call handle");
        }
        break;
    }
    case Command::none:
        break;
    }
}

void publish_protected_peer() {
    if (native_peer_report.empty()) {
        return;
    }
    static std::string last_epoch;
    static std::string last_equipment_pose_epoch;
    static std::uint64_t last_guest_account{};
    static std::uint32_t last_revision{};
    static char last_role{};
    static Clock::time_point next_report{};
    const auto now = Clock::now();
    const auto role = payload_role();
    const auto peer = lobby.leave_requested ? coop::SnapshotPeer{} : peer_probe.snapshot_peer(role, lobby.joined);
    const auto epoch = peer.epoch;
    if (now < next_report && epoch == last_epoch && peer.guest_account_id == last_guest_account &&
        peer.equipment_pose_epoch == last_equipment_pose_epoch && lobby.membership_revision == last_revision && role == last_role) {
        return;
    }
    try {
        auto temporary = native_peer_report;
        temporary += L".tmp";
        bool solo_host = false;
        if (epoch.empty() && lobby.joined && lobby.role == Role::host && !lobby.leave_requested && !campaign_namespace.empty()) {
            const auto* api = steam_exports(GetModuleHandleW(L"steam_api64.dll"));
            if (api && api->user() && api->logged_on(api->user()) && api->matchmaking()) {
                auto* const matchmaking = api->matchmaking();
                const auto local = api->steam_id(api->user());
                solo_host = local && api->owner(matchmaking, lobby.joined) == local &&
                    api->members(matchmaking, lobby.joined) == 1;
            }
        }
        {
            std::ofstream file(temporary, std::ios::binary | std::ios::trunc);
            file << "{\"schema\":1,\"at\":" << std::time(nullptr)
                 << ",\"game_pid\":" << GetCurrentProcessId()
                 << ",\"role\":\"" << (epoch.empty() ? '-' : role)
                 << "\",\"solo_host\":" << (solo_host ? "true" : "false") << ",\"revision\":" << lobby.membership_revision
                 << ',';
            peer.write_fields(file);
            file << '}';
            file.close();
            if (!file) {
                return;
            }
        }
        if (MoveFileExW(temporary.c_str(), native_peer_report.c_str(), MOVEFILE_REPLACE_EXISTING)) {
            last_epoch = epoch;
            last_equipment_pose_epoch = peer.equipment_pose_epoch;
            last_guest_account = peer.guest_account_id;
            last_revision = lobby.membership_revision;
            last_role = role;
            next_report = now + std::chrono::milliseconds(500);
        }
    } catch (const std::exception&) {
        // An absent or expired report prevents native campaign release.
    }
}

// A window timer can run on a different thread or inside a nested message loop.
// Neither path may re-enter the shared Steam/pipe state.
std::atomic_flag transport_busy = ATOMIC_FLAG_INIT;
struct TransportPoll {
    const bool acquired = !transport_busy.test_and_set(std::memory_order_acquire);
    ~TransportPoll() { if (acquired) transport_busy.clear(std::memory_order_release); }
};

std::string_view execute_background_query(std::string_view command) {
    // The bridge revalidates cloud and save ownership while a campaign is active.
    // These Steam queries are read-only, like the lobby status on this timer.
    if (command == "status" || command == "membership-revision" ||
        command == "invite-revision" || command == "peer-status" ||
        command == "cloud-status" || command == "user-data-folder" ||
        command.substr(0, 11) == "join-error ") {
        return execute(command);
    }
    return "error return to the RE2 window and retry this command";
}

// Accessed only on the window's owner thread. KillTimer can leave a queued tick.
thread_local HWND inactive_window{};
Clock::time_point last_frame{};
void CALLBACK background_transport(HWND window, UINT, UINT_PTR, DWORD) {
    if (window != inactive_window || !IsWindow(window)) return;
    const TransportPoll poll;
    if (!poll.acquired || Clock::now() - last_frame < peer_interval) return;
    refresh_lobby();
    controls.poll(execute_background_query);
    pose_controls.poll(execute_pose);
}

bool on_window_message(void* handle, unsigned int message, unsigned long long wparam, long long) {
    const auto window = static_cast<HWND>(handle);
    const auto timer_id = reinterpret_cast<UINT_PTR>(&transport_busy);
    const bool inactive = (message == WM_ACTIVATEAPP && !wparam) ||
        (message == WM_SIZE && wparam == SIZE_MINIMIZED);
    if (inactive && window != inactive_window) {
        if (inactive_window) KillTimer(std::exchange(inactive_window, nullptr), timer_id);
        // REFramework owns loaded plugins for the game lifetime. A posted TIMERPROC
        // can outlive KillTimer, so retain its code for the same process lifetime.
        static const bool timer_code_pinned = [] {
            HMODULE module{};
            return GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                                      reinterpret_cast<LPCWSTR>(&transport_busy), &module) != FALSE;
        }();
        if (timer_code_pinned && SetTimer(window, timer_id, USER_TIMER_MINIMUM, background_transport)) {
            inactive_window = window;
        }
    } else if (window == inactive_window &&
               ((message == WM_ACTIVATEAPP && wparam) || message == WM_NCDESTROY)) {
        inactive_window = nullptr;
        KillTimer(window, timer_id);
    }
    return true;
}

void on_update() {
    const TransportPoll poll;
    if (!poll.acquired) return;
    last_frame = Clock::now();
    refresh_lobby();
    controls.poll(execute);
    pose_controls.poll(execute_pose);
    snapshot_controls.poll(execute_snapshot);
    combat_controls.poll(execute_combat);
    const auto now = Clock::now();
    if (poll_runtime_save_protection && now >= next_runtime_protection) {
        next_runtime_protection = now + std::chrono::seconds(1);
        const auto path = active_save_directory();
        poll_runtime_save_protection(path.empty() ? nullptr : path.c_str());
    }
    publish_protected_peer();
}

void start_installed_bridge() {
    try {
        std::array<wchar_t, 32768> executable{};
        const auto count = GetModuleFileNameW(nullptr, executable.data(), static_cast<DWORD>(executable.size()));
        if (count == 0 || count >= executable.size()) {
            return;
        }
        const std::filesystem::path game_executable(executable.data());
        if (_wcsicmp(game_executable.filename().c_str(), L"re2.exe") != 0) {
            return;
        }
        game_directory = game_executable.parent_path();
        wchar_t guarded_launch[2]{};
        if (GetEnvironmentVariableW(L"RE2_COOP_SAVE_GUARD_RUN_ID", guarded_launch, 2) != 0) {
            native_peer_report = game_executable.parent_path() / L"reframework" / L"data" / L"re2_coop_native_peer.json";
            return;
        }
        const auto started = coop::start_packaged_bridge(game_executable.parent_path(), GetCurrentProcessId());
        if (started == coop::BridgeStart::started) {
            ref->log_info("RE2_COOP_STEAM_LOBBY installed bridge process started");
        } else if (started == coop::BridgeStart::failed) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY installed bridge process could not start");
        }
    } catch (const std::exception&) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY installed bridge startup failed");
    }
}

} // namespace

extern "C" __declspec(dllexport) void reframework_plugin_required_version(REFrameworkPluginVersion* version) {
    *version = {REFRAMEWORK_PLUGIN_VERSION_MAJOR, REFRAMEWORK_PLUGIN_VERSION_MINOR,
                REFRAMEWORK_PLUGIN_VERSION_PATCH, nullptr};
}

extern "C" __declspec(dllexport) bool reframework_plugin_initialize(const REFrameworkPluginInitializeParam* param) {
    const TransportPoll initializing;
    if (!initializing.acquired) return false;
    ref = param->functions;
    if (!controls.open(L"lobby", lobby_pipe_capacity) || !pose_controls.open(L"pose", 4105) ||
        !snapshot_controls.open(L"snapshot", 4105) || !combat_controls.open(L"combat", 4105)) {
        ref->log_error("RE2_COOP_STEAM_LOBBY local command pipe could not open");
        return false;
    }
    if (!ref->on_pre_application_entry("UpdateBehavior", on_update)) {
        return false;
    }
    int argc{};
    if (auto** argv = CommandLineToArgvW(GetCommandLineW(), &argc)) {
        offered_invite.publish({coop::launch_lobby(argc, argv), 0});
        LocalFree(argv);
    }
    if (offered_invite.revision()) {
        ref->log_info("RE2_COOP_STEAM_LOBBY startup invite ready; use join-invite");
    }
    start_installed_bridge();
    if (!ref->on_message(on_window_message)) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY background transport timer unavailable");
    }
    ref->log_info("RE2_COOP_STEAM_LOBBY terminal control ready");
    return true;
}
