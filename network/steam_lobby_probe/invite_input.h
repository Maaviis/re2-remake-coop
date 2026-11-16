#pragma once

#include <charconv>
#include <cstdint>
#include <limits>
#include <string_view>
#include <steam/steam_api.h>

namespace coop {

struct Invite {
    uint64 lobby{};
    uint64 inviter{};
};

class InviteOffer {
public:
    void publish(Invite invite) {
        if (invite_.lobby == invite.lobby && invite_.inviter == invite.inviter) {
            return;
        }
        invite_ = invite;
        if (++revision_ == 0) {
            ++revision_;
        }
    }

    void clear() { invite_ = {}; }

    std::uint32_t revision() const { return invite_.lobby ? revision_ : 0; }

    Invite match(std::uint32_t expected) const {
        return expected && expected == revision() ? invite_ : Invite{};
    }

private:
    Invite invite_;
    std::uint32_t revision_{};
};

inline std::uint32_t parse_lobby_revision(std::string_view text) {
    std::uint32_t revision{};
    if (text.empty()) {
        return 0;
    }
    const auto end = text.data() + text.size();
    const auto result = std::from_chars(text.data(), end, revision);
    return result.ec == std::errc{} && result.ptr == end ? revision : 0;
}

inline bool valid_lobby_id(uint64 id) {
    const CSteamID steam_id{id};
    return steam_id.IsValid() && steam_id.IsLobby() && steam_id.GetAccountID() != 0;
}

inline uint64 launch_lobby(int argc, const wchar_t* const* argv) {
    uint64 lobby{};
    for (int i = 1; i < argc; ++i) {
        if (std::wstring_view{argv[i]} != L"+connect_lobby") {
            continue;
        }
        if (lobby || ++i == argc) {
            return 0;
        }
        for (const wchar_t digit : std::wstring_view{argv[i]}) {
            if (digit < L'0' || digit > L'9') {
                return 0;
            }
            const auto value = static_cast<uint64>(digit - L'0');
            if (lobby > (std::numeric_limits<uint64>::max() - value) / 10) {
                return 0;
            }
            lobby = lobby * 10 + value;
        }
        if (!valid_lobby_id(lobby)) {
            return 0;
        }
    }
    return lobby;
}

} // namespace coop
