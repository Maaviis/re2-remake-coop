#ifdef NDEBUG
#undef NDEBUG
#endif

#include "peer_probe_protocol.h"

#include <cassert>

int main() {
    using namespace coop;
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
}
