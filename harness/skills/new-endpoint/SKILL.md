---
name: new-endpoint
description: Add or change an HTTP endpoint in air-harness, contract first. Use for any task that changes what the public API (gateway) or an internal service accepts or returns.
---

# Add or change an endpoint (contract first)

The contract suite in `contract/` is the specification. Write the contract test before the implementation, and
watch it fail for the right reason.

1. **Decide where it lives.** The public route is in `services/gateway/app.py` under `/api/...` and only forwards.
   The behaviour lives in the service that owns the data (`content` owns posts, `search` owns the index).
   A new internal call is a new edge in the call graph: follow `harness/skills/new-service/SKILL.md` step 4.
2. **Contract test** in `contract/test_<resource>.py`, through the gateway (`api` fixture):
   - status code and full response shape for the happy path;
   - every validation rule (422) and the not-found case (404);
   - data created with the per-test `author` fixture, so tests never see each other's data;
   - asynchronous effects with `eventually(...)`, never `time.sleep`.
3. **Implement** in the owning service: a pydantic model for input and output (`Field` constraints carry the
   validation), `Depends(require_caller())` on the route, SQL with `%s` parameters only.
4. **Forward** in the gateway with `forward(service, method, path, ...)`; validate query parameters at the gateway
   too, so bad requests never cross the network.
5. **Verify**: `make harness-fast`, then `make up && make contract`. A contract test changed in the same diff as
   behaviour must be a test the task asked for (rubric R2) — say so in the commit message.

Do not: change an existing contract test to make your change pass; return a different shape on error than
FastAPI's `{"detail": ...}`; add an endpoint without its contract test.
