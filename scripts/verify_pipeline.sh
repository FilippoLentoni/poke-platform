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

  start_time="$(date -u -d '72 hours ago' +%Y-%m-%dT%H:%M:%SZ)"
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

cluster_arn="$(get_cluster_arn)"
if [[ -z "$cluster_arn" || "$cluster_arn" == "None" ]]; then
  echo "FAIL: ECS cluster not found for stack."
  exit 1
fi
echo "Cluster: $cluster_arn"

rule_names_text="$(get_rule_names)"
if [[ -z "$rule_names_text" ]]; then
  echo "FAIL: No EventBridge rules found in stack."
  exit 1
fi

read -r -a rule_names <<< "$rule_names_text"
fail_reasons=()

echo
echo "EventBridge Rules (last 72h metrics)"
for rule in "${rule_names[@]}"; do
  state="$(aws_cmd events describe-rule --name "$rule" --query "State" --output text)"
  schedule="$(aws_cmd events describe-rule --name "$rule" --query "ScheduleExpression" --output text)"
  targets="$(aws_cmd events list-targets-by-rule --rule "$rule" --query "Targets[].{Id:Id,Arn:Arn}" --output text)"
  invocations="$(metric_sum "$rule" "Invocations")"
  failed="$(metric_sum "$rule" "FailedInvocations")"

  echo "- Rule: $rule"
  echo "  State: $state"
  echo "  Schedule: $schedule"
  if [[ -z "$targets" ]]; then
    echo "  Targets: none"
  else
    echo "  Targets:"
    echo "$targets" | awk '{print "    - " $0}'
  fi
  echo "  Invocations (72h): $invocations"
  echo "  FailedInvocations (72h): $failed"

  if [[ "$state" != "ENABLED" ]]; then
    fail_reasons+=("Rule disabled: $rule")
  fi
  if [[ "${failed%.*}" -gt 0 ]]; then
    fail_reasons+=("FailedInvocations > 0: $rule")
  fi
done

echo
echo "ECS Tasks (last 50)"
running_tasks="$(aws_cmd ecs list-tasks \
  --cluster "$cluster_arn" \
  --desired-status RUNNING \
  --max-items 50 \
  --query "taskArns" \
  --output text)"

if [[ -z "$running_tasks" ]]; then
  echo "- RUNNING: none"
else
  echo "- RUNNING:"
  aws_cmd ecs describe-tasks \
    --cluster "$cluster_arn" \
    --tasks $running_tasks \
    --query "tasks[].{TaskArn:taskArn,LastStatus:lastStatus,StartedAt:startedAt}" \
    --output text | awk '{print "  - " $0}'
fi

stopped_tasks="$(aws_cmd ecs list-tasks \
  --cluster "$cluster_arn" \
  --desired-status STOPPED \
  --max-items 50 \
  --query "taskArns" \
  --output text)"

if [[ -z "$stopped_tasks" ]]; then
  echo "- STOPPED: none"
else
  echo "- STOPPED:"
  aws_cmd ecs describe-tasks \
    --cluster "$cluster_arn" \
    --tasks $stopped_tasks \
    --query "tasks[].{TaskArn:taskArn,LastStatus:lastStatus,StopCode:stopCode,StoppedReason:stoppedReason,ExitCode:containers[0].exitCode}" \
    --output text | awk '{print "  - " $0}'
fi

echo
if [[ ${#fail_reasons[@]} -gt 0 ]]; then
  echo "FAIL"
  for reason in "${fail_reasons[@]}"; do
    echo "- $reason"
  done
  exit 1
fi

echo "OK"
