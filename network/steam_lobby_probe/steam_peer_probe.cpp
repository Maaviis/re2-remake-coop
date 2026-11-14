#include "steam_peer_probe.h"

#include <bcrypt.h>

namespace coop {
namespace {

constexpr int probe_channel = 882;
constexpr int per_update = 16;
using Clock = std::chrono::steady_clock;

template <typename Function>
Function resolve(HMODULE module, const char* name) {
#pragma warning(suppress : 4191)
    return reinterpret_cast<Function>(GetProcAddress(module, name));
}

SteamNetworkingIdentity identity(std::uint64_t steam_id) {
    SteamNetworkingIdentity result{};
    result.SetSteamID64(steam_id);
    return result;
}

} // namespace

bool SteamPeerProbe::configure(HMODULE module, decltype(&SteamAPI_RegisterCallback) register_callback,
                               void (*log)(const char*, ...)) {
    if (module != module_) {
        suspend();
        module_ = module;
        messages_ = nullptr;
        registered_ = false;
        lobby_ = 0;
        peer_ = 0;
    }
    if (messages_) {
        available_ = true;
        return true;
    }
    const auto accessor = resolve<decltype(&SteamAPI_SteamNetworkingMessages_SteamAPI_v002)>(
        module, "SteamAPI_SteamNetworkingMessages_SteamAPI_v002");
#define STEAM(name) resolve<decltype(&name)>(module, #name)
    send_ = STEAM(SteamAPI_ISteamNetworkingMessages_SendMessageToUser);
    receive_ = STEAM(SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel);
    accept_ = STEAM(SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser);
    close_channel_ = STEAM(SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser);
    release_ = STEAM(SteamAPI_SteamNetworkingMessage_t_Release);
#undef STEAM
    if (!accessor || !send_ || !receive_ || !accept_ || !close_channel_ || !release_) {
        return false;
    }
    messages_ = accessor();
    if (!messages_) {
        return false;
    }
    log_ = log;
    if (!registered_) {
        register_callback(this, SteamNetworkingMessagesSessionRequest_t::k_iCallback);
        registered_ = true;
    }
    available_ = true;
    log_("RE2_COOP_STEAM_PEER Steam Networking Messages ready");
    return true;
}

void SteamPeerProbe::Run(void* payload) {
    if (payload) {
        const auto* request = static_cast<SteamNetworkingMessagesSessionRequest_t*>(payload);
        const auto id = request->m_identityRemote.GetSteamID64();
        const std::lock_guard<std::mutex> lock{request_mutex_};
        if (id && id == eligible_peer_) {
            requested_peer_ = id;
        }
    }
}

void SteamPeerProbe::Run(void* payload, bool failed, SteamAPICall_t) {
    if (!failed) {
        Run(payload);
    }
}

int SteamPeerProbe::GetCallbackSizeBytes() {
    return sizeof(SteamNetworkingMessagesSessionRequest_t);
}

void SteamPeerProbe::suspend() {
    available_ = false;
    const std::lock_guard<std::mutex> lock{request_mutex_};
    eligible_peer_ = 0;
    requested_peer_ = 0;
    exchange_.reset();
}

void SteamPeerProbe::release_peer() {
    {
        const std::lock_guard<std::mutex> lock{request_mutex_};
        eligible_peer_ = 0;
        requested_peer_ = 0;
    }
    if (peer_) {
        close_channel_(messages_, identity(peer_), probe_channel);
    }
    exchange_.reset();
}

EResult SteamPeerProbe::send(ProbeKind kind, std::uint64_t nonce) const {
    const auto data = encode_probe({kind, lobby_, nonce});
    return send_(messages_, identity(peer_), data.data(), static_cast<uint32>(data.size()),
                 k_nSteamNetworkingSend_ReliableNoNagle | k_nSteamNetworkingSend_AutoRestartBrokenSession,
                 probe_channel);
}

void SteamPeerProbe::update(std::uint64_t lobby, std::uint64_t peer) {
    if (!available_) {
        return;
    }
    bool eligibility_changed;
    {
        const std::lock_guard<std::mutex> lock{request_mutex_};
        eligibility_changed = eligible_peer_ != peer;
    }
    if (lobby != lobby_ || peer != peer_ || eligibility_changed) {
        release_peer();
        lobby_ = lobby;
        peer_ = peer;
        const std::lock_guard<std::mutex> lock{request_mutex_};
        eligible_peer_ = peer;
    }
    std::uint64_t requested;
    {
        const std::lock_guard<std::mutex> lock{request_mutex_};
        requested = requested_peer_;
        requested_peer_ = 0;
    }
    if (requested && requested == peer_) {
        accept_(messages_, identity(peer_));
    }

    if (exchange_.pending() && Clock::now() >= deadline_) {
        exchange_.reset();
        log_("RE2_COOP_STEAM_PEER ping timed out");
    }

    SteamNetworkingMessage_t* received[per_update]{};
    const int count = receive_(messages_, probe_channel, received, per_update);
    for (int i = 0; i < count; ++i) {
        const auto* message = received[i];
        if (!message) {
            continue;
        }
        const auto frame = peer_ && message->m_identityPeer.GetSteamID64() == peer_
            ? decode_probe(message->m_pData, static_cast<std::size_t>(message->m_cbSize), lobby_)
            : std::nullopt;
        if (frame && frame->kind == ProbeKind::ping) {
            const auto result = send(ProbeKind::pong, frame->nonce);
            if (result != k_EResultOK) {
                log_("RE2_COOP_STEAM_PEER reply failed result=%d", static_cast<int>(result));
            }
        } else if (frame && exchange_.complete(frame->nonce)) {
            log_("RE2_COOP_STEAM_PEER round trip verified for current lobby member");
        }
        release_(received[i]);
    }
}

void SteamPeerProbe::ping() {
    if (!available_ || !peer_ || exchange_.pending()) {
        return;
    }
    std::uint64_t nonce{};
    if (BCryptGenRandom(nullptr, reinterpret_cast<PUCHAR>(&nonce), sizeof(nonce),
                        BCRYPT_USE_SYSTEM_PREFERRED_RNG) != 0 || !exchange_.begin(nonce)) {
        log_("RE2_COOP_STEAM_PEER could not generate probe nonce");
        return;
    }
    const auto result = send(ProbeKind::ping, nonce);
    if (result != k_EResultOK) {
        exchange_.reset();
        log_("RE2_COOP_STEAM_PEER send failed result=%d", static_cast<int>(result));
        return;
    }
    deadline_ = Clock::now() + std::chrono::seconds(15);
    log_("RE2_COOP_STEAM_PEER ping sent to current lobby member");
}

std::string_view SteamPeerProbe::status() const {
    if (!available_) {
        return "peer-api-unavailable";
    }
    if (!peer_) {
        return "peer-waiting-for-member";
    }
    if (exchange_.pending()) {
        return "peer-ping-pending";
    }
    return exchange_.verified() ? "peer-round-trip-verified" : "peer-ready";
}

} // namespace coop
