#pragma once

#include <windows.h>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>

namespace coop {

struct CloseFile {
    void operator()(void* handle) const { CloseHandle(handle); }
};
using FileHandle = std::unique_ptr<void, CloseFile>;

class CampaignFolder {
public:
    bool open(const std::filesystem::path& save, const char* token, const std::filesystem::path& steam_userdata);
    std::string canonical_key(const char* key) const;
    FileHandle reserve_staging(const std::string& key) const;
    bool committed(const std::string& key, HANDLE staging, DWORD size) const;
    void discard_empty_staging(const std::string& key, HANDLE staging) const;
    std::string token;
private:
    std::filesystem::path directory_;
    std::string prefix_;
    std::vector<FileHandle> directories_;
    std::vector<BYTE> owner_;
};

} // namespace coop
