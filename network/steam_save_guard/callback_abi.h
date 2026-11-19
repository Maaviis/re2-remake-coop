#pragma once
#include <cstddef>
namespace coop {
// MSVC x64 reverses these overloaded virtual Run declarations in the vftable.
// Verified against the pinned public CCallbackBase by test_callback_abi.cpp.
constexpr std::size_t callback_call_slot=0,callback_single_slot=1,callback_size_slot=2;
} // namespace coop
