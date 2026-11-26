#include "campaign_folder.h"
#include <winioctl.h>
#include <bcrypt.h>
#include <limits>
#include <stdexcept>
#include <aclapi.h>
#include <sddl.h>
#include <algorithm>
#include <cstring>
#include <string_view>

namespace coop {
namespace {
namespace fs = std::filesystem;

FileHandle pin(const fs::path& path, bool directory, DWORD disposition, DWORD extra = 0,
               DWORD sharing = FILE_SHARE_READ | FILE_SHARE_WRITE) {
    const auto flags = FILE_FLAG_OPEN_REPARSE_POINT | (directory ? FILE_FLAG_BACKUP_SEMANTICS : 0);
    const auto access = directory ? FILE_LIST_DIRECTORY : FILE_READ_DATA;
    const auto raw = CreateFileW(path.c_str(), access | FILE_READ_ATTRIBUTES | extra, sharing,
        nullptr, disposition, flags, nullptr);
    if (raw == INVALID_HANDLE_VALUE) return {};
    FileHandle handle(raw);
    BY_HANDLE_FILE_INFORMATION info{};
    if (!GetFileInformationByHandle(raw, &info) || (info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)
        || ((info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) != directory
        || (!directory && info.nNumberOfLinks != 1)) return {};
    return handle;
}

struct FreeLocal {
    void operator()(void* value) const { LocalFree(value); }
};
using LocalAllocation = std::unique_ptr<void, FreeLocal>;

LocalAllocation private_descriptor(std::vector<BYTE>& owner) {
    HANDLE raw{};
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &raw)) return {};
    FileHandle token_handle(raw);
    DWORD bytes{};
    GetTokenInformation(raw, TokenUser, nullptr, 0, &bytes);
    if (!bytes) return {};
    std::vector<BYTE> user(bytes);
    if (!GetTokenInformation(raw, TokenUser, user.data(), bytes, &bytes)) return {};
    const auto sid = reinterpret_cast<TOKEN_USER*>(user.data())->User.Sid;
    owner.resize(GetLengthSid(sid));
    if (!CopySid(static_cast<DWORD>(owner.size()), owner.data(), sid)) return {};
    LPWSTR name{};
    if (!ConvertSidToStringSidW(sid, &name)) return {};
    LocalAllocation name_buffer(name);
    const std::wstring sddl = std::wstring(L"O:") + name + L"D:P(A;OICI;FA;;;" + name + L")(A;OICI;FA;;;SY)";
    PSECURITY_DESCRIPTOR descriptor{};
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.c_str(), SDDL_REVISION_1, &descriptor, nullptr))
        return {};
    return LocalAllocation(descriptor);
}

bool private_to_player(HANDLE handle, const std::vector<BYTE>& player, bool directory) {
    PACL acl{};
    PSID owner{};
    PSECURITY_DESCRIPTOR raw{};
    if (GetSecurityInfo(handle, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
            &owner, nullptr, &acl, nullptr, &raw) != ERROR_SUCCESS) return false;
    LocalAllocation descriptor(raw);
    auto* const user = const_cast<BYTE*>(player.data());
    SECURITY_DESCRIPTOR_CONTROL control{};
    DWORD revision{};
    if (!owner || !EqualSid(owner, user) || !acl || acl->AceCount != 2 ||
            !GetSecurityDescriptorControl(raw, &control, &revision) ||
            (directory && !(control & SE_DACL_PROTECTED))) return false;
    bool has_user = false, has_system = false;
    for (DWORD index = 0; index < acl->AceCount; ++index) {
        void* entry{};
        if (!GetAce(acl, index, &entry)) return false;
        const auto ace = static_cast<ACCESS_ALLOWED_ACE*>(entry);
        const auto flags = ace->Header.AceFlags & ~INHERITED_ACE;
        if (ace->Header.AceType != ACCESS_ALLOWED_ACE_TYPE || ace->Mask != FILE_ALL_ACCESS ||
            flags != (directory ? OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE : 0)) return false;
        if (EqualSid(&ace->SidStart, user)) has_user = true;
        else if (IsWellKnownSid(&ace->SidStart, WinLocalSystemSid)) has_system = true;
        else return false;
    }
    return has_user && has_system;
}

