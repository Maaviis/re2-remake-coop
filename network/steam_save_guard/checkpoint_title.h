#pragma once
#include <reframework/API.h>
namespace coop {
struct CheckpointTitle { bool ready; const char* check; };
CheckpointTitle checkpoint_title(const REFrameworkSDKData* api);
}
