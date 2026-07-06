I think Day 8 turned out to be one of the cleanest days in the project. Unlike Days 5–7, where we introduced new runtime algorithms, Day 8 was about **improving the architecture without changing behavior**. That's exactly what a good refactoring should accomplish.

# Day 8 Summary — Engine Interface & Backend Abstraction

## Goal

Refactor the runtime so that the **Scheduler depends on an abstract engine interface instead of a concrete implementation**.

By the end of Day 8, the scheduler can work with any backend that implements the `ModelEngine` interface.

---

# What We Built

## 1. Introduced the `ModelEngine` Interface

Created:

```text
app/
└── engine/
    └── base.py
```

Defined an abstract interface:

```python
class ModelEngine(ABC):

    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

    @abstractmethod
    async def prefill(...):
        ...

    @abstractmethod
    async def decode_step(...):
        ...
```

This establishes the **runtime contract** between the scheduler and any inference backend.

---

## 2. Refactored `FakeModelEngine`

Instead of a standalone implementation,

```text
FakeModelEngine
```

became

```text
FakeEngine(ModelEngine)
```

The implementation did **not** change.

Only the inheritance hierarchy changed.

---

## 3. Scheduler Now Depends on the Interface

Before:

```text
Scheduler
      │
      ▼
 FakeEngine
```

After:

```text
Scheduler
      │
      ▼
 ModelEngine
      ▲
      │
 FakeEngine
```

This removes the direct dependency on the fake backend and follows the **Dependency Inversion Principle (DIP)** from SOLID design.

---

## 4. Reorganized the Engine Package

New structure:

```text
app/
    engine/
        __init__.py
        base.py
        fake_engine.py
        factory.py
```

This makes it straightforward to add future backends:

```text
engine/
    base.py
    fake_engine.py
    vllm_engine.py
    tensorrt_engine.py
    sglang_engine.py
```

without modifying the scheduler.

---

## 5. Added an Engine Factory

Instead of constructing the backend directly:

```python
engine = FakeEngine()
```

the application now uses:

```python
engine = create_engine("fake")
```

This introduces a simple dependency injection mechanism.

Future backends can be selected by configuration:

```python
engine = create_engine("vllm")
```

with **no scheduler changes**.

---

## 6. Added Backend Metadata

Each engine now exposes

```python
backend_name
```

allowing the application to print startup information such as:

```text
========================================
LLM Inference Gateway
========================================
Backend: fake
========================================
```

This is useful for debugging and resembles production inference services.

---

## 7. Verified Backend Independence

To verify the abstraction, we implemented a `DummyEngine`:

```python
class DummyEngine(ModelEngine):
    ...
```

and successfully ran the scheduler using:

```python
engine = create_engine("dummy")
```

The output confirmed:

```text
Backend: Dummy
```

This demonstrated that the scheduler depends only on the `ModelEngine` interface rather than a specific implementation.

Although `DummyEngine` does not perform real decoding, it served its purpose as an architectural verification.

---

# Architecture Evolution

### Day 7

```text
REST API
    │
    ▼
Scheduler
    │
    ▼
FakeEngine
```

---

### Day 8

```text
REST API
    │
    ▼
Scheduler
    │
    ▼
ModelEngine
    ▲
    │
 ┌──┴──────────────┐
 │                 │
FakeEngine    DummyEngine
```

Future:

```text
                Scheduler
                    │
                    ▼
              ModelEngine
      ┌─────────┼───────────┐
      ▼         ▼           ▼
 FakeEngine  VLLMEngine  TensorRTEngine
```

This closely mirrors the architecture used in modern LLM serving systems such as **vLLM**, **TensorRT-LLM**, **SGLang**, and **Text Generation Inference (TGI)**.

---

# Design Principles Learned

During Day 8, we applied several important software engineering principles:

* **Dependency Inversion Principle (DIP):** High-level modules (`Scheduler`) depend on abstractions (`ModelEngine`) instead of concrete implementations.
* **Open/Closed Principle (OCP):** New inference backends can be added without modifying the scheduler.
* **Dependency Injection (DI):** The engine is selected externally and injected into the scheduler.
* **Interface-based Design:** The scheduler interacts only through a well-defined runtime contract.

These principles are common in production AI infrastructure, where scheduling logic is intentionally decoupled from backend-specific implementations.

---

# What We Did *Not* Change

Importantly, Day 8 was a **pure architectural refactor**.

We intentionally left the runtime behavior unchanged:

* Continuous batching
* Admission control
* Token budget
* KV cache management
* Decode scheduling
* Request lifecycle

All existing tests continued to pass, confirming that the refactor introduced no behavioral regressions.

---

# Project Progress

At this point, the project has evolved from a simple request scheduler into a modular inference runtime.

| Day       | Milestone                                          |
| --------- | -------------------------------------------------- |
| **Day 5** | Continuous batching scheduler                      |
| **Day 6** | Prefill/Decode separation + Token Budget           |
| **Day 7** | KV Cache abstraction and memory management         |
| **Day 8** | Engine abstraction and backend-independent runtime |

---

# Looking Ahead to Day 9

With the engine interface now stable, the next feature naturally builds on it:

```text
Scheduler
      │
      ▼
ModelEngine.decode_step()
      │
      ▼
Generated token
      │
      ▼
Streaming Response
      │
      ▼
Client
```

Day 9 will introduce **streaming token generation**, allowing clients to receive tokens incrementally as they are produced. This is another major step toward a production-style LLM serving system and prepares the project for integrating a real backend like vLLM in the following stage.