FileHandle metadata(const fs::path& path, DWORD disposition, DWORD extra = 0,
                    DWORD sharing = FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    SECURITY_ATTRIBUTES* attributes = nullptr) {
    const auto raw = CreateFileW(path.c_str(), FILE_READ_ATTRIBUTES | READ_CONTROL | extra,
        sharing, attributes, disposition,
        FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    return raw == INVALID_HANDLE_VALUE ? FileHandle{} : FileHandle(raw);
}

bool ordinary_file(HANDLE handle, BY_HANDLE_FILE_INFORMATION& info) {
    return GetFileInformationByHandle(handle, &info) && info.nNumberOfLinks == 1 &&
        !(info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)) &&
        (info.nFileIndexHigh || info.nFileIndexLow);
}

bool same_file(HANDLE left, HANDLE right, BY_HANDLE_FILE_INFORMATION& info) {
    BY_HANDLE_FILE_INFORMATION other{};
    return ordinary_file(left, info) && ordinary_file(right, other) &&
        info.dwVolumeSerialNumber == other.dwVolumeSerialNumber &&
        info.nFileIndexHigh == other.nFileIndexHigh && info.nFileIndexLow == other.nFileIndexLow;
}

bool same_identity(const BY_HANDLE_FILE_INFORMATION& left, const BY_HANDLE_FILE_INFORMATION& right) {
    return left.dwVolumeSerialNumber == right.dwVolumeSerialNumber &&
        left.nFileIndexHigh == right.nFileIndexHigh && left.nFileIndexLow == right.nFileIndexLow;
}

bool fingerprint(HANDLE file, DWORD size, std::array<BYTE, 32>& digest, const void* expected = nullptr) {
    struct Hash {
        BCRYPT_ALG_HANDLE algorithm{};
        BCRYPT_HASH_HANDLE hash{};
        ~Hash() {
            if (hash) BCryptDestroyHash(hash);
            if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
        }
    } hash;
    if (BCryptOpenAlgorithmProvider(&hash.algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0 ||
        BCryptCreateHash(hash.algorithm, &hash.hash, nullptr, 0, nullptr, 0, 0) != 0) return false;
    struct Scratch {
        std::array<BYTE, 8192> file{}, submission{};
        ~Scratch() { SecureZeroMemory(this, sizeof(*this)); }
    } scratch;
    const auto source = reinterpret_cast<std::uintptr_t>(expected);
    if (expected && source > (std::numeric_limits<std::uintptr_t>::max)() - size) return false;
    for (DWORD offset = 0; offset < size;) {
        const auto count = (std::min)(size - offset, static_cast<DWORD>(scratch.file.size()));
        DWORD read{};
        if (!ReadFile(file, scratch.file.data(), count, &read, nullptr) || read != count) return false;
        if (expected) {
            SIZE_T copied{};
            if (!ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(source + offset),
                    scratch.submission.data(), count, &copied) || copied != count ||
                    std::memcmp(scratch.file.data(), scratch.submission.data(), count) != 0) return false;
        }
        if (BCryptHashData(hash.hash, scratch.file.data(), count, 0) != 0) return false;
        offset += count;
    }
    return BCryptFinishHash(hash.hash, digest.data(), static_cast<ULONG>(digest.size()), 0) == 0;
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
    auto security = private_descriptor(owner_);
    if (!security) return false;
    SECURITY_ATTRIBUTES attributes_for_creation{sizeof(SECURITY_ATTRIBUTES), security.get(), FALSE};
    if (!CreateDirectoryW(directory_.c_str(), &attributes_for_creation) && GetLastError() != ERROR_ALREADY_EXISTS) return false;
    auto handle = pin(directory_, true, OPEN_EXISTING, READ_CONTROL);
    if (!handle || !exact_path(handle.get(), directory_) || !private_to_player(handle.get(), owner_, true)) return false;
    // Detect a writer opened before the private DACL. Steam itself opens
    // the directory for FILE_ADD_FILE when committing a rename, so this
    // additional no-write-sharing check ends before the first submission.
    auto no_old_directory_writer = pin(directory_, true, OPEN_EXISTING, 0, FILE_SHARE_READ);
    if (!no_old_directory_writer) return false;
    directories_.push_back(std::move(handle));
    // Reopening a campaign must also reject pre-existing links and nested trees.
    for (const auto& entry : fs::directory_iterator(directory_)) {
        auto existing = metadata(entry.path(), OPEN_EXISTING);
        BY_HANDLE_FILE_INFORMATION info{};
        if (!save_leaf(entry.path().filename().u8string()) || !existing || !ordinary_file(existing.get(), info) ||
            !private_to_player(existing.get(), owner_, false)) return false;
    }
    prefix_ = prefix + '/';
    token = requested;
    return true;
}

