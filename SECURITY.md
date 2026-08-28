# Security policy

[English](SECURITY.md) · [简体中文](SECURITY.zh-CN.md)

iamllm stores model requests, human replies, attachment metadata, administrator devices, and credential hashes. Treat a deployment as a production service containing private conversations, not as a static website.

## Reporting a vulnerability

Use a private contact method provided by the repository maintainer. Do not include any of the following in a public issue:

- working API keys, administrator tokens, passwords, or session secrets;
- complete databases, backups, logs, or `.env` files;
- private conversations, system prompts, file contents, or device refresh tokens;
- instructions that directly expose an unpatched instance.

A report may include a redacted version, deployment method, affected endpoint, reproduction conditions, impact, and suggested fix. Coordinate public disclosure after the maintainer confirms and fixes the issue.

## Minimum deployment requirements

- Use HTTPS publicly and let only the local reverse proxy reach `127.0.0.1:8000`.
- Keep the environment owner key private; issue limited, revocable managed keys to callers.
- Set `.env.production` permissions to `600` and never put it in Git, a container image, or chat.
- Back up SQLite regularly and protect backups like conversation content.
- Revoke an administrator device after a phone or computer is lost.
- Back up before updating dependencies or iamllm, then verify health and login afterward.
- Do not send raw context, attachments, or notification payloads to untrusted third parties.

## Credential storage

- Managed API keys and device refresh tokens are stored as HMAC hashes.
- A managed key is shown in full only once; the server cannot recover it later.
- The deployment environment remains responsible for the owner key, administrator token, administrator password, and session secret.
- SQLite backups contain conversations and configuration and remain sensitive even without plaintext keys.

## Support scope

Security support covers the current main branch and latest stable release. Older releases with publicly available fixes are not guaranteed to receive backports.

iamllm is currently a single-instance design. Multiple processes sharing one SQLite database, unreliable network filesystems, and direct exposure of the administration port are unsupported deployment modes.
