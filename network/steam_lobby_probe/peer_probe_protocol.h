#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>

namespace coop {

enum class ProbeKind : std::uint8_t { ping = 1, pong = 2 };

struct ProbeFrame {
    ProbeKind kind;
    std::uint64_t lobby;
    std::uint64_t nonce;
};

// Network byte order, independent of struct padding or host alignment.
using ProbeBytes = std::array<std::uint8_t, 22>;

inline ProbeBytes encode_probe(ProbeFrame frame) {
    ProbeBytes bytes{'R', 'E', '2', 'P', 1, static_cast<std::uint8_t>(frame.kind)};
    for (std::size_t i = 0; i < 8; ++i) {
        bytes[13 - i] = static_cast<std::uint8_t>(frame.lobby >> (i * 8));
        bytes[21 - i] = static_cast<std::uint8_t>(frame.nonce >> (i * 8));
    }
    return bytes;
}

inline std::optional<ProbeFrame> decode_probe(const void* data, std::size_t size,
                                              std::uint64_t expected_lobby) {
    if (!data || size != ProbeBytes{}.size()) {
        return std::nullopt;
    }
    const auto* bytes = static_cast<const std::uint8_t*>(data);
    const auto kind = static_cast<ProbeKind>(bytes[5]);
    if (bytes[0] != 'R' || bytes[1] != 'E' || bytes[2] != '2' || bytes[3] != 'P' || bytes[4] != 1 ||
        (kind != ProbeKind::ping && kind != ProbeKind::pong)) {
        return std::nullopt;
    }
    ProbeFrame frame{kind, 0, 0};
    for (std::size_t i = 0; i < 8; ++i) {
        frame.lobby = (frame.lobby << 8) | bytes[6 + i];
        frame.nonce = (frame.nonce << 8) | bytes[14 + i];
    }
    if (!frame.lobby || frame.lobby != expected_lobby || !frame.nonce) {
        return std::nullopt;
    }
    return frame;
}

class ProbeExchange {
public:
    bool begin(std::uint64_t nonce) {
        if (pending_ || !nonce) {
            return false;
        }
        pending_ = nonce;
        verified_ = false;
        return true;
    }

    bool complete(std::uint64_t nonce) {
        if (!pending_ || pending_ != nonce) {
            return false;
        }
        pending_ = 0;
        verified_ = true;
        return true;
    }

    void reset() {
        pending_ = 0;
        verified_ = false;
    }

    bool pending() const { return pending_ != 0; }
    bool verified() const { return verified_; }

private:
    std::uint64_t pending_ = 0;
    bool verified_ = false;
};

} // namespace coop
