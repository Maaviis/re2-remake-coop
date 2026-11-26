#include <windows.h>
#include <reframework/API.h>

#include <chrono>
#include <cstdio>
#include <string>
#include <string_view>

namespace {
REFOnPreApplicationEntryCb frame{};
REFOnMessageCb message{};

void log_message(const char*, ...) {}

LRESULT CALLBACK window_proc(HWND window, UINT id, WPARAM wparam, LPARAM lparam) {
    if (message && !message(window, id, wparam, lparam)) return 0;
    return DefWindowProcW(window, id, wparam, lparam);
}

bool pipe_reply(const wchar_t* endpoint, std::string_view command, std::string_view expected,
                bool resume_frames = false, const MSG* queued_tick = nullptr) {
    const auto name = std::wstring(LR"(\\.\pipe\re2-coop-steam-)") + endpoint + L"-" +
        std::to_wstring(GetCurrentProcessId());
    const auto client = CreateFileW(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                    OPEN_EXISTING, 0, nullptr);
    if (client == INVALID_HANDLE_VALUE) {
        std::fprintf(stderr, "open failed %lu\n", GetLastError());
        return false;
    }
    DWORD mode = PIPE_READMODE_MESSAGE | PIPE_NOWAIT;
    DWORD count{};
    bool ok = SetNamedPipeHandleState(client, &mode, nullptr, nullptr) &&
        WriteFile(client, command.data(), static_cast<DWORD>(command.size()), &count, nullptr) &&
        count == command.size();
    if (!ok) std::fprintf(stderr, "pipe setup/write failed %lu\n", GetLastError());
    if (ok && queued_tick) {
        DispatchMessageW(queued_tick);
        DWORD available{};
        ok = PeekNamedPipe(client, nullptr, 0, nullptr, &available, nullptr) && available == 0;
    }
    const auto end = std::chrono::steady_clock::now() + std::chrono::seconds(1);
    bool replied = false;
    while (ok && std::chrono::steady_clock::now() < end) {
        MSG msg{};
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
        if (resume_frames) frame();
        char buffer[64]{};
        if (ReadFile(client, buffer, sizeof(buffer), &count, nullptr)) {
            replied = std::string_view(buffer, count) == expected;
            break;
        }
        const auto error = GetLastError();
        ok = error == ERROR_NO_DATA;
        if (!ok) std::fprintf(stderr, "read failed %lu\n", error);
        MsgWaitForMultipleObjects(0, nullptr, FALSE, 25, QS_ALLINPUT);
    }
    CloseHandle(client);
    return replied;
}

MSG next_timer(HWND window) {
    MSG msg{};
    const auto end = std::chrono::steady_clock::now() + std::chrono::seconds(1);
    while (!PeekMessageW(&msg, window, WM_TIMER, WM_TIMER, PM_REMOVE) &&
           std::chrono::steady_clock::now() < end) {
        MsgWaitForMultipleObjects(0, nullptr, FALSE, 25, QS_ALLINPUT);
    }
    return msg;
}
}

int wmain(int argc, wchar_t** argv) {
    if (argc != 2) return 1;
    const auto dll = LoadLibraryW(argv[1]);
    if (!dll) return 1;
    const auto init = reinterpret_cast<REFPluginInitializeFn>(GetProcAddress(dll, "reframework_plugin_initialize"));
    REFrameworkPluginFunctions api{};
    api.on_pre_application_entry = [](const char* name, REFOnPreApplicationEntryCb cb) {
        if (std::string_view(name) != "UpdateBehavior") return false;
        frame = cb;
        return true;
    };
    api.on_message = [](REFOnMessageCb cb) { message = cb; return true; };
    api.log_info = api.log_warn = api.log_error = log_message;
    REFrameworkPluginInitializeParam param{};
    param.functions = &api;
    if (!init || !init(&param) || !frame) return 1;

    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = GetModuleHandleW(nullptr);
    wc.lpszClassName = L"RE2CoopTransportFixture";
    if (!RegisterClassW(&wc)) return 1;
    const auto window = CreateWindowExW(0, wc.lpszClassName, L"", 0, 0, 0, 0, 0,
                                        HWND_MESSAGE, nullptr, wc.hInstance, nullptr);
    if (!window) return 1;
    frame();  // Stop engine updates while the window is inactive.
    SendMessageW(window, WM_ACTIVATEAPP, FALSE, 0);
    // No Steam runtime is loaded. A responsive transport must report the missing peer.
    const bool lobby = pipe_reply(L"lobby", "status", "idle");
    const bool pose = pipe_reply(L"pose", "B", "N");
    const bool membership = pipe_reply(L"lobby", "membership-revision", "none");
    const auto background_command = [window](std::string_view command, std::string_view expected) {
        auto reopen = next_timer(window);
        DispatchMessageW(&reopen);
        return pipe_reply(L"lobby", command, expected);
    };
    const bool cloud = background_command("cloud-status", "cloud-unavailable");
    const bool save_folder = background_command("user-data-folder", "user-data-unavailable");
    const bool background = background_command("prepare-context", "background");
    constexpr auto focus_required = "error return to the RE2 window and retry this command";
    const bool denied = background_command("create", focus_required);
    const bool prepare_denied = background_command("prepare-new-game 1 0123456789abcdef0123456789abcdef", focus_required);
    const bool frame_free_again = pipe_reply(L"pose", "R", "N");
    if (!pipe_reply(L"snapshot", "R", "N") || !pipe_reply(L"combat", "R", "N")) {
        std::fprintf(stderr, "Campaign transport unavailable while engine frames are paused\n");
        return 1;
    }
    // Dispatch a tick already posted by Windows *after* the application reactivates.
    auto queued = next_timer(window);
    SendMessageW(window, WM_ACTIVATEAPP, TRUE, 0);
    const bool resumed = pipe_reply(L"lobby", "create", "accepted create", true, &queued);
    frame(); // Reopen the pipe after the client closes it.
    const bool foreground = pipe_reply(L"lobby", "prepare-context", "frame", true);
    frame();
    const bool scoped_command = pipe_reply(L"lobby", "prepare-new-game 1 0123456789abcdef0123456789abcdef",
                                           "error Steam lobby membership changed", true);
    frame();
    SendMessageW(window, WM_SIZE, SIZE_MINIMIZED, 0);
    // A new activation cycle can still write to the pose pipe. An absent Steam peer rejects the send.
    const bool send = pipe_reply(L"pose", "Sepoch0001payload", "N");
    DestroyWindow(window);
    const bool passed = lobby && pose && membership && cloud && save_folder && background && foreground && denied && prepare_denied && frame_free_again &&
        queued.message == WM_TIMER && resumed && scoped_command && send;
    if (!passed) std::fprintf(stderr, "lobby=%d pose=%d membership=%d cloud=%d save_folder=%d denied=%d prepare_denied=%d "
                              "background=%d timer=%u resumed=%d send=%d\n", lobby, pose, membership, cloud, save_folder,
                              denied, prepare_denied, frame_free_again, queued.message, resumed, send);
    return passed ? 0 : 1;
}
