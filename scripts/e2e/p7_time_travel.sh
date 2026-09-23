#!/usr/bin/env bash
# End-to-end acceptance for P7 / Phase 18 (time travel), against a RUNNING
# gateway started from the checkout under test. Not a smoke pass: every step
# below asserts a value the feature promises, and a skipped step is a failure.
#
#   API_BASE=http://127.0.0.1:8100/api/v1 PW_USER=platform-admin PW_PASS=... \
#     bash scripts/e2e/p7_time_travel.sh
#
# Exercises: publish (upload -> v1, digest checked against the bytes),
# execution context + output pins on a run, deterministic replay, correction
# erasure appending v2, diff v1..v2 with identity columns, rollback -> v3 whose
# digest equals v1's, temporal SQL by version and by instant (including an
# instant before v1), the retention policy over versions (report-only), and
# the audit surface. Leaves its project in place as evidence unless
# P7_E2E_CLEANUP=1.
set -uo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8100/api/v1}"
PW_USER="${PW_USER:-platform-admin}"
PW_PASS="${PW_PASS:-change-me-now}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
PASS=0; FAIL=0

say()  { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "  PASS  $*"; }
bad()  { FAIL=$((FAIL+1)); say "  FAIL  $*"; }
check(){ # check <description> <actual> <expected>
  if [[ "$2" == "$3" ]]; then ok "$1 ($2)"; else bad "$1: expected [$3], got [$2]"; fi
}
api()  { # api <method> <path> [curl args...]
  local method="$1" path="$2"; shift 2
  curl -sS -X "$method" "$API_BASE$path" -H "Authorization: Bearer $TOKEN" "$@"
}

say "== P7 time-travel acceptance against $API_BASE =="

# ---- 0. sign in ---------------------------------------------------------
TOKEN="$(curl -sS -X POST "$API_BASE/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$PW_USER\",\"password\":\"$PW_PASS\"}" | jq -r '.access_token // empty')"
if [[ -z "$TOKEN" ]]; then say "  FAIL  login returned no token"; exit 1; fi
ok "signed in as $PW_USER"

# ---- 1. project + upload = version 1 ----------------------------------------
PROJECT_ID="$(api POST /projects -H 'Content-Type: application/json' \
  -d "{\"name\":\"P7 acceptance $STAMP\",\"description\":\"time travel e2e\",\"status\":\"active\"}" | jq -r .id)"
check "project created" "$([[ ${#PROJECT_ID} -eq 36 ]] && echo yes || echo no)" yes

CSV="$WORK/people.csv"
printf 'customer,email,born,amount\nann,ann@acme.com,1990-06-15,10\nbo,bo@acme.com,2000-01-01,20\ncy,cy@acme.com,1985-12-31,\n' > "$CSV"
LOCAL_DIGEST="sha256:$(shasum -a 256 "$CSV" | cut -d' ' -f1)"
UPLOAD="$(api POST "/projects/$PROJECT_ID/datasets/upload?dataset_name=people" -F "file=@$CSV;type=text/csv")"
DATASET_ID="$(echo "$UPLOAD" | jq -r .dataset.id)"
UPLOAD_RUN_ID="$(echo "$UPLOAD" | jq -r .dataset.pipeline_run_id)"
check "upload succeeded" "$(echo "$UPLOAD" | jq -r .dataset.ingestion_status)" succeeded

VERSIONS="$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions")"
check "one version after upload" "$(echo "$VERSIONS" | jq -r .current_version)" 1
V1_DIGEST="$(echo "$VERSIONS" | jq -r '.items[0].content_hash')"
check "v1 digest equals sha256 of the uploaded bytes" "$V1_DIGEST" "$LOCAL_DIGEST"
check "v1 is active" "$(echo "$VERSIONS" | jq -r '.items[0].retention_state')" active
V1_AT="$(echo "$VERSIONS" | jq -r '.items[0].created_at')"
check "upload run carries an output pin" \
  "$(api GET "/projects/$PROJECT_ID/runs/$UPLOAD_RUN_ID/audit" | jq -r '.output_versions[0].version_number')" 1

