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

// Hold the resolved path components and the target until Steam finishes the
// API call, including calls that were submitted before a lobby disconnect.
class CampaignFolder {
public:
    bool open(const std::filesystem::path& save, const char* token, const std::filesystem::path& steam_userdata);
    FileHandle pin_target(const char* key, std::string& canonical_key) const;
    std::string token;
private:
    std::filesystem::path directory_;
    std::string prefix_;
    std::vector<FileHandle> directories_;
};

} // namespace coop
