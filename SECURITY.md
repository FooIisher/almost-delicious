# Credentials and publication gate

The original prototype folders contained an ES password and an AI Gateway key.
They were removed before importing every reconstructed Git snapshot. Removing
values from code does not revoke those credentials. Original folders/ZIP backups
remain untouched and may still contain obsolete values after rotation.

Publication is blocked until the owner has:
1. Rotated the existing ES credential using their cluster administration workflow.
2. Revoked/replaced the legacy AI Gateway credential in its provider dashboard.
3. Updated only local environment/private .env files in any still-used prototypes
   and the new app. For legacy JEV adapters, set JEV_API_KEY as needed.
4. Verified ES connectivity and the intended provider access using the new values.

Do not paste credentials into chat, command arguments, screenshots or Git issues.
Do not put a private SSH key in this repository or the app image. A public CA may
be mounted from an external directory; its private key stays outside the app.

Run before every initial push (including all tags):

```bash
uv run python scripts/scan_secrets.py
uv run python scripts/scan_secrets.py --history
```

The migration additionally checks exact known legacy values through a private,
untracked audit input. The scanner reports only paths/rule names, never values.
Pattern scanning is defense in depth, not a substitute for credential rotation or
provider access controls. No automatic key rotation or ES password change runs in
startup, tests, Docker build or CI.

After the owner confirms rotation and the local acceptance checks pass:

```bash
git push -u origin main
git push origin v1.0 v1.1 v1.2 v1.3
```

Use the existing credential manager or GitHub sign-in flow. Do not embed tokens
in the remote URL. This migration never force-pushes or deletes remote branches.
