"""Security findings captured as failing tests, before the fixes.

Every test here is a strict expected failure: it must fail today, and once its fix
lands it passes, which strict mode reports as a failure until the marker is removed.

- `bug(...)`: a defect in tkt's code (batch A), fixed without design decisions.
- `design(...)`: the right behaviour still needs a decision (batch C); the test pins the
  security property, not the shape of the fix, and may be adjusted with that decision.
"""
