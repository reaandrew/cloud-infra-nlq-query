#!/usr/bin/env bash
# Run a DDL statement through Athena and block until it finishes.
# Usage: run_ddl.sh <sql-file> <database> <results-bucket>
set -euo pipefail

sql_file="${1:?sql file required}"
database="${2:?database required}"
results_bucket="${3:?results bucket required}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not on PATH" >&2
  exit 1
fi

qid=$(aws athena start-query-execution \
  --query-string "file://${sql_file}" \
  --result-configuration "OutputLocation=s3://${results_bucket}/ddl/" \
  --query-execution-context "Database=${database}" \
  --output text --query 'QueryExecutionId')

echo "athena: started $qid (db=${database}, sql=${sql_file})"

for i in $(seq 1 90); do
  state=$(aws athena get-query-execution \
    --query-execution-id "$qid" \
    --output text --query 'QueryExecution.Status.State')
  case "$state" in
    SUCCEEDED)
      echo "athena: $qid SUCCEEDED"
      exit 0
      ;;
    FAILED|CANCELLED)
      reason=$(aws athena get-query-execution \
        --query-execution-id "$qid" \
        --output text --query 'QueryExecution.Status.StateChangeReason')
      echo "athena: $qid $state: $reason" >&2
      exit 1
      ;;
  esac
  sleep 2
done

echo "athena: $qid timed out after 180s" >&2
exit 1
