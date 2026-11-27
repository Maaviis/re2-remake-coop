#include "checkpoint_title.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <string_view>

namespace coop {
namespace {
// The pinned C API requires the full 128-byte return union plus exception byte.
struct InvokeResult { std::array<unsigned char, 128> bytes{}; bool exception{}; };
static_assert(sizeof(InvokeResult) == 129);
bool query(const REFrameworkSDKData* api, const char* type, const char* name, bool reference,
           std::uint64_t& value) {
    if (!api || !api->functions || !api->tdb || !api->type_definition || !api->method ||
        !api->functions->get_tdb || !api->functions->get_managed_singleton || !api->tdb->find_type ||
        !api->type_definition->find_method || !api->method->invoke || !api->method->get_return_type ||
        !api->method->get_num_params || !api->method->is_static || !api->type_definition->get_full_name ||
        !api->type_definition->is_valuetype) return false;
    const auto tdb = api->functions->get_tdb();
    const auto definition = tdb ? api->tdb->find_type(tdb, type) : nullptr;
    const auto object = api->functions->get_managed_singleton(type);
    const auto method = definition ? api->type_definition->find_method(definition, name) : nullptr;
    if (!method || api->method->is_static(method) || api->method->get_num_params(method)) return false;
    const auto result_type = api->method->get_return_type(method);
    if (!result_type) return false;
    if (reference) {
        if (api->type_definition->is_valuetype(result_type)) return false;
    } else {
        std::array<char, 64> result_name{};
        unsigned int count{};
        if (api->type_definition->get_full_name(result_type, result_name.data(),
                static_cast<unsigned int>(result_name.size()), &count) != REFRAMEWORK_ERROR_NONE ||
            result_name.back() || std::string_view(result_name.data()) != "System.Boolean") return false;
    }
    if (!object) {
        if (reference) { value = 0; return true; }
        return false;
    }
    InvokeResult result;
    if (api->method->invoke(method, object, nullptr, 0, &result, sizeof(result)) != REFRAMEWORK_ERROR_NONE ||
        result.exception) return false;
    std::memcpy(&value, result.bytes.data(), sizeof(value));
    if (!reference) {
        if (result.bytes[0] > 1) return false;
        value = result.bytes[0];
    }
    return true;
}
}
CheckpointTitle checkpoint_title(const REFrameworkSDKData* api) {
    std::uint64_t value{};
    for (const auto& test : std::array<std::array<const char*, 3>, 7>{{
        {{"app.ropeway.gamemastering.MainFlowManager", "get_IsInTitle", "true"}},
        {{"app.ropeway.gamemastering.MainFlowManager", "get_IsInLoadGameData", "false"}},
        {{"app.ropeway.gamemastering.SaveDataManager", "get_IsBusy", "false"}},
        {{"app.ropeway.gamemastering.SaveDataManager", "get_IsErrorBusy", "false"}},
        {{"app.ropeway.PlayerManager", "get_CurrentPlayer", "null"}},
        {{"app.ropeway.gui.GUIMaster", "isBusyLoad", "false"}},
        {{"app.ropeway.gui.GUIMaster", "isBusyMenuStory", "false"}}
    }}) {
        const bool reference = std::string_view(test[2]) == "null";
        if (!query(api, test[0], test[1], reference, value) || value != (std::string_view(test[2]) == "true" ? 1u : 0u))
            return {false, test[1]};
    }
    for (const auto* name : {"isTitleMenuOpened", "isBusyMenuMain"}) {
        if (!query(api, "app.ropeway.gui.GUIMaster", name, false, value)) return {false, name};
        if (value == 1) return {true, "ok"};
    }
    return {false, "title_menu_closed"};
}
} // namespace coop
