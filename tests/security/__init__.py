"""Security findings captured as failing tests, before the fixes.

Each test carries `@pytest.mark.security_bug(reason)` (a defect in tkt's code) or
`@pytest.mark.security_design(reason)` (a property whose fix needs a decision); the
root conftest makes both strict expected failures.

Each module is self-contained on purpose: the few constants, the `forged()` ticket
builder and the attack payloads are repeated where used rather than shared, so a module
reads on its own. Only real-git machinery (tests/gitkit.py) and the fixtures in this
directory's conftest are shared."""
