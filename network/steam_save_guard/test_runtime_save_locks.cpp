#include "runtime_save_locks.h"

#include <aclapi.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>

namespace {
namespace fs = std::filesystem;

class ScopedDeny {
public:
    explicit ScopedDeny(const fs::path& path) : path_(path) {}
    ~ScopedDeny() {
        if (changed_) SetNamedSecurityInfoW(path_.data(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                            nullptr, nullptr, previous_, nullptr);
        if (descriptor_) LocalFree(descriptor_);
    }

    bool apply(DWORD rights) {
        alignas(SID) BYTE everyone[SECURITY_MAX_SID_SIZE]{};
        DWORD length = sizeof(everyone);
        if (!CreateWellKnownSid(WinWorldSid, nullptr, everyone, &length)) return false;
        EXPLICIT_ACCESSW entry{};
        entry.grfAccessPermissions = rights;
        entry.grfAccessMode = DENY_ACCESS;
        BuildTrusteeWithSidW(&entry.Trustee, everyone);
        if (GetNamedSecurityInfoW(path_.data(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                  nullptr, nullptr, &previous_, nullptr, &descriptor_) != ERROR_SUCCESS) return false;
        PACL merged{};
        changed_ = SetEntriesInAclW(1, &entry, previous_, &merged) == ERROR_SUCCESS &&
            SetNamedSecurityInfoW(path_.data(), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
                                  nullptr, nullptr, merged, nullptr) == ERROR_SUCCESS;
        if (merged) LocalFree(merged);
        return changed_;
    }

private:
    std::wstring path_;
    PACL previous_{};
    PSECURITY_DESCRIPTOR descriptor_{};
    bool changed_{};
};

struct Files {
    fs::path root, remote, directory, first, second;
    ~Files() {
        std::error_code ignored;
        for (const auto& path : {second, first, directory, remote, root}) fs::remove(path, ignored);
    }
};

HANDLE open(const fs::path& path, DWORD access) {
    return CreateFileW(path.c_str(), access, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                       nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
}

bool blocked(const fs::path& path, DWORD access) {
    const auto handle = open(path, access);
    if (handle == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_SHARING_VIOLATION;
    CloseHandle(handle);
    return false;
}
} // namespace

int main() {
    const auto root = fs::temp_directory_path() / (L"RE2 runtime lock test " + std::to_wstring(GetCurrentProcessId())
                                                    + L"-" + std::to_wstring(GetTickCount64()));
    if (!fs::create_directory(root)) return 1;
    const auto remote = root / L"remote";
    const auto directory = remote / L"win64_save";
    const auto first = directory / L"data000Slot.bin";
    const auto second = directory / L"data004Slot.bin";
    Files files{root, remote, directory, first, second};
    fs::create_directories(directory);
    std::ofstream(first) << "first fixture";
    std::ofstream(second) << "second fixture";
    coop::RuntimeSaveLocks locks;
    if (locks.acquire(directory) || locks.size() != 0) {
        std::cerr << "A writable profile was accepted\n";
        return 1;
    }
    ScopedDeny directory_acl(directory), parent_acl(remote);
    if (!directory_acl.apply(FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | FILE_DELETE_CHILD | DELETE)
            || !parent_acl.apply(FILE_DELETE_CHILD)) return 1;
    const auto writer = open(second, GENERIC_WRITE);
    if (writer == INVALID_HANDLE_VALUE) return 1;
    const bool acquired_with_writer = locks.acquire(directory);
    const auto first_writer = open(first, GENERIC_WRITE);
    if (first_writer != INVALID_HANDLE_VALUE) CloseHandle(first_writer);
    CloseHandle(writer);
    if (acquired_with_writer || locks.size() != 0 || first_writer == INVALID_HANDLE_VALUE) {
        std::cerr << "The active writer or rollback was mishandled\n";
        return 1;
    }
    if (!locks.acquire(directory) || locks.size() != 2 || !locks.intact()
            || !locks.matches(directory) || locks.matches(remote)
            || !blocked(first, GENERIC_WRITE) || !blocked(second, DELETE)) {
        std::cerr << "The native lock did not protect the complete existing inventory\n";
        return 1;
    }
    const auto reader = open(second, GENERIC_READ);
    if (reader == INVALID_HANDLE_VALUE) return 1;
    CloseHandle(reader);
    return 0;
}
