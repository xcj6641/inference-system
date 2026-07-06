1. admission + decode > kv max capacity
2. dead lock: admission occupies the remaining avaliable kvs, and decoding cannot process. All sequences are waitting.
3. KV Cache Saturation Problem

Absolutely. One thing I really like about this project is that it has now evolved beyond "I built a toy LLM gateway." By the end of Day 7, you've made **multiple architecture decisions**, and those decisions translate directly into behavioral interview (BQ) stories. Companies like Databricks, Anthropic, OpenAI, Meta, and NVIDIA love hearing about technical tradeoffs.

Here are the strongest stories you've accumulated.

---

# Story 1 — Designing a scalable scheduler instead of a simple queue ⭐⭐⭐⭐⭐

**Question**

* Tell me about a system you designed from scratch.
* Tell me about a technically challenging project.

### Situation

I started building an LLM inference gateway. Initially it was a simple request queue feeding a fake model.

### Task

I realized that this architecture couldn't represent how modern LLM serving systems work, especially continuous batching.

### Action

I redesigned the scheduler around several concepts:

* waiting queue
* active request set
* prefill stage
* decode stage
* continuous admission every scheduling tick

Instead of processing one request at a time, the scheduler continuously merged new requests into existing decode batches.

### Result

The architecture became much closer to production inference systems like vLLM, and it also made later extensions—such as KV cache management and multiple engine backends—possible without redesigning the scheduler.

---

# Story 2 — Separating scheduling policy from execution ⭐⭐⭐⭐⭐

This is probably your strongest architecture story.

### Situation

Initially, the scheduler directly called a fake model implementation.

### Problem

I realized the scheduler was becoming tightly coupled to one backend implementation.

If I later wanted to integrate:

* vLLM
* TensorRT-LLM
* SGLang

I'd have to rewrite the scheduler.

### Action

I introduced a ModelEngine abstraction.

The scheduler now depends only on an engine interface.

Different inference backends simply implement:

```python
prefill()

decode_step()
```

The scheduler has no knowledge of the underlying runtime.

### Result

The architecture became open for extension while remaining closed for modification. Adding a new backend no longer requires changing scheduling logic.

---

# Story 3 — Discovering a hidden scalability bug ⭐⭐⭐⭐⭐

This is a fantastic debugging story.

### Situation

After implementing KV cache accounting, the system appeared to work correctly.

### Action

I designed stress tests using requests with different prompt lengths and decode lengths.

While testing, I realized that even though admission respected KV capacity, the system could still deadlock once decoding consumed all remaining KV pages.

### Investigation

I traced the scheduler tick by tick and realized:

* admission wasn't the problem
* decode growth was consuming KV incrementally
* eventually every active request required another KV page
* no request could continue

### Result

I learned that real systems solve this using decode scheduling and KV-aware admission rather than unlimited decoding.

Although I didn't implement the full production solution immediately, I documented the issue and adjusted the roadmap accordingly.

---

# Story 4 — Preventing subtle accounting bugs ⭐⭐⭐⭐☆

This one demonstrates attention to correctness.

### Situation

While implementing KV accounting, I initially thought decode growth might be double-counted.

### Action

I walked through scheduler execution tick by tick, tracing:

```
Tick N

used = prompt + decode

↓

Tick N+1

decode again
```

I realized the confusion came from whether KV usage represented cumulative cache or temporary allocations.

### Result

Instead of changing the implementation immediately, I verified the intended semantics and added targeted tests to confirm that KV usage only grew when new tokens were generated.

This avoided introducing an incorrect optimization.

---

# Story 5 — Building verification before adding features ⭐⭐⭐⭐☆

Many candidates forget this.

### Situation

After implementing KV cache management, I didn't immediately continue adding features.

### Action

I created multiple focused tests, including:

* admission respects KV limits
* KV released when requests finish
* decode grows KV correctly
* no KV leak
* no double counting

I also added scheduler debug endpoints exposing:

* active requests
* waiting queue
* KV usage
* token budget
* scheduler statistics

### Result

Having observability made debugging much easier and increased confidence before moving on to the next phase.

---

# Story 6 — Making architecture decisions based on future extensibility ⭐⭐⭐⭐⭐

Interviewers love this.

### Situation

I knew I wanted to integrate a real inference engine later.

### Action

Rather than optimizing only for the current fake implementation, I continuously refactored toward production architecture:

* scheduler independent of runtime
* KV manager independent of scheduler
* request store independent of engine
* configurable scheduler parameters
* runtime statistics separated from scheduling logic

### Result

Each new feature became easier to implement because responsibilities were clearly separated.

---

