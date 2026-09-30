# Runtime Manager

Isolated agent runtime orchestration service.

## Providers

- **MockRuntimeProvider** (default in development) — in-process agent simulation
- **DockerRuntimeProvider** (production) — container-based isolation

## API

```
POST   /runtimes              Create runtime
GET    /runtimes/{id}         Status
POST   /runtimes/{id}/invoke  Execute agent (internal only)
DELETE /runtimes/{id}         Destroy runtime
```

## Security

- Non-root containers
- No docker.sock in agent containers
- CPU/memory limits
- Network policies: none, internet_read, allowlist
- Immutable image digests only

See [docs/RUNTIME.md](../../docs/RUNTIME.md).
