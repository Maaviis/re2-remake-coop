#include <windows.h>

#include "bridge_start.h"

#include <chrono>
#include <fstream>
#include <string>
#include <string_view>
#include <thread>

int wmain(int argc, wchar_t** argv) {
    namespace fs = std::filesystem;
    using coop::BridgeStart;
    if (argc > 1) {
        const auto package = fs::current_path();
        const auto data = package.parent_path() / L"reframework" / L"data";
        if (argc != 11 || std::wstring_view(argv[1]) != L"-B" ||
            fs::path(argv[2]) != package / L"steam_pose_bridge.py" ||
            std::wstring_view(argv[3]) != L"--role" || std::wstring_view(argv[4]) != L"auto" ||
            std::wstring_view(argv[5]) != L"--pid" || std::wstring_view(argv[6]) != L"12345" ||
            std::wstring_view(argv[7]) != L"--data" || fs::path(argv[8]) != data ||
            std::wstring_view(argv[9]) != L"--lobby" || std::wstring_view(argv[10]) != L"--save-catalog") {
            return 2;
        }
        std::ofstream(package / L"started.txt") << "started";
        return 0;
    }

    const auto game = fs::temp_directory_path() / (L"RE2 Co-op test " + std::to_wstring(GetCurrentProcessId()));
    if (!fs::create_directory(game) || coop::start_packaged_bridge(game, 12345) != BridgeStart::not_installed) {
        return 1;
    }
    const auto package = game / L"re2-coop";
    const auto runtime = package / L"runtime";
    const auto python = runtime / L"python.exe";
    const auto script = package / L"steam_pose_bridge.py";
    const auto marker = package / L"started.txt";
    fs::create_directories(runtime);
    fs::copy_file(fs::absolute(argv[0]), python);
    std::ofstream(script) << "fixture";
    bool started = coop::start_packaged_bridge(game, 12345) == BridgeStart::started;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (started && !fs::exists(marker) && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    started = started && fs::exists(marker) && fs::is_directory(game / L"reframework" / L"data");
    std::error_code ec;
    for (const auto& path : {marker, script, python, runtime, package, game / L"reframework" / L"data",
                             game / L"reframework", game}) {
        fs::remove(path, ec);
    }
    return started ? 0 : 1;
}