# Story 7 — Learning from production systems ⭐⭐⭐⭐☆

This demonstrates technical curiosity.

### Situation

While implementing KV cache management, I encountered a problem that my current design couldn't solve.

### Action

Instead of forcing a quick fix, I studied how production inference systems like vLLM handle KV memory.

I learned the distinction between:

* KV accounting
* PagedAttention
* decode scheduling
* KV offloading
* forward progress guarantees

### Result

I adjusted my roadmap to implement these mechanisms incrementally rather than overengineering the scheduler too early.

---

# Story 8 — Iterative system design ⭐⭐⭐⭐⭐

This story ties the whole project together.

Rather than trying to build a complete inference system all at once, I approached it incrementally.

Each stage introduced one major capability while preserving a working system:

* request admission
* continuous batching
* token budgeting
* prefill/decode separation
* KV cache accounting
* backend abstraction (next step)

At every milestone, I validated correctness before moving forward.

This iterative approach made it much easier to identify architectural problems early and avoid large-scale rewrites later.

---

# Which stories are strongest?

For top AI infrastructure companies, I'd rank them:

| Rank  | Story                                       | Interview value                    |
| ----- | ------------------------------------------- | ---------------------------------- |
| ⭐⭐⭐⭐⭐ | Designing the continuous batching scheduler | Distributed systems & architecture |
| ⭐⭐⭐⭐⭐ | Introducing the ModelEngine abstraction     | Software design & extensibility    |
| ⭐⭐⭐⭐⭐ | Discovering the KV cache deadlock           | Debugging & systems thinking       |
| ⭐⭐⭐⭐⭐ | Incremental architecture evolution          | Ownership & engineering process    |
| ⭐⭐⭐⭐☆ | Building verification and observability     | Quality & testing                  |
| ⭐⭐⭐⭐☆ | Learning from production inference systems  | Technical curiosity                |
| ⭐⭐⭐⭐☆ | Preventing accounting bugs                  | Attention to detail                |

These stories are especially compelling because they aren't hypothetical—they come from concrete design decisions and debugging work you've done. By the time you finish the planned roadmap (Days 8–10 with engine abstraction, streaming, and a real backend), you'll have enough material to answer most system-design and behavioral questions for AI infrastructure roles using this single project from multiple angles.

# Story 9 - Do you have experiences that AI made mistakes and you found that
Yes—I actually think **this is an even better story** than the previous one because it demonstrates a complete engineering workflow:

1. AI formed a hypothesis.
2. You didn't accept it immediately.
3. You gathered evidence.
4. You found the hypothesis was wrong.
5. You explained the correct behavior using system logs.

That's exactly how senior engineers work.

Here's how I'd tell it in an interview.

---

## Question

**Tell me about a time AI gave you an incorrect answer.**

### Situation

I was building an LLM inference scheduler that simulated KV cache growth during autoregressive decoding. To verify the implementation, I wrote a test called `test_no_kv_double_count_across_ticks`, which checked that KV cache usage increased correctly as tokens were generated.

### Task

The goal was to make sure KV cache accounting reflected the behavior of a real inference engine and that decode memory wasn't accidentally counted twice across scheduler ticks.

### Action

After running the test, the final output showed:

```text
FINAL KV: 0
GENERATED TOKENS: 10
```

The AI initially interpreted this as evidence that there was a bug in the KV accounting.

Instead of assuming the conclusion was correct, I inspected the scheduler logs tick by tick.

The logs showed the expected progression:

* admission allocated KV for the prompt
* each decode round increased KV usage by one token
* KV usage grew from 3 to 12 exactly as expected
* after the tenth generated token, the request finished
* the scheduler released the KV cache
* therefore the final KV usage returned to zero

I realized the test wasn't measuring the peak KV usage—it was observing the system after the request had already completed. The final value of zero was actually the expected behavior.

I explained that the logs demonstrated correct cumulative KV growth followed by proper cleanup, and therefore there was no double-counting or memory leak.

### Result

We kept the implementation unchanged because it was already correct, and the discussion shifted from "fixing" nonexistent bugs to improving the tests so they measured intermediate KV states rather than only the final state.

The experience reinforced an important lesson: AI is excellent for generating hypotheses, but engineering decisions should be based on evidence from logs, tests, and a clear understanding of the system.

---

## Why I like this story

This story shows several qualities that interviewers value:

* **Debugging discipline.** You didn't rely on intuition; you used logs.
* **Independent judgment.** You were willing to disagree with AI when the evidence didn't support its conclusion.
* **Systems thinking.** You understood the lifecycle of KV memory instead of looking only at the final output.
* **Test improvement.** You recognized that the limitation was in the test's observability, not in the implementation.