# ---- 2. a run with clock functions: execution context + output pin ---------
PIPELINE_ID="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/pipelines" -H 'Content-Type: application/json' -d '{
  "name": "ages", "steps_json": [
    {"step_type":"derive_column","config":{"target_column":"as_of","formula":"TODAY()"}},
    {"step_type":"derive_column","config":{"target_column":"age","formula":"AGE_YEARS([born])"}},
    {"step_type":"filter_rows","config":{"conditions":[{"column":"amount","operator":"greater_than","value":0}]}}
  ]}' | jq -r .id)"
RUN="$(api POST "/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/run")"
RUN_ID="$(echo "$RUN" | jq -r .run.id)"
DERIVED_ID="$(echo "$RUN" | jq -r .dataset.id)"
check "run succeeded" "$(echo "$RUN" | jq -r .run.status)" succeeded
CTX="$(echo "$RUN" | jq -c .run.summary_json.execution_context)"
check "context records the base input pin at v1" "$(echo "$CTX" | jq -r '.inputs[0].version_number')" 1
check "context input digest equals v1 digest" "$(echo "$CTX" | jq -r '.inputs[0].content_hash')" "$V1_DIGEST"
check "context records an output pin" "$(echo "$CTX" | jq -r '.outputs[0].version_number')" 1
check "context has a frozen instant" "$(echo "$CTX" | jq -r '.evaluated_at | length > 10')" true
EVAL_DATE="$(echo "$CTX" | jq -r '.evaluated_at[:10]')"
check "TODAY() in the data equals the frozen instant's date" \
  "$(echo "$RUN" | jq -r '.dataset.preview_json.rows[0].as_of[:10]')" "$EVAL_DATE"
AUDIT="$(api GET "/projects/$PROJECT_ID/runs/$RUN_ID/audit")"
check "audit resolves the run to the version it published" \
  "$(echo "$AUDIT" | jq -r '.output_versions[0].dataset_id')" "$DERIVED_ID"
check "audit says the run is replayable" "$(echo "$AUDIT" | jq -r .replayable)" true

# ---- 3. deterministic replay ------------------------------------------------
REPLAY="$(api POST "/projects/$PROJECT_ID/runs/$RUN_ID/replay")"
check "replay is equivalent" "$(echo "$REPLAY" | jq -r .status)" equivalent
check "replay output digest equals original output digest" \
  "$(echo "$REPLAY" | jq -r .replay_output.content_hash)" "$(echo "$REPLAY" | jq -r .original_output.content_hash)"
REPLAY_RUN_ID="$(echo "$REPLAY" | jq -r .replay_run_id)"
check "replay run records replay_of" \
  "$(api GET "/projects/$PROJECT_ID/runs/$REPLAY_RUN_ID/audit" | jq -r .execution_context.replay_of)" "$RUN_ID"
check "no pins left open on v1 after the replay" \
  "$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions" | jq -r '.items[0].active_pins')" 0

# ---- 4. correction erasure appends v2; history stays readable --------------
ERASE="$(api POST "/projects/$PROJECT_ID/erasures" -H 'Content-Type: application/json' \
  -d '{"subject_value":"bo@acme.com","subject_kind":"email","apply":true,"mode":"correction"}')"
check "correction erasure completed" "$(echo "$ERASE" | jq -r .status)" completed
VERSIONS="$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions")"
check "correction appended v2" "$(echo "$VERSIONS" | jq -r .current_version)" 2
check "v1 preview still readable (history kept)" \
  "$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/1/preview" | jq -r '.rows | length')" 3
check "v1 still names the subject" \
  "$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/1/preview" | jq -r '[.rows[].email] | index("bo@acme.com") != null')" true
check "v2 (head) no longer names the subject" \
  "$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/2/preview" | jq -r '[.rows[].email] | index("bo@acme.com") != null')" false

# ---- 5. diff with and without identity ---------------------------------------
DIFF_ID="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/diff" -H 'Content-Type: application/json' \
  -d '{"from_version":1,"to_version":2,"identity_columns":["customer"]}')"
