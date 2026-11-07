# Security policy

Almost Delicious is a research prototype for a master's thesis. It is not
operated as a public service, and only the latest `main` receives fixes.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability**
(private security advisory) on this repository instead, and include the affected
file or endpoint and steps to reproduce. Expect a reply within a few days.

## Credentials and configuration

- No credentials are stored in the repository or the container image. Configure
  Elasticsearch and model-provider keys only through environment variables or
  an ignored `.env` (see `.env.example`).
- Never paste keys into issues, commit messages, command arguments or screenshots.
- Keep private keys (SSH, CA private keys) outside the repository; only a public
  CA certificate may be mounted from an external directory.
- `uv run python scripts/scan_secrets.py --history` scans the working tree and
  all history; CI runs it on every push.
