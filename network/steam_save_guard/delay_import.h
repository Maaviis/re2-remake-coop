#pragma once
#include <cstddef>

namespace coop {
enum class CallResultImport { register_result, unregister_result };
const char* call_result_import_name(CallResultImport name);
// Read-only, bounded Windows x64 PE lookup in a supplied mapped image.
// Only RVA-based delay imports from steam_api64.dll are accepted.
void** find_call_result_import(void* image,std::size_t mapped_size,CallResultImport name) noexcept;
class ImportPatch {
public:
    ImportPatch()=default;
    ImportPatch(const ImportPatch&)=delete;
    ImportPatch& operator=(const ImportPatch&)=delete;
    ~ImportPatch();
    bool attach(void** slot,void* expected,void* replacement);
    bool intact() const;
    void detach();
    void** slot() const{return slot_;}
    const char* error() const{return error_;}
private:
    void** slot_{};void* original_{};void* replacement_{};
    unsigned long protection_{};
    bool protection_restored_{};
    const char* error_="not_attached";
};
} // namespace coop
