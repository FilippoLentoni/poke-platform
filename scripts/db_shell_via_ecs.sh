#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
STACK="${STACK:-PokePlatformStack}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

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

exec_cmd=$'bash -lc \'set -euo pipefail\n\
if ! command -v psql >/dev/null 2>&1; then\n\
  if command -v apt-get >/dev/null 2>&1; then\n\
    apt-get update -y >/dev/null && apt-get install -y postgresql-client >/dev/null\n\
  elif command -v yum >/dev/null 2>&1; then\n\
    yum -y install postgresql >/dev/null\n\
  else\n\
    echo \"psql not installed and no package manager found.\"\n\
    exit 1\n\
  fi\n\
fi\n\
\n\
: \"${DB_HOST:?DB_HOST missing}\"\n\
: \"${DB_PORT:=5432}\"\n\
: \"${DB_NAME:=poke}\"\n\
: \"${DB_USER:?DB_USER missing}\"\n\
: \"${DB_PASSWORD:?DB_PASSWORD missing}\"\n\
\n\
psql_cmd() { PGPASSWORD=\"$DB_PASSWORD\" psql -h \"$DB_HOST\" -p \"$DB_PORT\" -U \"$DB_USER\" -d \"$DB_NAME\" -t -A -c \"$1\"; }\n\
\n\
echo \"card_metadata_count=$(psql_cmd \"SELECT COUNT(*) FROM card_metadata;\")\"\n\
echo \"card_metadata_latest_snapshot=$(psql_cmd \"SELECT MAX(snapshot_date) FROM card_metadata;\")\"\n\
\''

aws_cmd ecs execute-command \
  --cluster "$cluster_arn" \
  --task "$task_arn" \
  --container "ApiContainer" \
  --command "$exec_cmd" \
  --interactive
