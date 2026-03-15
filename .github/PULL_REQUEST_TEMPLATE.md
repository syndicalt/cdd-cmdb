## What this PR does

<!-- Brief description of the changes -->

## Type of change

- [ ] New test suite
- [ ] Tests added to existing suite
- [ ] New client methods in `harness/client.py`
- [ ] New fixtures in `conftest.py`
- [ ] Profile change
- [ ] Generator improvement
- [ ] Documentation
- [ ] Bug fix in spec

## Invariants added/modified

<!-- List the behavioral contracts this PR enforces or changes -->

-

## Profile impact

<!-- Which profile(s) are affected? -->

- [ ] minimal
- [ ] standard
- [ ] enterprise
- [ ] New custom profile: <!-- name -->

## Checklist

- [ ] No test imports implementation code (all interaction via `harness/client.py`)
- [ ] Test file has module-level docstring listing invariants
- [ ] New endpoints have corresponding client methods
- [ ] New fixtures have cleanup/teardown logic
- [ ] `@given` tests do cleanup in `finally` blocks
- [ ] Tests pass against a compliant CMDB instance
- [ ] Profile `.ini` updated if adding a new suite
