#include <windows.h>
#include <shellapi.h>

#include "command_pipe.h"
#include "invite_input.h"
#include "steam_peer_probe.h"

#include <chrono>
#include <mutex>
#include <optional>
#include <utility>
#include <reframework/API.h>
#include <steam/steam_api_flat.h>

namespace {

constexpr AppId_t re2_app = 883710;
constexpr int lobby_capacity = 2;
constexpr char lobby_key[] = "re2_remake_coop_lobby";
constexpr char lobby_version[] = "1";
using Clock = std::chrono::steady_clock;
const REFrameworkPluginFunctions* ref = nullptr;

// RE2 Build 11636119 exports the v021 accessor. The flat calls below are
// resolved from the same installed module, using Valve's published signatures.
using GetSteamUser = ISteamUser* (*)();

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
    };
#undef STEAM
}

struct Invite {
    uint64 lobby{};
    uint64 inviter{};
};

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
Invite offered_invite;

enum class Request { create, join };
enum class Role { none, host, guest };

struct LobbyState {
    SteamAPICall_t pending{};
    uint64_steamid joined{};
    Invite joining;
    bool checking_metadata{};
    Request request = Request::create;
    Role role = Role::none;
    uint64_steamid host{};
    Clock::time_point deadline{};
    bool discard_result{};
    bool leave_requested{};
};

LobbyState lobby;

void leave_lobby(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid id) {
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
        ref->log_warn("RE2_COOP_STEAM_LOBBY rejecting incompatible lobby or member list");
        leave_lobby(api, matchmaking, id);
        return;
    }
    lobby.checking_metadata = false;
    lobby.role = Role::guest;
    ref->log_info("RE2_COOP_STEAM_LOBBY joined as guest; verified owner and two members");
}

void poll_lobby(const Steam& api, ISteamMatchmaking* matchmaking, ISteamUtils* utils,
                ISteamUser* user) {
    if (!lobby.pending) {
        return;
    }
    if (!lobby.discard_result && Clock::now() >= lobby.deadline) {
        lobby.discard_result = true;
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
        ref->log_warn("RE2_COOP_STEAM_LOBBY Steam lobby request failed");
        return;
    }

    if (lobby.request == Request::join) {
        LobbyEnter_t result{};
        if (!read_result(api, utils, call, result) ||
            result.m_EChatRoomEnterResponse != k_EChatRoomEnterResponseSuccess) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam join failed response=%u",
                          result.m_EChatRoomEnterResponse);
            return;
        }
        const auto id = result.m_ulSteamIDLobby;
        if (!coop::valid_lobby_id(id)) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam returned an invalid lobby ID");
            return;
        }
        lobby.host = api.owner(matchmaking, id);
        if (id != lobby.joining.lobby || lobby.discard_result || !lobby.host || lobby.host == local ||
            (lobby.joining.inviter && lobby.host != lobby.joining.inviter)) {
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
    lobby.role = Role::host;
    lobby.host = local;
    ref->log_info("RE2_COOP_STEAM_LOBBY created app=%u local_owner=1 members=1 limit=2", re2_app);
}

enum class Command { none, create, invite, join, ping };
coop::SteamPeerProbe peer_probe;
Clock::time_point next_peer_tick{};

