Can you tell me why do we do these changes -- decode the new coming requests in the next tick earliest, and prefill at most max_prefill_per_tick requests? can you tell me why is active_before_finish from decode_targets rather than active_requests?

Yes. These changes are there to make your scheduler behave more like an LLM serving system, instead of a generic queue worker.

There are really three separate questions here.

# 1. Why should newly prefetched requests decode no earlier than the next tick?

Because prefill and decode are different kinds of work.

In real LLM inference:

prefill = process the whole prompt, build KV cache, initialize sequence state
decode = generate one more token for requests that are already “alive” in the batch

A request that just arrived is not in the same situation as one that has already finished prefill. It still has to “enter” the model state first.

If you let a request do this in one tick:

admit
prefill
decode first token

then you are collapsing two phases into one atomic action. That makes the scheduler look simpler than real inference serving, and it hides an important latency component: time to first token.

So forcing newly prefetched requests to wait until the next tick does two useful things:

First, it makes the state machine more realistic:

tick N: admitted / prefilling
tick N+1: first eligible decode

Second, it makes the scheduling tradeoff visible. A request that is already decoding is different from a request that is only halfway into service.

Without that separation, you cannot really study:

prefill backlog
decode backlog
TTFT behavior
how new arrivals affect ongoing generation

So this rule is not arbitrary. It is there to preserve the meaning of the two phases.

# 2. Why prefill at most max_prefill_per_tick requests?

Because prefill is not free, and in practice it competes with decode for capacity.

If you let the scheduler prefill every newly admitted request immediately, then you are assuming:

onboarding new requests has effectively infinite capacity, or
prefill cost is negligible

That is usually not true in inference systems.

The reason to cap prefill is to model this idea:

the system can only absorb a limited amount of “new prompt setup work” per scheduling cycle.

That matters because prefill and decode have very different effects.

More prefill per tick helps new requests become decode-ready faster
But too much prefill can starve or interfere with ongoing decode work

Even in your toy scheduler, adding max_prefill_per_tick introduces a second bottleneck:

admission bottleneck: how many requests can be active
prefill bottleneck: how fast active-but-not-ready requests become decode-ready

That is why Day 5 became more interesting than Day 4. You could now see that some requests were already admitted but still had to wait for prefill capacity before joining decode.

So max_prefill_per_tick is a simple way to represent limited onboarding capacity.

# 3. Why is active_before_finish built from decode_targets instead of all active_requests?

Because active_before_finish is not trying to answer:

what requests are currently in the system?

It is trying to answer:

which requests participated in the decode batch this tick?

Those are very different questions.

At a given tick, active_requests may include:

requests still in PREFILL
requests already in DECODE

But only the DECODE ones are eligible for decode_step() in that tick.

So if you logged active_before_finish from all active_requests, the log would be misleading. It would make it look like every active request was part of the decode batch, even though some were still only prefilling.

Example:

Suppose active set is:

A = DECODE
B = DECODE
C = PREFILL

If you log all active requests as active_before_finish=A,B,C, but only decode A and B, then the reader may wrongly think C was also decode-eligible. That muddies the whole Day 5 story.

Using decode_targets makes the log semantically precise:

these were the requests already decode-ready before this tick’s prefill
these were the ones eligible for shared decode this tick

So active_before_finish from decode_targets is really more like:

decode_active_before_finish
or decode_batch_inputs

The name is a little broad, but the logic is right.

Intuition in one sentence

You made these changes because a real inference scheduler is not just “take active requests and generate tokens.” It has to distinguish:

requests waiting outside the system
requests admitted but not ready yet
requests already participating in decode

That is the whole point.

A simple analogy

Think of a restaurant kitchen.

waiting queue = customers waiting for a table
prefill = taking the order and preparing the ingredients
decode = cooking one next step for dishes already on the stove

A new customer cannot:

sit down,
have ingredients prepped,
and instantly join the same cooking cycle

And the kitchen cannot prep unlimited new tables each minute without affecting ongoing dishes.

That is why:

new requests decode next tick earliest
prefill has its own per-tick cap
decode batch is logged from decode_targets, not from everyone in the restaurant
The cleanest mental model

Your scheduler now has three layers:

waiting queue: not admitted yet
active but prefilling: admitted, not decode-ready
active and decoding: participating in token generation

Day 5 exists to make those three layers visible.