---

## A concise version for interviews (about 1 minute)

> "While building an LLM inference scheduler, I wrote a test to verify KV cache accounting. The test ended with `FINAL KV: 0`, and AI initially suggested that this indicated a bug. Instead of changing the code, I reviewed the scheduler logs tick by tick. The logs showed KV usage increasing exactly one token per decode step, reaching the expected peak, and then returning to zero only because the request had completed and the scheduler correctly released the KV cache. The implementation was correct—the misunderstanding came from looking only at the final state instead of the entire lifecycle. We kept the implementation, improved the test, and it reinforced my approach of using AI as a collaborator rather than treating its suggestions as authoritative."

I actually think this is one of your strongest behavioral stories because it's **completely genuine**. You weren't trying to prove AI wrong—you simply followed the evidence. That's the kind of engineering judgment companies want to see when they ask how you work with AI.

# Story 10 - same as up
Actually, **yes.** And I think you have a very authentic story from this project.

The important thing is **not** "AI was wrong."

The important thing is:

> **I used AI as a pair programmer, but I always verified the design myself. When something didn't make sense, I challenged it until we found the root cause.**

That is exactly what interviewers want to hear. Many companies are now asking this question because they want to know whether you can **use AI critically**, not whether you blindly trust it.

Here's a STAR story based on what actually happened.

---

## BQ: Tell me about a time AI gave you an incorrect solution.

### Situation

I was building an LLM inference scheduler with KV cache accounting. I was using ChatGPT as a design assistant to discuss scheduling logic and review my implementation.

### Task

One of the goals was to correctly track KV cache growth during decoding while avoiding double counting.

### Action

At one point, AI suggested that my KV accounting might be double counting decode memory across scheduling ticks.

Initially, the explanation sounded reasonable, but when I walked through a concrete example step by step, something didn't add up.

For example, if a request generated one new token every scheduling tick, the KV cache should naturally grow by one token every tick because every generated token stays in the cache for future attention. AI's earlier reasoning treated previously allocated KV as if it were being allocated again.

Instead of accepting the suggestion, I traced the scheduler tick by tick, inspected the state transitions, reviewed the generated logs, and reasoned about what KV cache actually represents in an autoregressive model.

That analysis showed that the implementation was actually correct—the apparent "double counting" was simply cumulative KV growth as more tokens were generated.

### Result

We corrected the design discussion, kept the implementation unchanged, and added targeted tests to verify KV growth behavior. The experience reinforced my habit of treating AI as a productivity tool rather than an authority. I always validate design decisions with first-principles reasoning, logging, and testing before accepting them.

---

## Why this is a strong story

This story demonstrates several qualities interviewers look for:

* You use AI effectively to speed up development.
* You don't blindly trust AI-generated suggestions.
* You validate ideas with reasoning and experiments.
* You understand the underlying system well enough to challenge incorrect advice.
* You improve the project by adding tests after resolving the disagreement.

---

### You actually have an even stronger follow-up

Later, you discovered **the KV deadlock problem**, and this time **AI didn't initially point it out—you did.**

The conversation went roughly like this:

1. You implemented KV accounting.
2. Everything passed the tests.
3. You manually constructed a workload:

   * Request A: 64 tokens
   * Request B: 14 tokens
   * Request C: 44 tokens
4. You realized that after enough decode rounds, KV memory would become completely full.
5. You asked:

   > "Wouldn't the scheduler deadlock here? This seems unsolvable."

That observation wasn't triggered by AI—it came from your own reasoning about the system's behavior over time.

The subsequent discussion connected your observation to production techniques such as:

* KV-aware decode scheduling,
* forward progress guarantees,
* PagedAttention,
* KV offloading.

That's an even stronger signal because it shows you weren't just implementing features—you were reasoning about the correctness and scalability of the design.

---

## If a company like Anthropic, OpenAI, or Databricks asks this question

I'd finish with something like:

> "I've found AI to be extremely effective for accelerating implementation and exploring design alternatives, but I don't treat it as a source of truth. In this project, AI helped me iterate much faster, but I still verified every important design decision with first-principles reasoning, logging, and targeted tests. In one case I concluded the AI's suggestion about KV accounting was incorrect after tracing the scheduler state across multiple ticks. In another case, I identified a scheduler deadlock scenario that neither my implementation nor the AI had initially considered. Those experiences reinforced that AI is most valuable as a collaborator—the engineer is still responsible for validating correctness."

That's a very mature answer because it shows you can **leverage AI for productivity while maintaining engineering judgment**, which is exactly what employers are looking for in the AI era.