uint64_steamid current_peer(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid local) {
    const auto id = lobby.joined;
    if (!id || !local || lobby.role == Role::none || api.owner(matchmaking, id) != lobby.host ||
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
Command requested = Command::none;

std::string_view execute(std::string_view command) {
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
        return offered_invite.lobby ? "invite-pending" : "idle";
    }
    if (command == "leave") {
        requested = Command::none;
        if (lobby.pending) {
            lobby.discard_result = true;
        }
        offered_invite = {};
        lobby.leave_requested = lobby.joined != 0;
        return "accepted leave";
    }
    if (command == "join-invite") {
        if (lobby.pending || lobby.joined || !offered_invite.lobby) {
            return "error join requires a pending invite and an idle lobby";
        }
        requested = Command::join;
        return "accepted join-invite";
    }
    if (command == "create" || command == "invite-dialog") {
        if (lobby.leave_requested || (lobby.discard_result && lobby.pending)) {
            return "error leave in progress";
        }
        requested = command == "create" ? Command::create : Command::invite;
        return command == "create" ? "accepted create" : "accepted invite-dialog";
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
        offered_invite = incoming;
        ref->log_info("RE2_COOP_STEAM_LOBBY invite ready; use join-invite");
    }
    // Refresh eligibility before the pipe reports status or accepts a new ping.
    const auto command = requested;
    requested = Command::none;
    const auto now = Clock::now();
    const bool register_now = !callback_registered && now >= next_callback_attempt;
    const bool peer_tick = now >= next_peer_tick;
    if (peer_tick) {
        next_peer_tick = now + std::chrono::milliseconds(100);
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
        peer_probe.suspend();
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY steam_api64.dll is not loaded");
        }
        return;
    }

    static HMODULE last_module = nullptr;
    static std::optional<Steam> steam;
    if (module != last_module || !steam) {
        steam.emplace(load_steam(module));
        last_module = module;
    }
    const auto& api = *steam;
    if (!api.available() || !api.user_handle()) {
        peer_probe.suspend();
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY expected Steam exports or user unavailable");
        }
        return;
    }
    auto* const matchmaking = api.matchmaking();
    auto* const utils = api.utils();
    auto* const user = api.user();
    if (!matchmaking || !utils || !user || api.app_id(utils) != re2_app) {
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

    if ((peer_tick || command == Command::ping) &&
        peer_probe.configure(module, api.register_callback, ref->log_info)) {
        const auto local = api.steam_id(user);
        const auto peer = api.logged_on(user) ? current_peer(api, matchmaking, local) : 0;
        peer_probe.update(peer ? lobby.joined : 0, peer);
    }

    switch (command) {
    case Command::ping:
        peer_probe.ping();
        break;
    case Command::create:
        if (lobby.pending || lobby.joined) {
            ref->log_info("RE2_COOP_STEAM_LOBBY request already pending or active");
        } else if (api.logged_on(user)) {
            offered_invite = {};
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
    case Command::join:
        if (!api.logged_on(user)) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY Steam user is offline");
            break;
        }
        lobby.joining = offered_invite;
        lobby.request = Request::join;
        lobby.pending = api.join(matchmaking, offered_invite.lobby);
        lobby.discard_result = false;
        lobby.deadline = now + std::chrono::seconds(15);
        if (lobby.pending) {
            offered_invite = {};
            ref->log_info("RE2_COOP_STEAM_LOBBY requested guest join");
        } else {
            ref->log_warn("RE2_COOP_STEAM_LOBBY JoinLobby returned an invalid call handle");
        }
        break;
    case Command::invite:
        if (auto* const friends = api.friends(); friends && lobby.role == Role::host &&
            api.overlay_enabled(utils) && api.logged_on(user)) {
            const auto local = api.steam_id(user);
            if (local && api.owner(matchmaking, lobby.joined) == local) {
                api.open_invite(friends, lobby.joined);
                ref->log_info("RE2_COOP_STEAM_LOBBY requested invite dialog");
                break;
            }
        }
        ref->log_warn("RE2_COOP_STEAM_LOBBY active owned lobby and Steam overlay required");
        break;
    case Command::none:
        break;
    }
}

void on_update() {
    refresh_lobby();
    controls.poll(execute);
}

} // namespace

extern "C" __declspec(dllexport) void reframework_plugin_required_version(REFrameworkPluginVersion* version) {
    *version = {REFRAMEWORK_PLUGIN_VERSION_MAJOR, REFRAMEWORK_PLUGIN_VERSION_MINOR,
                REFRAMEWORK_PLUGIN_VERSION_PATCH, nullptr};
}

extern "C" __declspec(dllexport) bool reframework_plugin_initialize(const REFrameworkPluginInitializeParam* param) {
    ref = param->functions;
    if (!controls.open()) {
        ref->log_error("RE2_COOP_STEAM_LOBBY local command pipe could not open");
        return false;
    }
    if (!ref->on_pre_application_entry("UpdateBehavior", on_update)) {
        return false;
    }
    int argc{};
    if (auto** argv = CommandLineToArgvW(GetCommandLineW(), &argc)) {
        offered_invite.lobby = coop::launch_lobby(argc, argv);
        LocalFree(argv);
    }
    if (offered_invite.lobby) {
        ref->log_info("RE2_COOP_STEAM_LOBBY startup invite ready; use join-invite");
    }
    ref->log_info("RE2_COOP_STEAM_LOBBY terminal control ready");
    return true;
}
