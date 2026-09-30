# Runtime

See [RUNTIME.md](./RUNTIME.md) for full runtime architecture.

## Providers

| Provider | Use Case |
|----------|----------|
| `MockRuntimeProvider` | Local dev without Docker |
| `DockerRuntimeProvider` | Production — isolated containers |

Set `RUNTIME_PROVIDER=docker` in environment.

## Docker Security

Agent containers run with:

- Non-root user (65534)
- Read-only root filesystem
- All capabilities dropped
- Memory and CPU limits
- PID limit (100)
- `no-new-privileges` security opt
- Isolated `agenthub-agents` network

## Demo Agent Image

Built from `agents/demo-agent/` — routes by `AGENT_SLUG` environment variable.

```bash
docker compose build demo-agent-image
```

## Human Approval

High-risk actions (send email, delete record, execute payment) pause execution and require customer approval in the workspace UI.

Try in workspace: *"Please send email to supplier@example.com"*
