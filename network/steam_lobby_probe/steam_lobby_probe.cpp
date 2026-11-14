#include <windows.h>

#include "command_pipe.h"

#include <chrono>
#include <reframework/API.h>
#include <steam/steam_api_flat.h>

namespace {

constexpr AppId_t re2_app = 883710;
constexpr int lobby_capacity = 2;
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
    const decltype(&SteamAPI_ISteamUtils_IsOverlayEnabled) overlay_enabled;
    const decltype(&SteamAPI_ISteamMatchmaking_CreateLobby) create;
    const decltype(&SteamAPI_ISteamMatchmaking_LeaveLobby) leave;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyOwner) owner;
    const decltype(&SteamAPI_ISteamMatchmaking_GetNumLobbyMembers) members;
    const decltype(&SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit) member_limit;
    const decltype(&SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog) open_invite;

    bool available() const {
        return user_handle && user && matchmaking && utils && friends && logged_on &&
            steam_id && app_id && completed && result && overlay_enabled && create &&
            leave && owner && members && member_limit && open_invite;
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
        STEAM(SteamAPI_ISteamUtils_IsOverlayEnabled),
        STEAM(SteamAPI_ISteamMatchmaking_CreateLobby),
        STEAM(SteamAPI_ISteamMatchmaking_LeaveLobby),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyOwner),
        STEAM(SteamAPI_ISteamMatchmaking_GetNumLobbyMembers),
        STEAM(SteamAPI_ISteamMatchmaking_GetLobbyMemberLimit),
        STEAM(SteamAPI_ISteamFriends_ActivateGameOverlayInviteDialog),
    };
#undef STEAM
}

struct LobbyState {
    SteamAPICall_t pending{};
    uint64_steamid owned{};
    Clock::time_point deadline{};
    bool discard_result{};
    bool leave_requested{};
};

LobbyState lobby;

void leave_lobby(const Steam& api, ISteamMatchmaking* matchmaking, uint64_steamid id) {
    api.leave(matchmaking, id);
    lobby.owned = 0;
    ref->log_info("RE2_COOP_STEAM_LOBBY LeaveLobby called for the probe lobby");
}

void poll_lobby(const Steam& api, ISteamMatchmaking* matchmaking, ISteamUtils* utils,
                ISteamUser* user) {
    if (!lobby.pending) {
        return;
    }

    bool failed = false;
    if (!api.completed(utils, lobby.pending, &failed)) {
        if (!lobby.discard_result && Clock::now() >= lobby.deadline) {
            lobby.discard_result = true;
            ref->log_warn("RE2_COOP_STEAM_LOBBY create timed out; a late success will be left");
        }
        return;
    }

    LobbyCreated_t result{};
    bool result_failed = false;
    const bool read = api.result(utils, lobby.pending, &result, sizeof(result),
                                 LobbyCreated_t::k_iCallback, &result_failed);
    lobby.pending = 0;
    if (!read || failed || result_failed || result.m_eResult != k_EResultOK ||
        result.m_ulSteamIDLobby == 0) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY create failed read=%d result=%d io_failed=%d",
                      read, static_cast<int>(result.m_eResult), failed || result_failed);
        return;
    }

    const auto id = result.m_ulSteamIDLobby;
    const auto local = api.steam_id(user);
    const bool local_owner = local != 0 && api.owner(matchmaking, id) == local;
    const int members = api.members(matchmaking, id);
    const int limit = api.member_limit(matchmaking, id);
    if (lobby.discard_result || !local_owner || members != 1 || limit != lobby_capacity) {
        ref->log_warn("RE2_COOP_STEAM_LOBBY discarding lobby local_owner=%d members=%d limit=%d",
                      local_owner, members, limit);
        leave_lobby(api, matchmaking, id);
        return;
    }
    lobby.owned = id;
    ref->log_info("RE2_COOP_STEAM_LOBBY created app=%u local_owner=1 members=1 limit=2", re2_app);
}

enum class Command { none, create, invite };
coop::CommandPipe controls;
Command requested = Command::none;

std::string_view execute(std::string_view command) {
    if (command == "status") {
        if (lobby.pending) {
            return lobby.discard_result ? "canceling" : "creating";
        }
        if (lobby.leave_requested) {
            return "leaving";
        }
        return lobby.owned ? "owned" : "idle";
    }
    if (command == "leave") {
        requested = Command::none;
        if (lobby.pending) {
            lobby.discard_result = true;
        }
        lobby.leave_requested = lobby.owned != 0;
        return "accepted leave";
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

void on_update() {
    controls.poll(execute);
    const auto command = requested;
    requested = Command::none;
    if (command == Command::none && !lobby.pending && !lobby.leave_requested) {
        return;
    }

    const auto module = GetModuleHandleW(L"steam_api64.dll");
    if (!module) {
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY steam_api64.dll is not loaded");
        }
        return;
    }

    const auto api = load_steam(module);
    if (!api.available() || !api.user_handle()) {
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY expected Steam exports or user unavailable");
        }
        return;
    }
    auto* const matchmaking = api.matchmaking();
    auto* const utils = api.utils();
    auto* const user = api.user();
    if (!matchmaking || !utils || !user || api.app_id(utils) != re2_app) {
        if (command != Command::none) {
            ref->log_warn("RE2_COOP_STEAM_LOBBY RE2 Steam context unavailable");
        }
        return;
    }

    if (lobby.leave_requested) {
        lobby.leave_requested = false;
        leave_lobby(api, matchmaking, lobby.owned);
    }
    poll_lobby(api, matchmaking, utils, user);

    switch (command) {
    case Command::create:
        if (lobby.pending || lobby.owned) {
            ref->log_info("RE2_COOP_STEAM_LOBBY request already pending or active");
        } else if (api.logged_on(user)) {
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
    case Command::invite:
        if (auto* const friends = api.friends(); friends && lobby.owned &&
            api.overlay_enabled(utils) && api.logged_on(user)) {
            const auto local = api.steam_id(user);
            if (local && api.owner(matchmaking, lobby.owned) == local) {
                api.open_invite(friends, lobby.owned);
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
    ref->log_info("RE2_COOP_STEAM_LOBBY terminal control ready");
    return true;
}
