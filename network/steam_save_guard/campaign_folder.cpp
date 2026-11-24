#include "campaign_folder.h"
#include <winioctl.h>
#include <algorithm>
#include <cstring>
#include <string_view>

namespace coop {
namespace {
namespace fs = std::filesystem;

FileHandle pin(const fs::path& path, bool directory, DWORD disposition) {
    const auto flags = FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : 0);
    const auto access = directory ? FILE_LIST_DIRECTORY : FILE_READ_DATA;
    const auto raw = CreateFileW(path.c_str(), access | FILE_READ_ATTRIBUTES, FILE_SHARE_READ |
        FILE_SHARE_WRITE, nullptr, disposition, flags, nullptr);
    if (raw == INVALID_HANDLE_VALUE) return {};
    FileHandle handle(raw);
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(raw, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
        || ((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) != directory
        || (!directory && info.nNumberOfLinks != 1)) return {};
    return handle;
}

bool save_leaf(std::string_view leaf) {
    if (leaf == "data00-1.bin") return true;
    if (leaf.size() < 11 || leaf.substr(0, 4) != "data"
        || !std::all_of(leaf.begin() + 4, leaf.begin() + 7, [](char ch) { return ch >= '0' && ch <= '9'; }))
        return false;
    return leaf.substr(7) == ".bin" || leaf.substr(7) == "Slot.bin";
}

bool same_path(fs::path left, fs::path right) {
    return _wcsicmp(left.make_preferred().c_str(), right.make_preferred().c_str()) == 0;
}

bool exact_path(HANDLE h, const fs::path& path) {
    const auto size = GetFinalPathNameByHandleW(h, nullptr, 0, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (!size) return false;
    std::wstring final(size, L'\0');
    const auto used = GetFinalPathNameByHandleW(h, final.data(), size, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS);
    if (!used || used >= size) return false;
    final.resize(used);
    auto expected = path;
    return _wcsicmp(final.c_str(), (L"\\\\?\\" + expected.make_preferred().native()).c_str()) == 0;
}

bool pin_directories(const fs::path& directory, std::vector<FileHandle>& handles) {
    if (!directory.is_absolute() || directory.root_name().native().size() != 2 ||
            directory != directory.lexically_normal()) return false;
    auto parent = directory.root_path();
    for (const auto& part : directory.relative_path()) {
        parent /= part;
        auto handle = pin(parent, true, OPEN_EXISTING);
        if (!handle || !exact_path(handle.get(), parent)) return false;
        handles.push_back(std::move(handle));
    }
    return true;
}

fs::path junction_target(HANDLE link) {
    // Read the kernel substitute name, independent of the optional display name.
    struct MountPoint {
        DWORD tag;
        WORD length, reserved, offset, size, print_offset, print_size;
        wchar_t names[MAXIMUM_REPARSE_DATA_BUFFER_SIZE / sizeof(wchar_t)];
    } data{};
    DWORD bytes{};
    if (!DeviceIoControl(link, FSCTL_GET_REPARSE_POINT, nullptr, 0, &data, MAXIMUM_REPARSE_DATA_BUFFER_SIZE,
            &bytes, nullptr) || data.tag != IO_REPARSE_TAG_MOUNT_POINT || bytes < offsetof(MountPoint, names) ||
        data.offset % sizeof(wchar_t) || data.size % sizeof(wchar_t) ||
        offsetof(MountPoint, names) + data.offset + data.size > bytes) return {};
    std::wstring target(data.names + data.offset / sizeof(wchar_t), data.size / sizeof(wchar_t));
    if (target.compare(0, 4, L"\\??\\") != 0 || target.find(L'\0') != std::wstring::npos) return {};
    return target.substr(4);
}
}

bool CampaignFolder::open(const fs::path& save, const char* requested, const fs::path& steam_userdata) {
    if (!requested || strnlen_s(requested, 33) != 32 ||
        !std::all_of(requested, requested + 32, [](char ch) {
            return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
        })) return false;
    const auto remote = save.parent_path();
    const auto app = remote.parent_path();
    const auto account = app.parent_path();
    const auto number = account.filename().wstring();
    if (!save.is_absolute() || save.root_name().native().size() != 2 ||
        save != save.lexically_normal() || save.filename() != L"win64_save" || remote.filename() != L"remote" ||
        app.filename() != L"883710" || steam_userdata.filename() != L"userdata" || number.empty() ||
        !std::all_of(number.begin(), number.end(), [](wchar_t ch) { return ch >= L'0' && ch <= L'9'; }))
        return false;

    const auto prefix = std::string("coop-save-") + requested;
    if (!pin_directories(steam_userdata.parent_path(), directories_)) return false;
    auto physical = steam_userdata;
    const auto attributes = GetFileAttributesW(steam_userdata.c_str());
    if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY)) return false;
    if (attributes & FILE_ATTRIBUTE_REPARSE_POINT) {
        // Steam can relocate its registered userdata through a junction. Pin
        // the link object against rename, removal and reparse-data writes.
        const auto raw = CreateFileW(steam_userdata.c_str(), FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
        if (raw == INVALID_HANDLE_VALUE) return false;
        FileHandle link(raw);
        physical = junction_target(raw);
        if (physical.empty()) return false;
        directories_.push_back(std::move(link));
    }
    if (!same_path(account.parent_path(), steam_userdata) && !same_path(account.parent_path(), physical))
        return false;
    const auto pinned_remote = physical / account.filename() / L"883710" / L"remote";
    if (!pin_directories(pinned_remote, directories_)) return false;
    const auto logical_save = steam_userdata / account.filename() / L"883710" / L"remote" / L"win64_save";
    auto original = pin(logical_save, true, OPEN_EXISTING);
    if (!original || !exact_path(original.get(), pinned_remote / L"win64_save")) return false;
    directories_.push_back(std::move(original));
    directory_ = pinned_remote / prefix;
    if (!CreateDirectoryW(directory_.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
    auto handle = pin(directory_, true, OPEN_EXISTING);
    if (!handle || !exact_path(handle.get(), directory_)) return false;
    directories_.push_back(std::move(handle));
    // Reopening a campaign must also reject pre-existing links and nested trees.
    for (const auto& entry : fs::directory_iterator(directory_)) {
        if (!save_leaf(entry.path().filename().u8string()) || !pin(entry.path(), false, OPEN_EXISTING)) return false;
    }
    prefix_ = prefix + '/';
    token = requested;
    return true;
}

FileHandle CampaignFolder::pin_target(const char* key, std::string& canonical_key) const {
    if (!key) return {};
    const auto size = strnlen_s(key, 96);
    if (size == 96) return {};
    std::string candidate(key, size);
    std::replace(candidate.begin(), candidate.end(), '\\', '/');
    std::string_view spelling(candidate);
    if (spelling.substr(0, 2) == "./") spelling.remove_prefix(2);
    if (spelling.substr(0, prefix_.size()) != prefix_) return {};
    const auto leaf = spelling.substr(prefix_.size());
    if (!save_leaf(leaf)) return {};
    auto target = directory_ / std::string(leaf);
    auto handle = pin(target, false, OPEN_ALWAYS);
    if (!handle || !exact_path(handle.get(), target)) return {};
    canonical_key.assign(spelling);
    return handle;
}
} // namespace coop
