#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${ES_PASSWORD:-}" ]]; then
  echo "Set ES_PASSWORD before explicitly starting the optional ES stack." >&2
  exit 1
fi
cd /usr/share/elasticsearch
if [[ ! -f /certs/ca/ca.crt ]]; then
  bin/elasticsearch-certutil ca --silent --pem --out /certs/ca.zip
  unzip -q /certs/ca.zip -d /certs
fi
if [[ ! -f /certs/es/es.crt ]]; then
  printf 'instances:\n  - name: es\n    dns: [es, localhost]\n    ip: [127.0.0.1]\n' > /certs/instances.yml
  bin/elasticsearch-certutil cert --silent --pem --in /certs/instances.yml --ca-cert /certs/ca/ca.crt --ca-key /certs/ca/ca.key --out /certs/es.zip
  unzip -q /certs/es.zip -d /certs
fi
chown -R 1000:0 /certs
find /certs -type d -exec chmod 750 {} \;
find /certs -type f -exec chmod 640 {} \;
# Only the public CA must be readable by the unprivileged app container.
chmod 755 /certs /certs/ca
chmod 644 /certs/ca/ca.crt
