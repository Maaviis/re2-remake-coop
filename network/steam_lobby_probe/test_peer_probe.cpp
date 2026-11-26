#ifdef NDEBUG
#undef NDEBUG
#endif

#include "command_pipe.h"
#include "peer_probe_protocol.h"
#include "pose_packet.h"
#include "steam_peer_probe.h"

#include <cassert>
#include <sstream>

static void test_snapshot_peer_identity() {
    constexpr uint64 peer = 0x0110000100000123ULL;
    constexpr auto connected = k_ESteamNetworkingConnectionState_Connected;
    SteamNetConnectionInfo_t info{};
    info.m_identityRemote.SetSteamID64(peer);
    const auto receipt = [&](char role, std::string_view snapshot, uint64 candidate, ESteamNetworkingConnectionState state) {
        return coop::connected_snapshot_peer(role, snapshot, "pose0001", candidate, state, info);
    };
    const auto host = receipt('H', "epoch001", peer, connected);
    assert(host.epoch == "epoch001" && host.guest_account_id == peer);
    std::ostringstream host_json;
    host.write_fields(host_json);
    assert(host_json.str() == "\"snapshot_epoch\":\"65706f6368303031\",\"guest_account_id\":\"" +
        std::to_string(peer) + "\",\"equipment_pose_epoch\":\"706f736530303031\"");
    const auto guest = receipt('G', "epoch001", peer, connected);
    assert(guest.epoch == "epoch001" && !guest.guest_account_id);
    std::ostringstream guest_json;
    guest.write_fields(guest_json);
    assert(guest_json.str() == "\"snapshot_epoch\":\"65706f6368303031\"");
    assert(!receipt('-', "epoch001", peer, connected).guest_account_id);
    assert(!receipt('H', "", peer, connected).guest_account_id);
    assert(!receipt('H', "epoch002", peer + 1, connected).guest_account_id);
    assert(!receipt('H', "epoch001", peer, k_ESteamNetworkingConnectionState_ClosedByPeer).guest_account_id);
    info.m_nFlags = k_nSteamNetworkConnectionInfoFlags_Unauthenticated;
    assert(!receipt('H', "epoch001", peer, connected).guest_account_id);
    info.m_nFlags = 0;
    constexpr uint64 lobby_id = 0x0184000000000123ULL;
    info.m_identityRemote.SetSteamID64(lobby_id);
    assert(!receipt('H', "epoch001", lobby_id, connected).guest_account_id);
}

static void test_pipe_reopens_on_the_next_update() {
    coop::CommandPipe pipe;
    assert(pipe.open(L"test-peer"));
    const auto name = std::wstring(LR"(\\.\pipe\re2-coop-steam-test-peer-)") +
        std::to_wstring(GetCurrentProcessId());
    const auto echo = [](std::string_view command) { return command; };
    pipe.poll(echo);
    for (const char command : {'R', 'B'}) {
        const auto client = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                        OPEN_EXISTING, 0, nullptr);
        assert(client != INVALID_HANDLE_VALUE);
        DWORD mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
        assert(SetNamedPipeHandleState(client, &mode, nullptr, nullptr));
        DWORD count{};
        assert(WriteFile(client, &command, 1, &count, nullptr) && count == 1);
        pipe.poll(echo);
        char reply{};
        assert(ReadFile(client, &reply, 1, &count, nullptr) && count == 1 && reply == command);
        assert(CloseHandle(client));
        pipe.poll(echo);
    }
}

static void test_closed_client_cannot_leave_a_background_command() {
    coop::CommandPipe pipe;
    assert(pipe.open(L"test-closed"));
    const auto name = std::wstring(LR"(\\.\pipe\re2-coop-steam-test-closed-)") +
        std::to_wstring(GetCurrentProcessId());
    static bool ran{};
    const auto execute = [](std::string_view command) { ran = true; return command; };
    pipe.poll(execute);
    auto client = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    assert(client != INVALID_HANDLE_VALUE);
    pipe.poll(execute);  // The server accepts the connection before the client times out.
    assert(!ran);
    DWORD written{};
    assert(WriteFile(client, "create", 6, &written, nullptr) && written == 6);
    CloseHandle(client);
    pipe.poll(execute);
    assert(!ran);

    // Dropping an abandoned command should reopen the listener on that tick.
    // The game can stop issuing ticks before a status client tries to connect.
    client = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    assert(client != INVALID_HANDLE_VALUE);
    DWORD mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
    assert(SetNamedPipeHandleState(client, &mode, nullptr, nullptr));
    assert(WriteFile(client, "status", 6, &written, nullptr) && written == 6);
    pipe.poll(execute);
    char reply[6]{};
    DWORD received{};
    assert(ReadFile(client, reply, sizeof(reply), &received, nullptr) && received == sizeof(reply));
    assert(std::string_view(reply, received) == "status");
    CloseHandle(client);
}

