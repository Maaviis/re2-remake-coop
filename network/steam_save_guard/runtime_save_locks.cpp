#include "runtime_save_locks.h"

#include <array>
#include <utility>

namespace coop {
namespace {
namespace fs = std::filesystem;
constexpr DWORD directory_flags = FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT;
constexpr DWORD share_all = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE;
constexpr std::size_t max_save_files = 128;

bool ordinary_directory(const fs::path& path) {
    const auto attributes = GetFileAttributesW(path.c_str());
    return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) &&
           !(attributes & FILE_ATTRIBUTE_REPARSE_POINT);
}

bool denied(const fs::path& path, DWORD access) {
    const auto handle = CreateFileW(path.c_str(), access, share_all, nullptr, OPEN_EXISTING,
                                    directory_flags, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return GetLastError() == ERROR_ACCESS_DENIED;
    CloseHandle(handle);
    return false;
}

bool protected_directory(const fs::path& path) {
    const auto parent = path.parent_path();
    if (!ordinary_directory(path) || !ordinary_directory(parent)) return false;
    constexpr std::array<DWORD, 4> mutations{FILE_ADD_FILE, FILE_ADD_SUBDIRECTORY, FILE_DELETE_CHILD, DELETE};
    for (const auto access : mutations) {
        if (!denied(path, access)) return false;
    }
    // Windows can authorize deletion through the parent instead.
    return denied(parent, FILE_DELETE_CHILD);
}
} // namespace

RuntimeSaveLocks::~RuntimeSaveLocks() {
    for (const auto file : files_) CloseHandle(file);
    if (directory_handle_ != INVALID_HANDLE_VALUE) CloseHandle(directory_handle_);
}

bool RuntimeSaveLocks::acquire(const fs::path& directory) {
    if (directory_handle_ != INVALID_HANDLE_VALUE || !directory.is_absolute() ||
        _wcsicmp(directory.filename().c_str(), L"win64_save") != 0 ||
        !protected_directory(directory)) return false;
    RuntimeSaveLocks pending;
    pending.directory_ = directory;
    pending.files_.reserve(max_save_files);
    pending.directory_handle_ = CreateFileW(directory.c_str(), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ, nullptr, OPEN_EXISTING, directory_flags, nullptr);
    BY_HANDLE_FILE_INFORMATION information{};
    if (pending.directory_handle_ == INVALID_HANDLE_VALUE ||
        !GetFileInformationByHandle(pending.directory_handle_, &information) ||
        !(information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ||
        (information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) return false;

    std::error_code error;
    for (fs::directory_iterator entry(directory, error), end; entry != end && !error; entry.increment(error)) {
        if (pending.files_.size() == max_save_files) return false;
        const auto attributes = GetFileAttributesW(entry->path().c_str());
        if (attributes == INVALID_FILE_ATTRIBUTES ||
            (attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) return false;
        const auto file = CreateFileW(entry->path().c_str(), GENERIC_READ, FILE_SHARE_READ,
                                     nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (file == INVALID_HANDLE_VALUE) return false;
        pending.files_.push_back(file);
        if (!GetFileInformationByHandle(file, &information) ||
            (information.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))) return false;
    }
    if (error || !pending.intact()) return false;
    directory_.swap(pending.directory_);
    files_.swap(pending.files_);
    std::swap(directory_handle_, pending.directory_handle_);
    return true;
}

bool RuntimeSaveLocks::intact() const {
    return directory_handle_ != INVALID_HANDLE_VALUE && !files_.empty() && protected_directory(directory_);
}

bool RuntimeSaveLocks::matches(const fs::path& directory) const {
    if (!intact() || !ordinary_directory(directory)) return false;
    const auto handle = CreateFileW(directory.c_str(), FILE_READ_ATTRIBUTES, share_all,
                                    nullptr, OPEN_EXISTING, directory_flags, nullptr);
    if (handle == INVALID_HANDLE_VALUE) return false;
    BY_HANDLE_FILE_INFORMATION held{}, current{};
    const bool same = GetFileInformationByHandle(directory_handle_, &held) &&
        GetFileInformationByHandle(handle, &current) &&
        !(current.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) &&
        held.dwVolumeSerialNumber == current.dwVolumeSerialNumber &&
        held.nFileIndexHigh == current.nFileIndexHigh && held.nFileIndexLow == current.nFileIndexLow;
    CloseHandle(handle);
    return same;
}
} // namespace coop
