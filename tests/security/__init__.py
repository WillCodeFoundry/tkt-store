"""Security findings captured as failing tests, before the fixes.

Each test carries `@pytest.mark.security_bug(reason)` (a defect in tkt's code) or
`@pytest.mark.security_design(reason)` (a property whose fix needs a decision); the
security conftest makes both strict expected failures."""
