Absolutely. I think Day 6 is one of the most important milestones in your entire project. Day 5 made your project look like a scheduler; **Day 6 made it look like an LLM inference scheduler.**

---

# Day 6 — Token-Based Scheduling & Prefill/Decode Separation

## Goal

Move from a **request-count-based scheduler** to a **workload-aware inference scheduler**.

The key idea is:

> **LLM serving capacity is determined by token workload, not by the number of requests.**

---

# 1. Motivation

## Day 5 Model

The scheduler admitted requests based on the number of active requests.

```
capacity ≈ number of active requests
```

Example:

```
max_active_requests = 8
```

Every request was treated equally.

```
5-token request
500-token request

↓

Both consume one slot
```

This is unrealistic because LLM requests have very different computational costs.

---

## Day 6 Model

The scheduler now models capacity based on token workload.

```
capacity ≈ total tokens in flight
```

Instead of:

```
How many requests?
```

it now asks:

```
How much work is currently running?
```

---

# 2. Phase Separation

Instead of treating inference as one stage, requests now move through four states.

```
WAITING
    │
    ▼
PREFILL
    │
    ▼
DECODE
    │
    ▼
FINISHED
```

This better reflects how modern LLM inference works.

---

# 3. Prefill vs Decode

## Prefill

Purpose:

Process the entire prompt once.

Characteristics:

* one-time computation
* proportional to prompt length

Simulator:

```
prefill_cost
    =
prompt_tokens
×
PREFILL_COST_PER_TOKEN
```

Implementation:

```python
prefill_cost = max(
    MIN_PREFILL_COST,
    req.prompt_tokens * PREFILL_COST_PER_TOKEN,
)
await asyncio.sleep(prefill_cost)
```

Result:

```
long prompt

↓

longer prefill

↓

higher TTFT
```

---

## Decode

Purpose:

Generate one token per decode iteration.

Characteristics:

* iterative
* shared across active sequences

Simulator:

```
decode_cost
    =
active_sequence_count
×
DECODE_COST_PER_SEQ
```

Implementation:

```python
decode_cost = max(
    MIN_DECODE_COST,
    len(decode_targets) * DECODE_COST_PER_SEQ,
)
await asyncio.sleep(decode_cost)
```

Result:

```
more active sequences

↓

larger decode batch

↓

slower decode rounds
```

---

# 4. Token Budget Admission

The biggest architectural change of Day 6.

## Before

Admission rule:

```
len(active_requests)
<
max_active_requests
```

---

## After

Each request reserves

```
reserved_tokens
=
prompt_tokens
+
max_new_tokens
```

The scheduler tracks

```
current_tokens_in_flight
```

Admission becomes

```
current_tokens_in_flight
+
reserved_tokens
<=
max_tokens_in_flight
```

Example:

```
GPU Budget = 64
```

Short request:

```
prompt = 1
generate = 10

reserve = 11
```

Five requests:

```
5 × 11 = 55

↓

admitted
```

Sixth request:

```
66 > 64

↓

blocked
```

---

# 5. Reservation Model

The scheduler uses a **reservation model**.

When a request is submitted:

```python
gen_req.prompt_tokens = estimate_prompt_tokens(req.prompt)

gen_req.reserved_tokens = (
    gen_req.prompt_tokens
    + req.max_new_tokens
)
```

The scheduler reserves the **maximum possible workload** before execution.

Advantages:

* simple
* deterministic
* easy admission control

Trade-off:

The reservation is conservative because not every request actually generates `max_new_tokens`.

---

# 6. Scheduler Flow

The scheduler now executes one tick as:

```
1. Admission
```

Move requests from WAITING into PREFILL while token budget allows.

---

```
2. Prefill
```

Run prefill for at most

```
max_prefill_per_tick
```

requests.

---

```
3. Decode
```

Decode one token for every request already in DECODE.

---

```
4. Finish
```

Completed requests

* leave the active set
* release reserved tokens

```
current_tokens_in_flight
-=
reserved_tokens
```

---

# 7. max_prefill_per_tick

A new scheduler parameter.

Purpose:

Limit how many requests may finish prefill during one scheduler tick.

Example:

```
max_prefill_per_tick = 1
```

Behavior:

```
admit 5 requests

↓

only one reaches decode

↓

others wait in PREFILL
```

Effect:

* higher prefill wait
* higher TTFT

---

Larger value:

```
max_prefill_per_tick = 16
```

Behavior:

```
many requests finish prefill

↓

large decode batch
```

Effect:

* lower prefill wait
* larger decode rounds

Important:

```
max_prefill_per_tick
```

**does not affect admission capacity.**

Admission capacity is controlled only by

```
max_tokens_in_flight
```

---

# 8. Experimental Findings

## Small token budget

```
max_tokens_in_flight = 64
```

Short requests:

```
reserve = 11
```

Result:

```
5 admitted

6th blocked
```

---

Long requests:

```
reserve = 201
```

Result:

```
0 admitted
```

The request itself is larger than the entire budget.

---

## Larger token budget

```
max_tokens_in_flight = 512
```

Short requests:

```
30 requests admitted
```

Long requests:

```
201 tokens each

↓

2 admitted

3rd blocked
```

This validates that admission is governed by workload rather than request count.

---

# 9. Metrics Added

The scheduler now records:

* Queue wait
* Prefill wait
* Prefill duration
* Time To First Token (TTFT)
* Decode tail latency
* Service time
* Total latency

These metrics make it possible to analyze different stages of inference separately.

---

# 10. Logs Added

Submission

```
prompt_tokens
reserved_tokens
max_new_tokens
```

Admission

```
tokens_in_flight
```

Blocked admission

```
needed_tokens
current_tokens
max_tokens
```

Completion

```
TTFT
prefill duration
total latency
reserved tokens
```

These logs support performance analysis and debugging.

---

# 11. Current Limitation (Intentional)

The scheduler still admits requests using FIFO.

Example:

```
Queue

Large (210)
Small (11)
Small (11)
```

Budget remaining:

```
100
```

FIFO behavior:

```
Large cannot fit

↓

stop

↓

Small requests also wait
```

This is known as **Head-of-Line Blocking**.

This limitation is intentional and becomes the motivation for Day 7.

---

# Interview Summary

> I redesigned the scheduler from request-count-based admission to token-budget-based admission. I separated inference into prefill and decode phases, modeled prefill cost as proportional to prompt length, and modeled decode cost as proportional to the number of active sequences. Each request reserves its estimated token workload (`prompt_tokens + max_new_tokens`) before admission, allowing the scheduler to limit total in-flight workload instead of simply limiting concurrent requests. This produced more realistic behavior, including prompt-length-dependent TTFT, workload-aware admission, and exposed head-of-line blocking under FIFO scheduling.

---

# Day 6 Knowledge Checklist

By the end of Day 6, you should be able to explain:

* ✅ Why request count is a poor proxy for LLM capacity.
* ✅ The difference between **Prefill** and **Decode**.
* ✅ Why prefill scales with prompt length.
* ✅ Why decode scales with active sequence count.
* ✅ Why token-budget admission is more realistic than request-count admission.
* ✅ Why `reserved_tokens = prompt_tokens + max_new_tokens` is a conservative reservation model.
* ✅ The role of `max_tokens_in_flight` versus `max_prefill_per_tick`.
* ✅ How TTFT, prefill duration, and decode latency relate to different phases.
* ✅ Why FIFO admission can lead to **head-of-line blocking**, setting the stage for exploring alternative admission policies in Day 7.

This is a strong milestone. At this point, your project has moved beyond a generic request scheduler and now captures several of the fundamental ideas behind modern LLM inference systems.
