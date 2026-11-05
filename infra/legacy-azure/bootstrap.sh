#!/usr/bin/env bash
set -euo pipefail
cd /home/azureuser/recipe-search
umask 077
if [ ! -f .env ]; then
  for key in ELASTIC_PASSWORD KIBANA_PASSWORD KIBANA_SECURITY_KEY KIBANA_SAVEDOBJECTS_KEY KIBANA_REPORTING_KEY; do
    printf '%s=%s\n' "$key" "$(openssl rand -hex 32)" >> .env
  done
fi
chmod 600 .env
set -a
source .env
set +a
sudo docker compose pull
if [ ! -f certs/es01/es01.crt ]; then
  mkdir -p certs
  cat > certs/instances.yml <<'YAML'
instances:
  - name: es01
    dns: [es01, elasticsearch, localhost]
    ip: [127.0.0.1]
YAML
  sudo docker run --rm --user 0 -v "$PWD/certs:/certs" docker.elastic.co/elasticsearch/elasticsearch:9.0.0 bash -c '
    set -e
    bin/elasticsearch-certutil ca --silent --pem --out /certs/ca.zip
    unzip -o /certs/ca.zip -d /certs
    bin/elasticsearch-certutil cert --silent --pem --in /certs/instances.yml --ca-cert /certs/ca/ca.crt --ca-key ${SSH_KEY_PATH} --out /certs/nodes.zip
    unzip -o /certs/nodes.zip -d /certs
    chown -R 1000:0 /certs
    find /certs -type d -exec chmod 750 {} \;
    find /certs -type f -exec chmod 640 {} \;
    chmod 644 /certs/ca/ca.crt
    rm /certs/ca.zip /certs/nodes.zip
  '
fi
printf 'vm.max_map_count=1048576\n' | sudo tee /etc/sysctl.d/99-recipe-elasticsearch.conf >/dev/null
sudo sysctl --system >/dev/null
sudo docker compose up -d --wait --wait-timeout 360 elasticsearch
# Keep authentication material out of command arguments and output.
printf 'user = "elastic:%s"\ncacert = "%s/certs/ca/ca.crt"\n' "$ELASTIC_PASSWORD" "$PWD" > .curl-auth
chmod 600 .curl-auth
printf '{"password":"%s"}' "$KIBANA_PASSWORD" | curl -fsS --config .curl-auth -H 'Content-Type: application/json' --data-binary @- https://localhost:9200/_security/user/kibana_system/_password >/dev/null
sudo docker compose up -d --wait --wait-timeout 600 kibana
sudo docker compose ps
curl -fsS --config .curl-auth 'https://localhost:9200/_cluster/health?pretty'
