#include "read_trace.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <thread>
#include <vector>

namespace {
void check(bool value, const char* reason) { if (!value) { std::fprintf(stderr, "%s\n", reason); std::exit(1); } }
void* owner(std::uintptr_t index) { return reinterpret_cast<void*>(index); }
} // namespace

int main() {
    for (std::size_t index = 0; index != coop::known_read_targets; ++index)
        check(coop::classify_read_target(coop::known_read_target(index)) == index, "known game filename not classified");
    const auto slot = coop::classify_read_target("./win64_save/data005Slot.bin");
    const auto other = coop::classify_read_target("./win64_save/data004Slot.bin");
    check(slot != other && slot < coop::known_read_targets, "different manual files collapsed");
    for (const auto* name : {"../win64_save/data005Slot.bin", "C:/win64_save/data005Slot.bin", "win64_save/data005Slot.bin",
        ".//win64_save/data005Slot.bin", ".\\win64_save\\data005Slot.bin", "./win64_save/data022Slot.bin",
        "./win64_save/data005slot.bin", "./win64_save/data005Slot.bin.secret", "personal-name"})
        check(coop::classify_read_target(name) == coop::unknown_read_target, "non-whitelisted name acquired file identity");
    check(coop::known_read_target(coop::unknown_read_target) == nullptr, "unknown file exported arbitrary name");
    std::puts("ok - exact bounded filename catalogue rejects traversal, absolute paths, suffixes and case aliases");

    constexpr std::uint64_t handle = 0xfedcba9876543210ULL;
    coop::ReadTrace trace;
    trace.request(slot, owner(1), handle, 12, 100);
    trace.complete(owner(2), handle, 50, true);
    trace.complete(owner(1), handle, 50, false);
    auto state = trace.snapshot();
    check(state.pending == 1 && state.targets[slot].completion_failures == 1 && state.unmatched_completions == 1,
        "wrong receiver or false completion consumed request");
    trace.complete(owner(1), handle, 50, true);
    state = trace.snapshot();
    check(state.available && state.pending == 0 && state.retained_keys == 1 && state.bookkeeping_errors == 0,
        "successful request not retired");
    check(state.targets[slot].completion_successes == 1 && state.targets[slot].successful_completion_bytes == 50,
        "partial successful completion miscounted");
    check(state.events[3].request_id == state.events[0].request_id && state.events[3].offset == 12
        && state.events[3].requested_size == 100 && state.events[3].completion_size == 50 && state.events[3].result,
        "completion lost original range/request identity");
    trace.complete(owner(1), handle, 50, true);
    trace.request(other, owner(1), handle, 0, 200);
    trace.complete(owner(1), handle, 200, true);
    state = trace.snapshot();
    check(state.unmatched_completions == 2 && state.collisions == 1 && state.ambiguous_completions == 1
        && state.ambiguous_pending == 1 && state.targets[other].completion_successes == 0,
        "duplicate completion/retired-handle reuse invented a different file's success");
    check(state.events[state.event_count - 1].target == coop::unknown_read_target,
        "ambiguous completion acquired one candidate's filename");
    std::puts("ok - scoped handles, false retry, partial success, duplicate completion and retired-key reuse remain distinct");

    coop::ReadTrace contexts;
    contexts.request(slot, owner(1), handle, 0, 8);
    contexts.request(other, owner(2), handle, 4, 9);
    contexts.complete(owner(2), handle, 9, true);
    contexts.complete(owner(1), handle, 8, true);
    state = contexts.snapshot();
    check(state.pending == 0 && state.collisions == 0 && state.targets[slot].completion_successes == 1
        && state.targets[other].completion_successes == 1, "independent interface receivers share a pending identity");
    coop::ReadTrace invalid;
    invalid.request(slot, owner(1), 0, 0, 4);
    invalid.request(slot, owner(1), 1, 0, 4);
    invalid.complete(owner(1), 1, 5, true);
    invalid.request((std::numeric_limits<std::size_t>::max)(), owner(1), 2, 0, 3);
    invalid.complete(owner(1), 2, 3, true);
    invalid.sync(slot, -9); invalid.sync(slot, 7);
    state = invalid.snapshot();
    check(state.targets[slot].invalid_handles == 1 && state.targets[slot].oversized_completions == 1
        && state.targets[slot].sync_calls == 2 && state.targets[slot].sync_reported_bytes == 7,
        "invalid/oversized/negative observations were normalized into success");
    check(state.targets[coop::unknown_read_target].completion_successes == 1, "unknown target was not explicitly retained");
    std::puts("ok - independent receivers, invalid API handles, oversize arguments and unknown targets stay explicit");

    coop::ReadTrace bounded;
    for (std::uint64_t id = 1; id <= coop::read_ticket_capacity; ++id) {
        bounded.request(slot, owner(1), id, 0, 4); bounded.complete(owner(1), id, 4, true);
    }
    bounded.request(other, owner(1), 1000, 0, 4);
    bounded.complete(owner(1), 1000, 4, true);
    state = bounded.snapshot();
    check(state.retained_keys == coop::read_ticket_capacity && state.pending == 0 && state.overflows == 1
        && state.unmatched_completions == 1 && state.targets[other].completion_successes == 0,
        "full retained-key capacity invented request tracking");
    check(state.event_count == coop::read_event_capacity && state.discarded_events > 0
        && state.events[state.event_count - 1].sequence == state.event_sequence,
        "bounded event history lost sequence/discard accounting");
    state.events[0].request_id = 0;
    state.targets[slot].completion_successes = 0;
    check(bounded.snapshot().targets[slot].completion_successes == coop::read_ticket_capacity,
        "exported snapshot aliases internal state");
    std::puts("ok - finite retained keys and event history fail explicitly, without recycling ambiguous identities");

    coop::ReadTrace parallel;
    std::atomic<int> finished{};
    std::vector<std::thread> threads;
    for (std::uintptr_t t = 1; t <= 4; ++t) threads.emplace_back([&, t] {
        const auto target = t % 2 ? slot : other;
        for (std::uint64_t id = 1; id <= 16; ++id) {
            parallel.request(target, owner(t), id, 0, 8);
            parallel.complete(owner(t), id, 8, false);
            parallel.complete(owner(t), id, 8, true);
        }
        ++finished;
    });
    while (finished.load() != 4) {
        const auto view = parallel.snapshot();
        check(view.retained_keys <= coop::read_ticket_capacity && view.event_count <= coop::read_event_capacity,
            "concurrent snapshot exceeded bounds");
        for (std::size_t i = 1; i < view.event_count; ++i)
            check(view.events[i - 1].sequence < view.events[i].sequence, "concurrent event order corrupted");
        std::this_thread::yield();
    }
    for (auto& thread : threads) thread.join();
    state = parallel.snapshot();
    check(state.pending == 0 && state.retained_keys == 64 && state.collisions == 0 && state.overflows == 0
        && state.unmatched_completions == 0 && state.bookkeeping_errors == 0, "concurrent correlation lost identities");
    check(state.targets[slot].completion_successes == 32 && state.targets[other].completion_successes == 32
        && state.targets[slot].completion_failures == 32 && state.targets[other].completion_failures == 32,
        "parallel retry results changed counts");
    coop::ReadTrace early;
    early.complete(owner(1), handle, 8, true);
    early.request(slot, owner(1), handle, 0, 8);
    state = early.snapshot();
    check(state.unmatched_completions == 1 && state.pending == 1 && state.targets[slot].completion_successes == 0,
        "completion before request bookkeeping invented a retrospective match");
    std::puts("ok - parallel requests/snapshots and completion-before-bookkeeping remain conservative");
}
