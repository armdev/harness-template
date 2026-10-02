# Contract suite

The specification of the public API (`gateway`) and of the service boundary rules. It runs against the
running stack (`make up && make contract`) and is the `contract` sensor in `harness.yaml`.

- Change an implementation to make a contract test pass; change a contract test **only** when the task asks
  for new behaviour (rubric R2), and in the same change as the implementation.
- One file per resource. Tests create their own data (unique `author` per test run) and never depend on order.
- Asynchronous effects (search indexing) are awaited with `eventually()`, a bounded poll — never a bare sleep.