std::string CampaignFolder::canonical_key(const char* key) const {
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
    return std::string(spelling);
}

FileHandle CampaignFolder::reserve_staging(const std::string& key) const {
    const auto target = directory_ / key.substr(prefix_.size());
    if (!private_to_player(directories_.back().get(), owner_, true)) return {};
    auto previous = metadata(target, OPEN_EXISTING, FILE_READ_DATA, FILE_SHARE_READ);
    BY_HANDLE_FILE_INFORMATION info{};
    if (previous) {
        if (!ordinary_file(previous.get(), info) || !exact_path(previous.get(), target) ||
                !private_to_player(previous.get(), owner_, false)) return {};
    } else if (GetLastError() != ERROR_FILE_NOT_FOUND) return {};
    // Steam writes the companion, closes it, then replaces the final name.
    // Even a FILE_SHARE_DELETE metadata handle on the destination prevents
    // MoveFileEx(REPLACE_EXISTING). Reserve the SOURCE file identity instead.
    const auto temporary = fs::path(target).concat(L".stmp");
    // TokenOwner can be the Administrators group when running elevated.
    // Set the player as owner at creation and inherit the private directory DACL.
    SECURITY_DESCRIPTOR descriptor{};
    if (!InitializeSecurityDescriptor(&descriptor, SECURITY_DESCRIPTOR_REVISION) ||
        !SetSecurityDescriptorOwner(&descriptor, const_cast<BYTE*>(owner_.data()), FALSE)) return {};
    SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), &descriptor, FALSE};
    auto staging = metadata(temporary, CREATE_NEW, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, &security);
    if (!staging || !ordinary_file(staging.get(), info) || !exact_path(staging.get(), temporary) ||
            !private_to_player(staging.get(), owner_, false)) return {};
    return staging;
}

ExistingCheckpoint CampaignFolder::matching_existing(const std::string& key, const void* data, DWORD size) const {
    ExistingCheckpoint result;
    const auto target = directory_ / key.substr(prefix_.size());
    // Release the destination handle before calling Steam so an ordinary
    // replacement remains possible. Keep only identity and a content digest.
    auto previous = metadata(target, OPEN_EXISTING, FILE_READ_DATA, FILE_SHARE_READ);
    if (!data || !previous || !ordinary_file(previous.get(), result.identity) ||
        result.identity.nFileSizeHigh || result.identity.nFileSizeLow != size ||
        !private_to_player(previous.get(), owner_, false) || !exact_path(previous.get(), target) ||
        !fingerprint(previous.get(), size, result.digest, data)) return result;
    result.matches_submission = true;
    return result;
}

bool CampaignFolder::committed(const std::string& key, HANDLE staging, DWORD size,
                               const ExistingCheckpoint& existing) const {
    const auto target = directory_ / key.substr(prefix_.size());
    auto final = metadata(target, OPEN_EXISTING);
    BY_HANDLE_FILE_INFORMATION info{};
    if (final && same_file(final.get(), staging, info) && !info.nFileSizeHigh && info.nFileSizeLow == size &&
        private_to_player(final.get(), owner_, false) && exact_path(final.get(), target)) return true;
    if (!existing.matches_submission) return false;
    final.reset();
    // An identical Steam write can complete without replacing the old file.
    // Accept only the pre-verified destination and an unused owned reservation.
    auto temporary = metadata(fs::path(target).concat(L".stmp"), OPEN_EXISTING);
    if (!temporary || !same_file(temporary.get(), staging, info) || info.nFileSizeHigh || info.nFileSizeLow ||
        !private_to_player(temporary.get(), owner_, false) ||
        !exact_path(temporary.get(), fs::path(target).concat(L".stmp"))) return false;
    auto unchanged = metadata(target, OPEN_EXISTING, FILE_READ_DATA, FILE_SHARE_READ);
    std::array<BYTE, 32> digest{};
    return unchanged && ordinary_file(unchanged.get(), info) && same_identity(info, existing.identity) &&
        !info.nFileSizeHigh && info.nFileSizeLow == size && private_to_player(unchanged.get(), owner_, false) &&
        exact_path(unchanged.get(), target) && fingerprint(unchanged.get(), size, digest) && digest == existing.digest;
}

