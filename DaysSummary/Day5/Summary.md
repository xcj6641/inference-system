# Day 5 Conclusion — Separating Prefill and Decode

Objective

The goal of Day 5 was to make the scheduler behave more like real LLM inference serving by separating prefill and decode into distinct phases, instead of allowing a newly admitted request to prefill and immediately join decode in the same tick. The new scheduler design also introduced a configurable prefill capacity limit, max_prefill_per_tick, to model prefill as a separate bottleneck.

What changed

The scheduler was updated so that each tick now follows this order:

Admit requests from the waiting queue into the active set.
Run prefill for only a limited number of active requests still in PREFILL.
Run decode only for requests that were already DECODE before this tick’s prefill work.
Retire finished requests.

This means a request now follows the more realistic lifecycle:

tick N: admitted and prefilling
tick N+1 or later: first decode token

instead of:

admit → prefill → first token all in one tick.

Experiment setup

To validate the new behavior, the same 5-request workload was run with:

max_active_requests = 3
tick_interval_s = 0.1
max_prefill_per_tick = 1, 2, and 3

Observed behavior

With max_prefill_per_tick = 1, decode batch size ramped gradually from 0 → 1 → 2 → 3, because only one request could finish prefill per tick. At tick 65 only one request was prefetched and decode size was 0; at tick 66 decode size became 1; at tick 67 it became 2; and at tick 68 it reached 3.

With max_prefill_per_tick = 2, the batch ramped faster: tick 205 prefetched two requests with decode size 0, tick 206 decoded two requests, and tick 207 reached decode size 3.

With max_prefill_per_tick = 3, all three admitted requests were prefetched in the first tick, and decode started at full width on the next tick. Tick 369 showed prefill_batch_size=3 and decode_batch_size=0, while tick 370 immediately decoded all three requests together.

These results confirm the intended Day 5 behavior: newly prefetched requests do not decode in the same tick, and prefill capacity directly controls how quickly the decode batch ramps up.

Latency findings

Increasing prefill capacity improved latency for the initially admitted requests. For the third request in the initial active set:

max_prefill_per_tick=1: total latency = 1551.2 ms
max_prefill_per_tick=2: total latency = 1395.3 ms
max_prefill_per_tick=3: total latency continued to improve for the initial batch because all three requests became decode-ready immediately in the first tick and decoded together starting in the next tick.

However, later-arriving requests still experienced large queue waits because max_active_requests=3 remained the dominant bottleneck for admission. For example:

req-4 queue wait dropped from 1093.8 ms at prefill=1 to 935.2 ms at prefill=2, but remained substantial.
req-5 queue wait stayed high: 1092.8 ms at prefill=1 and 1137.6 ms at prefill=2.

This shows that increasing prefill throughput helps requests that have already been admitted, but it does not remove queueing delays caused by the active-slot limit.

Key takeaway

Day 5 successfully exposed two distinct scheduling bottlenecks:

prefill capacity, which controls how quickly admitted requests become decode-ready
active request capacity, which controls when waiting requests can even enter service

This is a much more realistic inference-serving model than Day 4, because it separates onboarding new work from sustaining token generation for ongoing work.

Final Day 5 conclusion

Day 5 transformed the scheduler from a basic shared decode loop into a simple two-phase inference scheduler. By separating prefill from decode and limiting prefill throughput per tick, the system now shows realistic batch ramp-up behavior and makes it possible to study how prefill backlog and decode backlog interact. The experiments showed that higher prefill capacity improves startup efficiency for admitted requests, but tail latency for later requests is still dominated by the active request cap.

A strong one-paragraph interview version is:

On Day 5, I refactored the scheduler to separate prefill and decode into distinct phases and introduced a per-tick prefill limit. Newly admitted requests could no longer prefill and decode in the same tick, so decode batch size ramped up gradually depending on prefill capacity. This exposed two independent bottlenecks: prefill throughput for admitted requests and active-slot availability for queued requests. The result was a more realistic approximation of LLM serving behavior and a clearer latency story around batch ramp-up and queueing.


# Log analysis
These logs are good. They show the Day 5 effect clearly: increasing max_prefill_per_tick speeds up the batch ramp-up for the initial active set, but it does not remove the queueing delay caused by max_active_requests=3.

The cleanest way to read the experiment is this:

For the first 3 admitted requests:

with max_prefill_per_tick=1, decode batch ramps 0 → 1 → 2 → 3 across ticks 65–68.
with max_prefill_per_tick=2, it ramps faster: 0 → 2 → 3 across ticks 205–207.
with max_prefill_per_tick=3, all 3 are prefetched in the first tick, then decode starts at full size 3 on the next tick.

That is exactly the behavior you wanted Day 5 to expose.

The completion numbers for the first wave also support that:

req-3 total latency:
prefill=1: 1551.2 ms
prefill=2: 1395.3 ms
prefill=3: 1208.4 ms

So raising prefill capacity helps the early active requests meaningfully.

But for the later requests, the story is different.

Look at req-4 and req-5:

req-4 queue wait:
prefill=1: 1093.8 ms
prefill=2: 935.2 ms
prefill=3: 902.9 ms
req-5 queue wait:
prefill=1: 1092.8 ms
prefill=2: 1137.6 ms
prefill=3: 1106.2 ms

This tells you the main bottleneck for the tail requests is still active-slot availability, not prefill throughput. In other words:

prefill cap controls how quickly admitted requests become decode-ready
active slot cap controls when later requests can even enter service

That is the key Day 5 insight.

A nice way to summarize each run:

max_prefill_per_tick=1

strong staged ramp-up
prefill is visibly the bottleneck for the initial batch
worst startup behavior among the three settings

max_prefill_per_tick=2

much better early ramp-up
close to a “good enough” point for this workload
still limited by active slots for waiting requests

max_prefill_per_tick=3

initial batch reaches full decode width as fast as possible
early-request latency improves again
later requests still wait a long time because only 3 active requests are allowed at once

So the Day 5 conclusion is:

Separating prefill and decode successfully exposed a second scheduler bottleneck. Increasing prefill capacity improved startup efficiency and reduced latency for already admitted requests, but end-to-end latency for later requests remained dominated by admission delay from the active request cap.

That is a strong infra story already, because it sounds like real inference serving:

one bottleneck for onboarding new work
another bottleneck for sustaining ongoing generation

Now I’d move Day 5 forward in one focused direction:

Add TTFT-style metrics.

Specifically record per request:

arrival_time
admitted_time
prefill_start_time
prefill_end_time
first_decode_time
finished_time

Then compute:

queue_wait_ms = admitted - arrival
prefill_wait_ms = prefill_start - admitted
prefill_duration_ms = prefill_end - prefill_start
ttft_ms = first_decode_time - arrival
decode_tail_ms = finished_time - first_decode_time

That will let you say much more precisely what changed when prefill capacity increased.

My recommendation for Day 6 is:

turn Day 5 from “behavior visible in logs” into “behavior measured with per-phase latency metrics.”

That is the natural next step before you do anything more advanced like token-budget scheduling or decode prioritization.