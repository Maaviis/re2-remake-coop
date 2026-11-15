#ifdef NDEBUG
#undef NDEBUG
#endif

#include "invite_input.h"

#include <cassert>

int main() {
    using coop::launch_lobby;
    // Public Steam chat lobby with a non-zero account field.
    constexpr auto lobby = 0x0184000000000123ULL;
    wchar_t id[32]{};
    _ui64tow_s(lobby, id, 32, 10);
    const wchar_t* good[]{L"re2.exe", L"-windowed", L"+connect_lobby", id};
    assert(launch_lobby(4, good) == lobby);
    const wchar_t* duplicate[]{L"re2.exe", L"+connect_lobby", id, L"+connect_lobby", id};
    assert(!launch_lobby(5, duplicate));
    const wchar_t* suffix[]{L"re2.exe", L"+connect_lobby", L"109212290963734819x"};
    assert(!launch_lobby(3, suffix));
    const wchar_t* missing[]{L"re2.exe", L"+connect_lobby"};
    assert(!launch_lobby(2, missing));
    const wchar_t* overflow[]{L"re2.exe", L"+connect_lobby", L"18446744073709551616"};
    assert(!launch_lobby(3, overflow));
    const wchar_t* whitespace[]{L"re2.exe", L"+connect_lobby", L" 109212290963734819"};
    assert(!launch_lobby(3, whitespace));
    const wchar_t* unrelated[]{L"re2.exe", L"+connect_lobby", L"76561198000000001"};
    assert(!launch_lobby(3, unrelated));
    const wchar_t* argument_as_value[]{L"re2.exe", L"-foo", L"prefix+connect_lobby", id};
    assert(!launch_lobby(4, argument_as_value));

    coop::InviteOffer offered;
    assert(!offered.revision() && !offered.match(0).lobby);
    offered.publish({lobby, 11});
    const auto first = offered.revision();
    assert(first && offered.match(first).lobby == lobby);
    offered.publish({lobby, 11});
    assert(offered.revision() == first);
    offered.publish({lobby + 1, 22});
    const auto second = offered.revision();
    assert(second != first && !offered.match(first).lobby);
    assert(offered.match(second).lobby == lobby + 1 && offered.match(second).inviter == 22);
    offered.clear();
    assert(!offered.revision() && !offered.match(second).lobby);
    offered.publish({lobby + 1, 22});
    assert(offered.revision() != second);
    assert(coop::parse_lobby_revision("4294967295") == 4294967295U);
    assert(!coop::parse_lobby_revision("4294967296"));
    assert(!coop::parse_lobby_revision("1 "));
    assert(!coop::parse_lobby_revision("-1"));
    assert(!coop::parse_lobby_revision(""));
}
