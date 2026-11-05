# Deployment configuration

Default docker-compose.yml starts only the app. Configure it for the existing
cluster; that cluster and its data are not modified. ES_CA_CERTS inside the app
is /run/certs/ca.crt; mount a directory containing only the public CA as ca.crt
through CERTS_DIR. Do not mount the CA private key into the app container.

The optional compose.local-es.yml adds an isolated single-node ES 9.0.0 with TLS,
authentication, new data/certificate volumes and port 19201. Compose merges paths
relative to the first (root) Compose file. Both local and server deployments use
this same app configuration; deployment-specific hosts/credentials live in env.

The bootstrap refuses an empty ES_PASSWORD. It generates local certificates and
never connects to or changes an existing cluster. Start this stack only if you
explicitly want a separate empty cluster. Provision the recipes_clean index
through intentional offline ingest, never app startup. Do not remove named data
volumes as a routine upgrade step.

Linux/server settings: keep app binding on loopback or behind your reverse proxy;
use a container-reachable ES hostname covered by its TLS certificate and mount
its CA. The ES 19201 binding is loopback-only. No public address, private SSH path
or provider key belongs in versioned deployment files.

legacy-azure/ preserves sanitized reference material only. It is not invoked by
the new Compose files. Its documentation IP is a reserved example, not a live host.
