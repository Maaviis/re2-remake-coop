#include "command_pipe.h"

#include <sddl.h>
#include <array>
#include <string>

namespace coop {
namespace {

// Give only the Windows user running RE2 access to this local endpoint.
PSECURITY_DESCRIPTOR owner_only() {
    HANDLE token{};
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
        return nullptr;
    }
    // TOKEN_USER followed by the SID in the same buffer.
    alignas(TOKEN_USER) std::array<unsigned char, sizeof(TOKEN_USER) + SECURITY_MAX_SID_SIZE> buffer{};
    DWORD used{};
    const bool read = GetTokenInformation(token, TokenUser, buffer.data(),
                                          static_cast<DWORD>(buffer.size()), &used) != FALSE;
    CloseHandle(token);
    LPWSTR sid{};
    if (!read || !ConvertSidToStringSidW(reinterpret_cast<TOKEN_USER*>(buffer.data())->User.Sid, &sid)) {
        return nullptr;
    }
    const auto rule = std::wstring(L"D:P(A;;GA;;;") + sid + L")";
    LocalFree(sid);
    PSECURITY_DESCRIPTOR descriptor{};
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(rule.c_str(), SDDL_REVISION_1,
                                                               &descriptor, nullptr)) {
        return nullptr;
    }
    return descriptor;
}

} // namespace

CommandPipe::~CommandPipe() {
    if (pipe_ != INVALID_HANDLE_VALUE) {
        CloseHandle(pipe_);
    }
}

bool CommandPipe::open() {
    const auto name = std::wstring(LR"(\\.\pipe\re2-coop-steam-lobby-)") +
        std::to_wstring(GetCurrentProcessId());
    const auto descriptor = owner_only();
    if (!descriptor) {
        return false;
    }
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), descriptor, FALSE};
    pipe_ = CreateNamedPipeW(name.c_str(), PIPE_ACCESS_DUPLEX | FILE_FLAG_FIRST_PIPE_INSTANCE,
                            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_NOWAIT | PIPE_REJECT_REMOTE_CLIENTS,
                            1, 128, 128, 0, &security);
    LocalFree(descriptor);
    return pipe_ != INVALID_HANDLE_VALUE;
}

void CommandPipe::disconnect() {
    DisconnectNamedPipe(pipe_);
    connected_ = false;
    replied_ = false;
}

void CommandPipe::poll(std::string_view (*execute)(std::string_view)) {
    const auto now = std::chrono::steady_clock::now();
    if (!connected_) {
        if (ConnectNamedPipe(pipe_, nullptr)) {
            return; // The nonblocking instance is listening.
        }
        const auto error = GetLastError();
        if (error == ERROR_NO_DATA) {
            disconnect();
        }
        if (error != ERROR_PIPE_CONNECTED) {
            return;
        }
        connected_ = true;
        deadline_ = now + std::chrono::seconds(2);
    }

    if (replied_) {
        // Give the client time to receive the reply before disconnecting.
        if (!PeekNamedPipe(pipe_, nullptr, 0, nullptr, nullptr, nullptr) || now >= deadline_) {
            disconnect();
        }
        return;
    }

    char command[32]{};
    DWORD count{};
    std::string_view reply;
    if (ReadFile(pipe_, command, sizeof(command), &count, nullptr)) {
        reply = execute({command, count});
    } else {
        const auto error = GetLastError();
        if (error == ERROR_NO_DATA && now < deadline_) {
            return;
        }
        if (error != ERROR_MORE_DATA) {
            disconnect();
            return;
        }
        reply = "error invalid command";
    }

    DWORD written{};
    if (!WriteFile(pipe_, reply.data(), static_cast<DWORD>(reply.size()), &written, nullptr) ||
        written != reply.size()) {
        disconnect();
        return;
    }
    replied_ = true;
    deadline_ = now + std::chrono::seconds(2);
}

} // namespace coop
