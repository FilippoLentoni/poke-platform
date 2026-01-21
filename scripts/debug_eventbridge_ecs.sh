#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
STACK="${STACK:-PokePlatformStack}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

sum_values() {
  awk '{s=0; for(i=1;i<=NF;i++) s+=$i; print s+0}'
}

get_cluster_arn() {
  local arn
  arn="$(aws_cmd cloudformation describe-stacks \
    --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='ClusterArn'].OutputValue" \
    --output text 2>/dev/null || true)"
  if [[ -z "$arn" || "$arn" == "None" ]]; then
    arn="$(aws_cmd cloudformation list-stack-resources \
      --stack-name "$STACK" \
      --query "StackResourceSummaries[?ResourceType=='AWS::ECS::Cluster'].PhysicalResourceId" \
      --output text)"
  fi
  printf '%s\n' "$arn"
}

get_rule_names() {
  aws_cmd cloudformation list-stack-resources \
    --stack-name "$STACK" \
    --query "StackResourceSummaries[?ResourceType=='AWS::Events::Rule'].PhysicalResourceId" \
    --output text
}

metric_sum() {
  local rule_name="$1"
  local metric="$2"
  local start_time end_time data

  start_time="$(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%SZ)"
  end_time="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  data="$(aws_cmd cloudwatch get-metric-statistics \
    --namespace AWS/Events \
    --metric-name "$metric" \
    --dimensions Name=RuleName,Value="$rule_name" \
    --start-time "$start_time" \
    --end-time "$end_time" \
    --period 3600 \
    --statistics Sum \
    --query "Datapoints[].Sum" \
    --output text 2>/dev/null || true)"

  if [[ -z "$data" || "$data" == "None" ]]; then
    printf '0\n'
  else
    printf '%s\n' "$data" | sum_values
  fi
}

echo "Region: $REGION"
echo "Stack:  $STACK"

rule_names_text="$(get_rule_names)"
if [[ -z "$rule_names_text" ]]; then
  echo "No EventBridge rules found in stack."
  exit 1
fi
read -r -a rule_names <<< "$rule_names_text"

echo
echo "EventBridge Invocations (last 7d)"
for rule in "${rule_names[@]}"; do
  invocations="$(metric_sum "$rule" "Invocations")"
  failed="$(metric_sum "$rule" "FailedInvocations")"
  echo "- Rule: $rule"
  echo "  Invocations: $invocations"
  echo "  FailedInvocations: $failed"
  if [[ "${failed%.*}" -gt 0 ]]; then
    echo "  Hint: Check EventBridge rule role permissions (ecs:RunTask + iam:PassRole), cluster ARN condition, and VPC config."
  fi
done

cluster_arn="$(get_cluster_arn)"
if [[ -z "$cluster_arn" || "$cluster_arn" == "None" ]]; then
  echo
  echo "ECS cluster not found for stack."
  exit 1
fi

echo
echo "ECS Cluster Summary"
aws_cmd ecs describe-clusters \
  --clusters "$cluster_arn" \
  --query "clusters[0].{Status:status,RunningTasks:runningTasksCount,PendingTasks:pendingTasksCount,ActiveServices:activeServicesCount}" \
  --output text | awk '{print "- " $0}'

services="$(aws_cmd ecs list-services --cluster "$cluster_arn" --query "serviceArns" --output text)"
if [[ -z "$services" ]]; then
  echo
  echo "ECS Service Events: none (no services found)"
else
  echo
  echo "ECS Service Events (latest 5 per service)"
  aws_cmd ecs describe-services \
    --cluster "$cluster_arn" \
    --services $services \
    --query "services[].{ServiceName:serviceName,Events:events[0:5].[createdAt,message]}" \
    --output text | awk '{print "- " $0}'
fi
