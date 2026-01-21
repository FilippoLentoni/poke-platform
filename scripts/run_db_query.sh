#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
STACK="${STACK:-PokePlatformStack}"
CONTAINER="${CONTAINER:-ApiContainer}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

usage() {
  echo "Usage: $0 (-f <sql_file> | -q <sql>)"
  echo "Examples:"
  echo "  $0 -q \"SELECT COUNT(*) FROM tracked_asset WHERE is_active=true;\""
  echo "  $0 -f scripts/db_checks.sql"
  echo "  cat queries.sql | $0 -f -"
}

sql_content=""
sql_source=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--file)
      sql_source="$2"
      shift 2
      ;;
    -q|--query)
      sql_content="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -n "$sql_source" ]]; then
  if [[ "$sql_source" == "-" ]]; then
    sql_content="$(cat)"
  else
    if [[ ! -f "$sql_source" ]]; then
      echo "SQL file not found: $sql_source"
      exit 1
    fi
    sql_content="$(cat "$sql_source")"
  fi
fi

if [[ -z "$sql_content" ]]; then
  echo "No SQL provided."
  usage
  exit 1
fi

if command -v base64 >/dev/null 2>&1; then
  sql_b64="$(printf '%s' "$sql_content" | base64 -w 0)"
elif command -v python3 >/dev/null 2>&1; then
  sql_b64="$(python3 - <<'PY' "$sql_content"
import base64
import sys
data = sys.argv[1].encode("utf-8")
print(base64.b64encode(data).decode("ascii"), end="")
PY
)"
else
  echo "base64 or python3 required to encode SQL."
  exit 1
fi

echo "Region: $REGION"
echo "Stack:  $STACK"

cluster_arn="$(aws_cmd cloudformation list-stack-resources \
  --stack-name "$STACK" \
  --output json \
  | jq -r ".StackResourceSummaries[] | select(.ResourceType==\"AWS::ECS::Cluster\") | .PhysicalResourceId" \
  | head -n1 \
  | tr -d '\r' \
  | xargs)"

if [[ -z "$cluster_arn" || "$cluster_arn" == "None" ]]; then
  echo "ECS cluster not found in stack $STACK."
  exit 1
fi
echo "Resolved cluster: $cluster_arn"

service_arn="$(aws_cmd cloudformation list-stack-resources \
  --stack-name "$STACK" \
  --output json \
  | jq -r ".StackResourceSummaries[] | select(.ResourceType==\"AWS::ECS::Service\") | .PhysicalResourceId" \
  | head -n1 \
  | tr -d '\r' \
  | xargs)"

if [[ -z "$service_arn" || "$service_arn" == "None" ]]; then
  echo "API service not found in stack $STACK."
  exit 1
fi
echo "Resolved service: $service_arn"

exec_enabled="$(aws_cmd ecs describe-services \
  --cluster "$cluster_arn" \
  --services "$service_arn" \
  --query "services[0].enableExecuteCommand" \
  --output text)"

if [[ "$exec_enabled" != "True" ]]; then
  echo "ECS Exec is not enabled for the API service. Deploy the stack with execute-command enabled."
  exit 1
fi

task_arn="$(aws_cmd ecs list-tasks \
  --cluster "$cluster_arn" \
  --service-name "$service_arn" \
  --desired-status RUNNING \
  --max-items 1 \
  --query "taskArns[0]" \
  --output text)"

if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "No RUNNING API task found for service $service_arn."
  exit 1
fi

exec_script="$(cat <<'EOS'
set -euo pipefail
if ! command -v psql >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null && apt-get install -y postgresql-client >/dev/null
  elif command -v yum >/dev/null 2>&1; then
    yum -y install postgresql >/dev/null
  else
    echo "psql not installed and no package manager found."
    exit 1
  fi
fi

: "${DB_HOST:?DB_HOST missing}"
: "${DB_PORT:=5432}"
: "${DB_NAME:=poke}"
: "${DB_USER:?DB_USER missing}"
: "${DB_PASSWORD:?DB_PASSWORD missing}"

if command -v base64 >/dev/null 2>&1; then
  echo "$SQL_B64" | base64 -d > /tmp/query.sql
elif command -v python3 >/dev/null 2>&1; then
  python3 -c "import base64,os,sys;sys.stdout.write(base64.b64decode(os.environ.get(\"SQL_B64\", \"\")).decode(\"utf-8\"))" > /tmp/query.sql
else
  echo "base64/python3 not available for decoding SQL."
  exit 1
fi

PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -X -f /tmp/query.sql
EOS
)"

if command -v base64 >/dev/null 2>&1; then
  script_b64="$(printf '%s' "$exec_script" | base64 -w 0)"
elif command -v python3 >/dev/null 2>&1; then
  script_b64="$(python3 - <<'PY' "$exec_script"
import base64
import sys
data = sys.argv[1].encode("utf-8")
print(base64.b64encode(data).decode("ascii"), end="")
PY
)"
else
  echo "base64 or python3 required to encode the exec script."
  exit 1
fi

exec_cmd="bash -lc 'SCRIPT_B64=$script_b64; SQL_B64=$sql_b64; export SQL_B64; if command -v base64 >/dev/null 2>&1; then echo \"\$SCRIPT_B64\" | base64 -d > /tmp/run_query.sh; elif command -v python3 >/dev/null 2>&1; then python3 -c \"import base64,os,sys;sys.stdout.buffer.write(base64.b64decode(os.environ.get(\\\"SCRIPT_B64\\\", \\\"\\\")))\" > /tmp/run_query.sh; else echo \"base64/python3 not available\"; exit 1; fi; bash /tmp/run_query.sh'"

aws_cmd ecs execute-command \
  --cluster "$cluster_arn" \
  --task "$task_arn" \
  --container "$CONTAINER" \
  --command "$exec_cmd" \
  --interactive
