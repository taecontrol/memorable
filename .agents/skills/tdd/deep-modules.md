# Deep Modules

From "A Philosophy of Software Design":

**Deep module** = small interface + lots of implementation

```
┌─────────────────────┐
│   Small Interface   │  ← Few methods, simple params
├─────────────────────┤
│                     │
│                     │
│  Deep Implementation│  ← Complex logic hidden
│                     │
│                     │
└─────────────────────┘
```

**Shallow module** = large interface + little implementation (avoid)

```
┌─────────────────────────────────┐
│       Large Interface           │  ← Many methods, complex params
├─────────────────────────────────┤
│  Thin Implementation            │  ← Just passes through
└─────────────────────────────────┘
```

When designing interfaces, ask:

- Can I reduce the number of methods?
- Can I simplify the parameters?
- Can I hide more complexity inside?
- Does each public method justify its existence by offering real value to callers?

In Python, this means:

- Prefer a class with 3 well-designed methods over 12 thin wrappers
- Use `__init__` to absorb configuration complexity
- Hide helper functions as private (`_helper`) — don't expose them
- Use `@property` to present computed state without leaking how it's computed
- A Protocol with fewer methods is easier to implement, test, and fake
