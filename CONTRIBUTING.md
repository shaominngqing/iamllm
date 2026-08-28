# Contributing

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

Thank you for helping make iamllm better. The project favors software that one person can understand, deploy, and maintain for years; feature count is not the only goal.

## Before you start

- Bug reports should include a minimal reproduction, client and version, protocol endpoint, expected result, and actual result.
- Product proposals should explain the use case and intended user before prescribing an implementation.
- Never post real API keys, administrator credentials, private conversations, or local file paths in issues, logs, or screenshots.
- Open an issue before a large architectural change so the boundaries are clear before implementation.

## Local environment

Go 1.25, Node.js 22, and Flutter stable are required:

```bash
cp .env.example .env
set -a; source .env; set +a
make dev
```

Run the full checks before submitting:

```bash
make test
docker build -t iamllm:test .
```

For Web-only changes, run at least `make web`. For Flutter-only changes, run at least `flutter analyze` and `flutter test`.

## Architecture boundaries

- `internal/protocol` only translates vendor request/response formats and domain objects.
- Queueing, waiting, automation, limits, and device sessions belong to `internal/application`.
- Business logic depends on `internal/repository` contracts, not SQLite details.
- React and Flutter use the versioned Admin API and never access the database directly.
- New clients should reuse existing protocols whenever those protocols can express the required behavior.
- The current product is single-instance; incomplete distributed abstractions should not increase deployment cost.

See [Architecture](docs/en/architecture.md) for details.

## Pull requests

An easy-to-review pull request should:

1. explain what changed and why;
2. keep the change focused;
3. add a regression test for a bug fix;
4. update documentation when public APIs, environment variables, or user flows change;
5. exclude build artifacts, real `.env` files, databases, signing files, and personal configuration;
6. pass `make test` and `docker build`.

Use short English commit prefixes when practical:

```text
feat: add scheduled auto reply
fix: merge streamed chunks in conversation view
docs: document Claude Code setup
```

## Data changes

The repository currently contains one clean baseline schema. After the first stable release, published schema changes must use forward migrations instead of asking users to delete their databases.

Repository changes should cover creation, reads, concurrency, idempotency, and recovery after restart.

## UI and interaction

- The web console prioritizes desktop administration efficiency and clear information hierarchy.
- Flutter follows iOS spacing, corner radius, navigation, and feedback conventions while remaining usable on Android.
- Stream chunks form one assistant message in chat; transport details belong in the run log.
- User-visible chat, internal context, and tool execution must stay clearly separated.
- Loading, empty, error, retry, and reconnect states are part of the feature.

## License

By contributing, you agree that your contribution is released under the [MIT License](LICENSE).
