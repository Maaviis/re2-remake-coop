#pragma once

#include <cstdint>
#include <deque>
#include <string>
#include <string_view>

namespace coop {

constexpr std::size_t pose_payload_limit = 4096;
constexpr std::size_t pose_header_size = 13;
constexpr std::size_t peer_epoch_size = 8;
constexpr std::size_t peer_mailbox_limit = 32;

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

class PeerMailbox {
public:
    bool active() const { return !epoch_.empty(); }

    void start(std::string_view epoch) { epoch_.assign(epoch); }

    void reset() {
        incoming_.clear();
        epoch_.clear();
    }

    void receive(std::string_view payload) {
        if (!active()) {
            return;
        }
        if (incoming_.size() == peer_mailbox_limit) {
            reset(); // The local reader must establish a fresh stream.
            return;
        }
        incoming_.emplace_back(payload);
    }

    std::string_view read(char role) {
        reply_.assign(1, role);
        reply_.append(epoch_);
        if (!incoming_.empty()) {
            reply_.append(incoming_.front());
            incoming_.pop_front();
        }
        return reply_;
    }

    std::string_view read_batch(char role) {
        constexpr std::size_t max_frames = 4;
        constexpr auto reply_limit = 1 + peer_epoch_size + pose_payload_limit;
        constexpr auto header_size = 2 + peer_epoch_size;
        constexpr std::size_t length_size = 2;
        // A full-size frame still fits in the original single-frame reply.
        if (incoming_.size() < 2 || header_size + length_size + incoming_.front().size() > reply_limit) {
            return read(role);
        }
        // Batch marker, original role/epoch header, then big-endian lengths and payloads.
        reply_.assign(1, 'B');
        reply_.push_back(role);
        reply_.append(epoch_);
        for (std::size_t i = 0; i < max_frames && !incoming_.empty(); ++i) {
            const auto& frame = incoming_.front();
            if (reply_.size() + length_size + frame.size() > reply_limit) {
                break;
            }
            reply_.push_back(static_cast<char>(frame.size() >> 8));
            reply_.push_back(static_cast<char>(frame.size() & 0xff));
            reply_.append(frame);
            incoming_.pop_front();
        }
        return reply_;
    }

    std::string_view send_payload(std::string_view request) const {
        constexpr auto header_size = 1 + peer_epoch_size;
        if (request.size() <= header_size || request.size() > header_size + pose_payload_limit ||
            request.front() != 'S' || request.substr(1, peer_epoch_size) != epoch_) {
            return {};
        }
        return request.substr(header_size);
    }

private:
    std::string epoch_;
    std::string reply_;
    std::deque<std::string> incoming_;
};

} // namespace coop
