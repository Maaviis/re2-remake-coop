#pragma once

#include <windows.h>

#include <mutex>
#include <chrono>
#include <ostream>
#include <string_view>
#include <steam/steam_api_flat.h>

#include "peer_probe_protocol.h"
#include "pose_packet.h"

namespace coop {

struct SnapshotPeer {
    std::string_view epoch;
    std::uint64_t guest_account_id{};
    std::string_view equipment_pose_epoch;

    void write_fields(std::ostream& out) const {
        const auto write_epoch = [&](std::string_view bytes) {
            constexpr std::string_view hex = "0123456789abcdef";
            out.put('"');
            for (const unsigned char byte : bytes) {
                out.put(hex[byte >> 4]);
                out.put(hex[byte & 0xf]);
            }
            out.put('"');
        };
        out << "\"snapshot_epoch\":";
        write_epoch(epoch);
        if (guest_account_id) {
            out << ",\"guest_account_id\":\"" << std::to_string(guest_account_id) << '"';
            if (!equipment_pose_epoch.empty()) {
                out << ",\"equipment_pose_epoch\":";
                write_epoch(equipment_pose_epoch);
            }
        }
    }
};

inline SnapshotPeer connected_snapshot_peer(char role, std::string_view epoch, std::string_view pose_epoch, std::uint64_t peer,
                                            ESteamNetworkingConnectionState state, const SteamNetConnectionInfo_t& info) {
    if ((role != 'H' && role != 'G') || epoch.empty() || state != k_ESteamNetworkingConnectionState_Connected) {
        return {};
    }
    const CSteamID remote{info.m_identityRemote.GetSteamID64()};
    const bool guest = role == 'H' && remote.ConvertToUint64() == peer && remote.IsValid() &&
        remote.GetEAccountType() == k_EAccountTypeIndividual &&
        !(info.m_nFlags & k_nSteamNetworkConnectionInfoFlags_Unauthenticated);
    return {epoch, guest ? peer : 0, guest ? pose_epoch : std::string_view{}};
}

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
    std::string_view combat_request(std::string_view data, char role);
    SnapshotPeer snapshot_peer(char role, std::uint64_t lobby) const;

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
    PeerMailbox combat_;
    bool registered_{};
    bool available_{};
};

} // namespace coop
