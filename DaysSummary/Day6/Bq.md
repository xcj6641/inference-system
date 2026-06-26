# BQ Story: Preventing Scheduler Stall Caused by Oversized Requests

## Situation

While building my LLM inference scheduler, I had already implemented token-budget-based admission control. Every request reserved an estimated token budget equal to `prompt_tokens + max_new_tokens`, and the scheduler only admitted requests if the total reserved tokens stayed below the configured `max_tokens_in_flight`.

To validate the scheduler, I designed several workload tests, including short prompts, long prompts, and mixed workloads.

During testing, I configured the scheduler with a token budget of 64 tokens and submitted requests containing approximately 200 prompt tokens. Instead of progressing normally, the scheduler appeared to stop making progress. The waiting queue continued growing, but no requests were admitted.

## Task

My goal was to determine whether the scheduler implementation had a bug or whether the scheduling policy itself was incorrect. More importantly, I wanted the system to fail predictably instead of silently stalling.

## Action

I first added detailed scheduler logging, including:

* reserved tokens for every request
* current token usage
* admission decisions
* reasons why requests were blocked

The logs immediately showed that every long request required about 210 reserved tokens, while the scheduler's global token budget was only 64. Since the admission policy was FIFO, the scheduler continuously inspected the first request in the waiting queue, found that it exceeded the token budget, and stopped admission for that scheduling cycle.

I realized this was not simply a capacity problem. The scheduler was treating an impossible request as if it were only temporarily waiting for capacity.

I separated two different cases:

1. A request that is temporarily waiting because the system is full.
2. A request that can never fit within the scheduler's maximum token budget.

Previously, both cases were handled identically by placing the request into the waiting queue.

To fix this, I added an admission validation step before the request entered the queue. If a request's reserved token count exceeded the scheduler's maximum token budget, it was rejected immediately with a clear `request_too_large` error instead of entering the scheduler.

This prevented structurally impossible requests from occupying the head of the FIFO queue.

## Result

After implementing the validation, oversized requests were rejected immediately instead of silently blocking scheduler progress. The scheduler became much easier to debug because every rejection clearly explained why the request could not be served.

More importantly, I learned an important systems design principle: admission control should distinguish between temporary resource exhaustion and requests that are fundamentally impossible to schedule. Treating those two situations differently makes the serving system significantly more robust and predictable.

That debugging exercise also influenced my later scheduler design. Instead of only thinking about throughput, I started considering failure modes, scheduling policies, and operational behavior under abnormal workloads.
