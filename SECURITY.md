# Security Policy

DataSage runs SQL written by a language model, so any bypass of its read-only guard is
treated as a vulnerability. The design is described in the README's
[security model](README.md#security-model).

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |
| < 1.0 | no |

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting:
**Security -> Report a vulnerability** on
<https://github.com/bharatkumar00797/datasage-ai-analyst/security>. Include the affected
version or commit, the impact, and steps to reproduce.

You will get an acknowledgement within 3 working days and a status update within 10 working
days. If you like, you will be credited in the changelog.

## Scope

In scope:

- SQL that writes, attaches, reads non-allowlisted tables (including `sqlite_master`), loads
  extensions or escapes the row cap or timeout.
- CSV uploads that break out of their table, overwrite existing tables or bypass the size caps.
- Reaching another caller's workspace, a real provider in public-demo mode, or the API without
  a valid key in api-key mode.
- Rate-limit or body-cap bypasses, XSS or CSP bypass in the dashboard.
- Secrets exposed in responses, logs or the Docker image.

Out of scope:

- The model choosing a wrong but read-only query on allowlisted data.
- Shared public-demo identity behind a proxy when `DATASAGE_TRUST_PROXY` is unset.
- Loss of in-memory state across restarts or serverless instances (a documented caveat).
