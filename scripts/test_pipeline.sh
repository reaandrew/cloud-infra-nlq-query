#!/usr/bin/env bash
# End-to-end smoke test for the extract + Iceberg pipeline.
#
# Assumes terraform/app has already been applied. Reads output values from
# terraform state rather than re-querying AWS, so it's fast and deterministic.
#
# Flow:
#   1. Read queue URL + bucket names + database/table names from terraform outputs.
#   2. Poll SQS ApproximateNumberOfMessages + NotVisible until both are 0.
#   3. Run an Athena query against operational_live and print summary rows.
#
# Usage:
#   scripts/test_pipeline.sh [timeout_seconds]
set -euo pipefail

TIMEOUT="${1:-360}"
TF_DIR="${TF_DIR:-terraform/app}"

tf_out() {
  terraform -chdir="$TF_DIR" output -raw "$1"
}

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not on PATH" >&2
  exit 1
fi

echo "==> reading terraform outputs from $TF_DIR"
QUEUE_URL=$(tf_out extract_queue_url)
DATABASE=$(tf_out glue_database)
LIVE_VIEW=$(tf_out iceberg_live_view)
ICEBERG_TABLE=$(tf_out iceberg_table)
RESULTS_BUCKET=$(tf_out athena_results_bucket)

echo "  queue:     $QUEUE_URL"
echo "  database:  $DATABASE"
echo "  table:     $ICEBERG_TABLE"
echo "  view:      $LIVE_VIEW"
echo

echo "==> waiting for SQS to drain (timeout ${TIMEOUT}s)"
deadline=$(( $(date +%s) + TIMEOUT ))
last_print=0
while :; do
  attrs=$(aws sqs get-queue-attributes \
    --queue-url "$QUEUE_URL" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateNumberOfMessagesDelayed \
    --output text --query 'Attributes.[ApproximateNumberOfMessages,ApproximateNumberOfMessagesNotVisible,ApproximateNumberOfMessagesDelayed]')
  visible=$(echo "$attrs" | awk '{print $1}')
  in_flight=$(echo "$attrs" | awk '{print $2}')
  delayed=$(echo "$attrs" | awk '{print $3}')

  now=$(date +%s)
  if (( now - last_print >= 5 )); then
    echo "  visible=$visible in_flight=$in_flight delayed=$delayed"
    last_print=$now
  fi

  if [[ "$visible" == "0" && "$in_flight" == "0" && "$delayed" == "0" ]]; then
    echo "  queue drained"
    break
  fi

  if (( now >= deadline )); then
    echo "ERROR: queue did not drain within ${TIMEOUT}s (visible=$visible in_flight=$in_flight delayed=$delayed)" >&2
    exit 1
  fi

  sleep 3
done
echo

# Run a single Athena query, poll for completion, stream results
run_athena() {
  local label="$1" sql="$2"
  echo "==> athena: $label"
  echo "    $sql"
  local qid
  qid=$(aws athena start-query-execution \
    --query-string "$sql" \
    --query-execution-context "Database=$DATABASE" \
    --result-configuration "OutputLocation=s3://${RESULTS_BUCKET}/test-pipeline/" \
    --output text --query 'QueryExecutionId')
  local state
  for _ in $(seq 1 60); do
    state=$(aws athena get-query-execution --query-execution-id "$qid" --output text --query 'QueryExecution.Status.State')
    case "$state" in
      SUCCEEDED)
        aws athena get-query-results --query-execution-id "$qid" --output table \
          --query 'ResultSet.Rows[*].Data[*].VarCharValue' 2>/dev/null || true
        echo
        return 0
        ;;
      FAILED|CANCELLED)
        reason=$(aws athena get-query-execution --query-execution-id "$qid" --output text --query 'QueryExecution.Status.StateChangeReason')
        echo "    query $qid $state: $reason" >&2
        return 1
        ;;
    esac
    sleep 2
  done
  echo "    query $qid timed out" >&2
  return 1
}

run_athena "snapshot count (proves iceberg appends landed)" \
  "SELECT count(*) AS snapshot_count FROM \"${DATABASE}\".\"${ICEBERG_TABLE##*.}\$snapshots\""

run_athena "live view totals" \
  "SELECT count(*) AS rows, count(DISTINCT account_id) AS accounts, count(DISTINCT resource_type) AS types FROM $LIVE_VIEW"

run_athena "top 10 resource types in live view" \
  "SELECT resource_type, count(*) AS rows FROM $LIVE_VIEW GROUP BY 1 ORDER BY 2 DESC LIMIT 10"

echo "==> test-pipeline done"
