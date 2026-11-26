#include <windows.h>

#include "bridge_start.h"

#include <string>

namespace coop {

BridgeStart start_packaged_bridge(const std::filesystem::path& game, std::uint32_t pid) {
    const auto package = game / L"re2-coop";
    const auto python = package / L"runtime" / L"python.exe";
    const auto script = package / L"steam_pose_bridge.py";
    std::error_code error;
    if (!std::filesystem::is_regular_file(python, error) || !std::filesystem::is_regular_file(script, error)) {
        return BridgeStart::not_installed;
    }
    const auto data = game / L"reframework" / L"data";
    std::filesystem::create_directories(data, error);
    if (error) {
        return BridgeStart::failed;
    }
    // All executable paths come from the installed game directory. No shell,
    // environment-provided command or Steam invite content is used here.
    auto command = L"\"" + python.native() + L"\" -B \"" + script.native() + L"\" --role auto --pid "
        + std::to_wstring(pid) + L" --data \"" + data.native() + L"\" --lobby --save-catalog";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION child{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW, nullptr, package.c_str(), &startup, &child)) {
        return BridgeStart::failed;
    }
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return BridgeStart::started;
}

} // namespace coop
