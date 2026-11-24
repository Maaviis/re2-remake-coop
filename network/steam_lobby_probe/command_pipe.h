#pragma once

#include <windows.h>

#include <chrono>
#include <string_view>

namespace coop {

class CommandPipe {
public:
    ~CommandPipe();
    bool open(const wchar_t* suffix = L"lobby", DWORD capacity = 128);

    // Callers serialize polling. A filter leaves a pending command for the game frame.
    void poll(std::string_view (*execute)(std::string_view),
              bool (*allow)(std::string_view) = nullptr);

private:
    void disconnect();

    DWORD capacity_{};
    HANDLE pipe_ = INVALID_HANDLE_VALUE;
    bool connected_ = false;
    bool replied_ = false;
    std::chrono::steady_clock::time_point deadline_{};
};

} // namespace coop
