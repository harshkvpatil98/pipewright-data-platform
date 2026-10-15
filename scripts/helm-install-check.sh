#!/usr/bin/env bash
# Install the Helm chart by the deployment guide's own words (A9, Z4).
#
# Reads the shell blocks of "On Kubernetes with Helm" in docs/deployment-guide.md
# and runs them in order, changing only what the guide says to change on a
# laptop: no TLS, and a made-up host. Then checks what the guide says to check,
# through the ingress. Run by the `helm` job in CI on a new kind cluster; the
# images must already be in the cluster, tagged with the chart's appVersion.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST=pipewright.local
INGRESS=${INGRESS_ADDRESS:-http://127.0.0.1:8080}

python3 - "$HOST" > /tmp/helm-guide.sh <<'PY'
import re, sys
host = sys.argv[1]
guide = open("docs/deployment-guide.md").read()
section = guide.split("## On Kubernetes with Helm", 1)[1].split("\n## ", 1)[0]
blocks = re.findall(r"```bash\n(.*?)```", section, flags=re.S)
out = ["set -euxo pipefail"]
for block in blocks:
    if "curl" in block:
        continue  # the check below goes through the ingress without TLS
    block = block.replace("pipewright.example.com", host)
    block = block.replace("--wait --timeout 10m", "--set ingress.tls.enabled=false \\\n  --wait --timeout 15m")
    if "create secret" in block:
        # Run, but not echoed: the secrets would be in the log.
        block = "set +x\necho '+ kubectl create secret generic pipewright-secrets (values not shown)'\n" + block + "set -x\n"
    out.append(block)
print("\n".join(out))
PY
echo "--- the guide's steps, as run:"
cat /tmp/helm-guide.sh
bash /tmp/helm-guide.sh

echo "--- checking through the ingress"
curl_host() { curl -sf -H "Host: $HOST" "$@"; }
# Each address is asked until it answers, for up to three minutes: the ingress
# controller starts sending to a pod a moment after the pod is ready.
until_ok() {
  local what=$1 path=$2
  for attempt in $(seq 1 60); do
    if code=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: $HOST" "$INGRESS$path") && [ "$code" = 200 ]; then
      echo "$what 200"
      return 0
    fi
    sleep 3
  done
  echo "$what never answered 200 (last: $code)"
  return 1
}
until_ok "API ready" /api/v1/health/ready
until_ok "sign-in page" /login
until_ok "API reference" /api/docs
until_ok "help" /help

TOKEN=$(curl_host -X POST "$INGRESS/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"choose-a-long-password"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
PROJECT=$(curl_host -X POST "$INGRESS/api/v1/projects/demo" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
curl_host "$INGRESS/api/v1/projects/$PROJECT/datasets" -H "Authorization: Bearer $TOKEN" | python3 -c "
import json, sys
names = sorted((d['name'], d['row_count']) for d in json.load(sys.stdin)['items'])
print('the example, made in the cluster:', names)
assert ('Customer orders (sample)', 12) in names, names
"
# A file bigger than ingress-nginx lets through by default (1MB), read in the request.
python3 -c "
print('order_id,region,amount')
for i in range(120000): print(f'{i},region-{i % 7},{i % 1000}.50')
" > /tmp/orders.csv
ls -l /tmp/orders.csv
curl_host -X POST "$INGRESS/api/v1/projects/$PROJECT/datasets/upload?dataset_name=Through%20the%20ingress" \
  -H "Authorization: Bearer $TOKEN" -F "file=@/tmp/orders.csv;type=text/csv" | python3 -c "
import json, sys
answer = json.load(sys.stdin)
print('uploaded through the ingress:', answer['dataset']['name'], answer['dataset'].get('row_count'))
assert answer['dataset']['row_count'] == 120000, answer
"
kubectl -n pipewright get pods
echo "The chart installed by the guide's steps, and works."
