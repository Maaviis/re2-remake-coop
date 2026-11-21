#pragma once

#include <windows.h>

#include <mutex>
#include <chrono>
#include <string_view>
#include <steam/steam_api_flat.h>

#include "peer_probe_protocol.h"
#include "pose_packet.h"

namespace coop {

class SteamPeerProbe final : public CCallbackBase {
public:
    bool configure(HMODULE module, decltype(&SteamAPI_RegisterCallback) register_callback,
                   void (*log)(const char*, ...));
    void update(std::uint64_t lobby, std::uint64_t peer);
    void ping();
    void suspend();
    std::string_view status() const;
    std::string_view pose_request(std::string_view data, char role);
    std::string_view snapshot_request(std::string_view data, char role);
    std::string_view snapshot_epoch() const;

    void Run(void* payload) override;
    void Run(void* payload, bool failed, SteamAPICall_t) override;
    int GetCallbackSizeBytes() override;

private:
    void release_peer();
    void drain_mailbox(int channel, PeerMailbox& mailbox);
    std::string_view mailbox_request(std::string_view data, char role, int channel, PeerMailbox& mailbox);
    EResult send(ProbeKind kind, std::uint64_t nonce) const;

    HMODULE module_{};
    ISteamNetworkingMessages* messages_{};
    decltype(&SteamAPI_ISteamNetworkingMessages_SendMessageToUser) send_{};
    decltype(&SteamAPI_ISteamNetworkingMessages_ReceiveMessagesOnChannel) receive_{};
    decltype(&SteamAPI_ISteamNetworkingMessages_AcceptSessionWithUser) accept_{};
    decltype(&SteamAPI_ISteamNetworkingMessages_GetSessionConnectionInfo) connection_{};
    decltype(&SteamAPI_ISteamNetworkingMessages_CloseChannelWithUser) close_channel_{};
    decltype(&SteamAPI_SteamNetworkingMessage_t_Release) release_{};
    void (*log_)(const char*, ...){};
    std::mutex request_mutex_;
    std::uint64_t eligible_peer_{};
    std::uint64_t requested_peer_{};
    std::uint64_t lobby_{};
    std::uint64_t peer_{};
    std::chrono::steady_clock::time_point deadline_{};
    ProbeExchange exchange_;
    PeerMailbox poses_;
    PeerMailbox snapshots_;
    bool registered_{};
    bool available_{};
};

} // namespace coop