int main() {
    using namespace coop;
    using namespace std::string_view_literals;
    test_pipe_reopens_on_the_next_update();
    test_closed_client_cannot_leave_a_background_command();
    test_snapshot_peer_identity();
    const auto pose = wrap_pose(0x0102030405060708, std::string(pose_payload_limit, 'p'));
    assert(unwrap_pose(0x0102030405060708, pose).size() == pose_payload_limit);
    assert(unwrap_pose(0x0102030405060709, pose).empty());
    assert(unwrap_pose(0x0102030405060708, pose + "extra").empty());
    assert(unwrap_pose(0, pose).empty());
    const auto ping = encode_probe({ProbeKind::ping, 0x1234, 0xfedc});
    const auto decoded = decode_probe(ping.data(), ping.size(), 0x1234);
    assert(decoded && decoded->kind == ProbeKind::ping && decoded->nonce == 0xfedc);
    assert(!decode_probe(ping.data(), ping.size(), 0x1235));
    assert(!decode_probe(ping.data(), ping.size() - 1, 0x1234));
    assert(!decode_probe(nullptr, ping.size(), 0x1234));
    auto invalid = ping;
    invalid[4] = 2;
    assert(!decode_probe(invalid.data(), invalid.size(), 0x1234));
    invalid = ping;
    invalid[5] = 27;
    assert(!decode_probe(invalid.data(), invalid.size(), 0x1234));
    const auto empty_nonce = encode_probe({ProbeKind::pong, 0x1234, 0});
    assert(!decode_probe(empty_nonce.data(), empty_nonce.size(), 0x1234));

    ProbeExchange probe;
    assert(!probe.complete(0xfedc));
    assert(probe.begin(0xfedc));
    assert(!probe.begin(1));
    assert(!probe.complete(1));
    assert(probe.pending());
    assert(probe.complete(0xfedc));
    assert(probe.verified());
    assert(!probe.complete(0xfedc));
    assert(probe.begin(1));
    probe.reset();
    assert(!probe.complete(1));
    assert(!probe.verified() && !probe.pending());

    PeerMailbox poses, snapshots, combat;
    poses.start("pose-001");
    snapshots.start("snap-001");
    combat.start("cmbt-001");
    poses.receive("pose-frame");
    snapshots.receive("snapshot-frame");
    assert(poses.read('H') == "Hpose-001pose-frame");
    assert(snapshots.read('G') == "Gsnap-001snapshot-frame");
    assert(poses.send_payload("Spose-001pose-send") == "pose-send");
    assert(snapshots.send_payload("Ssnap-001snapshot-send") == "snapshot-send");
    assert(poses.send_payload("Ssnap-001snapshot-send").empty());
    assert(snapshots.send_payload("Spose-001pose-send").empty());
    assert(snapshots.send_payload("Scmbt-001hit").empty());
    assert(combat.send_payload("Ssnap-001resume").empty());

    poses.receive("1");
    poses.receive("2");
    poses.receive("3");
    poses.receive("4");
    poses.receive("5");
    assert(poses.read_batch('H') == "BHpose-001\x00\x01" "1\x00\x01" "2\x00\x01" "3\x00\x01" "4"sv);
    assert(poses.read_batch('H') == "Hpose-0015");
    assert(poses.read_batch('H') == "Hpose-001");

    const std::string large_frame(pose_payload_limit, 'p');
    poses.receive(large_frame);
    poses.receive("next");
    assert(poses.read_batch('H') == "Hpose-001" + large_frame);
    assert(poses.read('H') == "Hpose-001next");
    poses.receive("first");
    poses.receive(large_frame);
    assert(poses.read_batch('H') == "BHpose-001\x00\x05" "first"sv);
    assert(poses.read_batch('H') == "Hpose-001" + large_frame);

    poses.receive("still-pending");
    for (std::size_t i = 0; i < peer_mailbox_limit; ++i) {
        snapshots.receive("queued");
    }
    assert(snapshots.active());
    snapshots.receive("overflow");
    assert(!snapshots.active());
    assert(poses.active() && poses.read('H') == "Hpose-001still-pending");
    snapshots.start("snap-002");
    assert(snapshots.read('G') == "Gsnap-002");
    assert(snapshots.send_payload("Ssnap-001old-frame").empty());
    assert(snapshots.send_payload("Ssnap-002new-frame") == "new-frame");
    snapshots.receive("release-heartbeat");
    for (std::size_t i = 0; i <= peer_mailbox_limit; ++i) {
        combat.receive("queued-hit");
    }
    assert(!combat.active() && snapshots.active() && poses.active());
    assert(snapshots.read('H') == "Hsnap-002release-heartbeat");
    combat.start("cmbt-002");
    assert(combat.send_payload("Scmbt-001old-hit").empty());
    assert(combat.send_payload("Scmbt-002new-hit") == "new-hit");
    poses.reset();
    assert(!poses.active() && snapshots.active());
}
