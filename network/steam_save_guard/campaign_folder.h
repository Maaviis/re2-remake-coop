#pragma once

#include <windows.h>
#include <array>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace coop {

struct CloseFile {
    void operator()(void* handle) const { CloseHandle(handle); }
};
using FileHandle = std::unique_ptr<void, CloseFile>;

struct ExistingCheckpoint {
    bool matches_submission{};
    BY_HANDLE_FILE_INFORMATION identity{};
    std::array<BYTE, 32> digest{};
};

class CampaignFolder {
public:
    bool open(const std::filesystem::path& save, const char* token, const std::filesystem::path& steam_userdata);
    std::string canonical_key(const char* key) const;
    FileHandle reserve_staging(const std::string& key) const;
    ExistingCheckpoint matching_existing(const std::string& key, const void* data, DWORD size) const;
    bool committed(const std::string& key, HANDLE staging, DWORD size, const ExistingCheckpoint& existing) const;
    void discard_empty_staging(const std::string& key, HANDLE staging) const;
    std::string token;
private:
    std::filesystem::path directory_;
    std::string prefix_;
    std::vector<FileHandle> directories_;
    std::vector<BYTE> owner_;
};

} // namespace coop
