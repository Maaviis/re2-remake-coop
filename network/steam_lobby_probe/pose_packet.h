#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace coop {

constexpr std::size_t pose_payload_limit = 4096;
constexpr std::size_t pose_header_size = 13;

inline std::string wrap_pose(std::uint64_t lobby, std::string_view payload) {
    std::string data{"RE2S\x01", 5};
    for (int shift = 56; shift >= 0; shift -= 8) {
        data.push_back(static_cast<char>((lobby >> shift) & 0xff));
    }
    data.append(payload);
    return data;
}

inline std::string_view unwrap_pose(std::uint64_t lobby, std::string_view data) {
    if (!lobby || data.size() <= pose_header_size ||
        data.size() > pose_header_size + pose_payload_limit || data.substr(0, 5) != "RE2S\x01") {
        return {};
    }
    std::uint64_t remote_lobby{};
    for (const char byte : data.substr(5, 8)) {
        remote_lobby = (remote_lobby << 8) | static_cast<unsigned char>(byte);
    }
    return remote_lobby == lobby ? data.substr(pose_header_size) : std::string_view{};
}

} // namespace coop