std::vector<BYTE> CampaignFolder::read_checkpoint(const std::string& archive_namespace,
        const std::string& generation, const std::string& leaf, const std::array<BYTE, 32>& expected) const {
    const auto hex = [](const std::string& value, std::size_t size) {
        return value.size() == size && std::all_of(value.begin(), value.end(), [](char ch) {
            return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
        });
    };
    if (!hex(archive_namespace, 32) || !hex(generation, 64) ||
        (leaf != "data000.bin" && leaf != "data021Slot.bin" && leaf != "data00-1.bin"))
        throw std::runtime_error("checkpoint_selection_invalid");
    const auto source = directory_.parent_path().parent_path() / L"re2-coop-checkpoints" /
        archive_namespace / generation;
    std::vector<FileHandle> parents;
    if (!pin_directories(source, parents)) throw std::runtime_error("checkpoint_archive_path_invalid");
    const auto path = source / leaf;
    auto file = pin(path, false, OPEN_EXISTING, 0, FILE_SHARE_READ);
    BY_HANDLE_FILE_INFORMATION info{};
    std::array<BYTE, 32> digest{};
    if (!file || !ordinary_file(file.get(), info) || !exact_path(file.get(), path) ||
        info.nFileSizeHigh || !info.nFileSizeLow || info.nFileSizeLow > 32u * 1024u * 1024u ||
        !fingerprint(file.get(), info.nFileSizeLow, digest) || digest != expected)
        throw std::runtime_error("checkpoint_archive_bytes_invalid");
    const LARGE_INTEGER beginning{};
    if (!SetFilePointerEx(file.get(), beginning, nullptr, FILE_BEGIN))
        throw std::runtime_error("checkpoint_archive_read_failed");
    std::vector<BYTE> bytes(info.nFileSizeLow);
    DWORD count{};
    if (!ReadFile(file.get(), bytes.data(), static_cast<DWORD>(bytes.size()), &count, nullptr) || count != bytes.size())
        throw std::runtime_error("checkpoint_archive_read_failed");
    return bytes;
}

bool CampaignFolder::matches_checkpoint(const std::string& leaf, DWORD size,
                                       const std::array<BYTE, 32>& expected) const {
    if (leaf != "data000.bin" && leaf != "data021Slot.bin" && leaf != "data00-1.bin") return false;
    const auto path = directory_ / leaf;
    const auto temporary = fs::path(path).concat(L".stmp");
    if (GetFileAttributesW(temporary.c_str()) != INVALID_FILE_ATTRIBUTES || GetLastError() != ERROR_FILE_NOT_FOUND)
        return false;
    auto file = metadata(path, OPEN_EXISTING, FILE_READ_DATA, FILE_SHARE_READ);
    BY_HANDLE_FILE_INFORMATION info{};
    std::array<BYTE, 32> digest{};
    return file && ordinary_file(file.get(), info) && exact_path(file.get(), path) &&
        !info.nFileSizeHigh && info.nFileSizeLow == size && private_to_player(file.get(), owner_, false) &&
        fingerprint(file.get(), size, digest) && digest == expected;
}

void CampaignFolder::discard_empty_staging(const std::string& key, HANDLE staging) const {
    const auto temporary = (directory_ / key.substr(prefix_.size())).concat(L".stmp");
    auto current = metadata(temporary, OPEN_EXISTING, DELETE);
    BY_HANDLE_FILE_INFORMATION info{};
    if (current && same_file(current.get(), staging, info) && !info.nFileSizeHigh && !info.nFileSizeLow) {
        FILE_DISPOSITION_INFO remove{TRUE};
        SetFileInformationByHandle(current.get(), FileDispositionInfo, &remove, sizeof(remove));
    }
}
} // namespace coop