check "diff with identity: 1 row changed" "$(echo "$DIFF_ID" | jq -r .rows_changed)" 1
check "diff with identity: email cell changed" "$(echo "$DIFF_ID" | jq -r '.cells_changed_by_column.email')" 1
DIFF_NOID="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/diff" -H 'Content-Type: application/json' \
  -d '{"from_version":1,"to_version":2}')"
check "diff without identity: changed unavailable, says so" "$(echo "$DIFF_NOID" | jq -r .changed_available)" false
check "diff without identity: multiset counts 1 added / 1 removed" \
  "$(echo "$DIFF_NOID" | jq -r '"\(.rows_added)/\(.rows_removed)"')" "1/1"

# ---- 6. rollback to v1 appends v3 with v1's digest -------------------------
ROLLBACK="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/1/rollback")"
check "rollback appended v3" "$(echo "$ROLLBACK" | jq -r .version_number)" 3
check "v3 digest equals v1 digest" "$(echo "$ROLLBACK" | jq -r .content_hash)" "$V1_DIGEST"
check "rolling back to the head is refused" \
  "$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/3/rollback" -o /dev/null -w '%{http_code}')" 400

# ---- 7. temporal SQL: by version, by instant, before the first ------------
Q_V1="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/query" -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT COUNT(*) AS n FROM dataset WHERE email = '"'"'bo@acme.com'"'"'","version_number":1}')"
check "AS OF v1: the subject is present" "$(echo "$Q_V1" | jq -r '.rows[0].n')" 1
Q_V2="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/query" -H 'Content-Type: application/json' \
  -d '{"sql":"SELECT COUNT(*) AS n FROM dataset WHERE email = '"'"'bo@acme.com'"'"'","version_number":2}')"
check "AS OF v2: the subject is gone" "$(echo "$Q_V2" | jq -r '.rows[0].n')" 0
Q_AT="$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/query" -H 'Content-Type: application/json' \
  -d "{\"sql\":\"SELECT COUNT(*) AS n FROM dataset\",\"as_of\":\"$V1_AT\"}")"
check "AS OF v1's publication instant resolves to v1" "$(echo "$Q_AT" | jq -r .version_number)" 1
check "AS OF an instant before v1 is a 404, not the head" \
  "$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/query" -H 'Content-Type: application/json' \
     -d '{"sql":"SELECT 1 FROM dataset","as_of":"2000-01-01T00:00:00Z"}' -o /dev/null -w '%{http_code}')" 404
check "a write against a version is refused" \
  "$(api POST "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions/query" -H 'Content-Type: application/json' \
     -d '{"sql":"DELETE FROM dataset","version_number":1}' -o /dev/null -w '%{http_code}')" 400

# ---- 8. retention over versions (report-only) -------------------------------
RET="$(api POST "/projects/$PROJECT_ID/retention" -H 'Content-Type: application/json' \
  -d '{"resource_type":"dataset_versions","retain_days":30,"dry_run":true}')"
check "dataset_versions retention policy accepted" "$(echo "$RET" | jq -r .resource_type)" dataset_versions
SWEEP="$(api POST "/projects/$PROJECT_ID/retention/run")"
check "report-only sweep marks nothing (versions are minutes old)" \
  "$(echo "$SWEEP" | jq -r '.plans[0].detail.would_schedule')" 0
check "sweep leaves every version active" \
  "$(api GET "/projects/$PROJECT_ID/datasets/$DATASET_ID/versions" | jq -r '[.items[].retention_state] | unique | join(",")')" active

# ---- summary -----------------------------------------------------------------
say ""
say "== $PASS passed, $FAIL failed  (project $PROJECT_ID, dataset $DATASET_ID, run $RUN_ID) =="
if [[ "${P7_E2E_CLEANUP:-0}" == "1" ]]; then
  api DELETE "/projects/$PROJECT_ID" -o /dev/null && say "  cleaned up project $PROJECT_ID"
fi
rm -rf "$WORK"
[[ "$FAIL" -eq 0 ]]
