#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
STACK="${STACK:-PokePlatformStack}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

usage() {
  echo "Usage: $0 <component>"
  echo "Components: universe_updater | price_extractor | strategy_runner | s3-exporter | api | ui"
  echo "Optional: LOG_GROUP=/aws/ecs/... to override discovery"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

component="$1"
log_group="${LOG_GROUP:-}"

if [[ -z "$log_group" ]]; then
  log_group="$(aws_cmd logs describe-log-groups \
    --query "logGroups[?contains(logGroupName, \`${component}\`)] | sort_by(@, &lastEventTimestamp) | [-1].logGroupName" \
    --output text)"
fi

if [[ -z "$log_group" || "$log_group" == "None" ]]; then
  log_group="$(aws_cmd logs describe-log-groups \
    --query "logGroups[?contains(logGroupName, \`${STACK}\`)] | sort_by(@, &lastEventTimestamp) | [-1].logGroupName" \
    --output text)"
fi

if [[ -z "$log_group" || "$log_group" == "None" ]]; then
  echo "No log group found for component '$component'."
  exit 1
fi

stream="$(aws_cmd logs describe-log-streams \
  --log-group-name "$log_group" \
  --order-by LastEventTime \
  --descending \
  --max-items 1 \
  --query "logStreams[0].logStreamName" \
  --output text)"

if [[ -z "$stream" || "$stream" == "None" ]]; then
  echo "No log streams found for log group: $log_group"
  exit 1
fi

echo "Log group:  $log_group"
echo "Log stream: $stream"
echo

aws_cmd logs get-log-events \
  --log-group-name "$log_group" \
  --log-stream-name "$stream" \
  --limit 200 \
  --start-from-head false \
  --query "events[].{ts:timestamp,msg:message}" \
  --output text | awk '{print $0}'
