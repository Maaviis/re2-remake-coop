cmake_minimum_required(VERSION 3.20)
project(re2_coop_steam_lobby_probe LANGUAGES CXX)

if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "Build with a Windows x64 toolchain.")
endif()

set(REFRAMEWORK_INCLUDE_DIR "" CACHE PATH "Directory containing reframework/API.h")
set(STEAMWORKS_INCLUDE_DIR "" CACHE PATH "Directory containing steam/steam_api_flat.h")
if(NOT EXISTS "${REFRAMEWORK_INCLUDE_DIR}/reframework/API.h" OR
   NOT EXISTS "${STEAMWORKS_INCLUDE_DIR}/steam/steam_api_flat.h")
    message(FATAL_ERROR "Set REFRAMEWORK_INCLUDE_DIR and STEAMWORKS_INCLUDE_DIR.")
endif()

add_library(re2_coop_steam_lobby_probe SHARED steam_lobby_probe.cpp command_pipe.cpp)
target_compile_features(re2_coop_steam_lobby_probe PRIVATE cxx_std_17)
target_include_directories(re2_coop_steam_lobby_probe SYSTEM PRIVATE
    "${REFRAMEWORK_INCLUDE_DIR}" "${STEAMWORKS_INCLUDE_DIR}")
target_compile_definitions(re2_coop_steam_lobby_probe PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
target_link_libraries(re2_coop_steam_lobby_probe PRIVATE advapi32 shell32)
if(MSVC)
    set_property(TARGET re2_coop_steam_lobby_probe PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
    target_compile_options(re2_coop_steam_lobby_probe PRIVATE /W4 /WX)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(test_invite_input test_invite_input.cpp)
    target_compile_features(test_invite_input PRIVATE cxx_std_17)
    target_include_directories(test_invite_input SYSTEM PRIVATE "${STEAMWORKS_INCLUDE_DIR}")
    add_test(NAME steam_lobby_invite_input COMMAND test_invite_input)
endif()
