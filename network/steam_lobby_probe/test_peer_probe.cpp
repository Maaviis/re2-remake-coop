#ifdef NDEBUG
#undef NDEBUG
#endif

#include "command_pipe.h"
#include "peer_probe_protocol.h"
#include "pose_packet.h"

#include <cassert>

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

int main() {
    using namespace coop;
    using namespace std::string_view_literals;
    test_pipe_reopens_on_the_next_update();
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

    PeerMailbox poses, snapshots;
    poses.start("pose-001");
    snapshots.start("snap-001");
    poses.receive("pose-frame");
    snapshots.receive("snapshot-frame");
    assert(poses.read('H') == "Hpose-001pose-frame");
    assert(snapshots.read('G') == "Gsnap-001snapshot-frame");
    assert(poses.send_payload("Spose-001pose-send") == "pose-send");
    assert(snapshots.send_payload("Ssnap-001snapshot-send") == "snapshot-send");
    assert(poses.send_payload("Ssnap-001snapshot-send").empty());
    assert(snapshots.send_payload("Spose-001pose-send").empty());

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
    poses.reset();
    assert(!poses.active() && snapshots.active());
}
