#pragma once

#include <cstdint>
#include <filesystem>

namespace coop {

enum class BridgeStart { not_installed, started, failed };

BridgeStart start_packaged_bridge(const std::filesystem::path& game, std::uint32_t pid);

} // namespace coop
