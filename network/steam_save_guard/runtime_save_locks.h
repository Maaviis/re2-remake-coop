#pragma once

#include <windows.h>
#include <filesystem>
#include <vector>

namespace coop {

// Read-sharing handles held by the game itself. The isolated copy must
// already deny creating and removing entries before we acquire them.
class RuntimeSaveLocks {
public:
    RuntimeSaveLocks() = default;
    RuntimeSaveLocks(const RuntimeSaveLocks&) = delete;
    RuntimeSaveLocks& operator=(const RuntimeSaveLocks&) = delete;
    ~RuntimeSaveLocks();

    bool acquire(const std::filesystem::path& directory);
    bool intact() const;
    bool matches(const std::filesystem::path& directory) const;
    const std::filesystem::path& directory() const { return directory_; }
    std::size_t size() const { return files_.size(); }

private:
    std::filesystem::path directory_;
    HANDLE directory_handle_ = INVALID_HANDLE_VALUE;
    std::vector<HANDLE> files_;
};

} // namespace coop
