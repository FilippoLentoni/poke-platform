#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
STACK="${STACK:-PokePlatformStack}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

usage() {
  echo "Usage: $0 <task>"
  echo "Tasks: universe_updater | price_extractor | strategy_runner | proposal_generator"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

task="$1"
case "$task" in
  universe_updater) logical_rule="UniverseUpdaterDailyRule" ;;
  price_extractor) logical_rule="PriceExtractorDailyRule" ;;
  strategy_runner) logical_rule="StrategyRunnerDailyRule" ;;
  proposal_generator) logical_rule="ProposalGeneratorDailyRule" ;;
  *) usage; exit 1 ;;
esac

rule_name="$(aws_cmd cloudformation list-stack-resources \
  --stack-name "$STACK" \
  --output json \
  | jq -r ".StackResourceSummaries[] | select(.LogicalResourceId==\"${logical_rule}\") | .PhysicalResourceId" \
  | head -n1 \
  | tr -d '\r' \
  | xargs)"

if [[ -z "$rule_name" || "$rule_name" == "None" ]]; then
  echo "Rule not found for $task (logical: $logical_rule) in stack $STACK."
  exit 1
fi

echo "Resolved RULE_NAME: $rule_name"

cluster_arn="$(aws_cmd events list-targets-by-rule --rule "$rule_name" --query "Targets[0].Arn" --output text)"
task_def="$(aws_cmd events list-targets-by-rule --rule "$rule_name" --query "Targets[0].EcsParameters.TaskDefinitionArn" --output text)"
subnets="$(aws_cmd events list-targets-by-rule --rule "$rule_name" --query "Targets[0].EcsParameters.NetworkConfiguration.awsvpcConfiguration.Subnets" --output text)"
security_groups="$(aws_cmd events list-targets-by-rule --rule "$rule_name" --query "Targets[0].EcsParameters.NetworkConfiguration.awsvpcConfiguration.SecurityGroups" --output text)"
assign_public_ip="$(aws_cmd events list-targets-by-rule --rule "$rule_name" --query "Targets[0].EcsParameters.NetworkConfiguration.awsvpcConfiguration.AssignPublicIp" --output text)"

if [[ -z "$cluster_arn" || "$cluster_arn" == "None" ]]; then
  echo "Cluster ARN not found from rule target."
  exit 1
fi
if [[ -z "$task_def" || "$task_def" == "None" ]]; then
  echo "Task definition not found from rule target."
  exit 1
fi
if [[ -z "$subnets" || "$subnets" == "None" || -z "$security_groups" || "$security_groups" == "None" || -z "$assign_public_ip" || "$assign_public_ip" == "None" ]]; then
  echo "Network configuration missing from rule target. Full target JSON:"
  aws_cmd events list-targets-by-rule --rule "$rule_name" --output json
  exit 1
fi

subnets_csv="$(printf '%s' "$subnets" | tr '\t' ',')"
sgs_csv="$(printf '%s' "$security_groups" | tr '\t' ',')"

echo "Rule: $rule_name"
echo "Cluster: $cluster_arn"
echo "Task definition: $task_def"
echo "Subnets: $subnets_csv"
echo "Security groups: $sgs_csv"
echo "Assign public IP: $assign_public_ip"

task_arn="$(aws_cmd ecs run-task \
  --cluster "$cluster_arn" \
  --launch-type FARGATE \
  --task-definition "$task_def" \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets_csv],securityGroups=[$sgs_csv],assignPublicIp=$assign_public_ip}" \
  --query "tasks[0].taskArn" \
  --output text)"

if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "Failed to start task."
  exit 1
fi

echo "Task ARN: $task_arn"
echo "Waiting for STOPPED..."

while true; do
  status="$(aws_cmd ecs describe-tasks \
    --cluster "$cluster_arn" \
    --tasks "$task_arn" \
    --query "tasks[0].lastStatus" \
    --output text)"
  if [[ "$status" == "STOPPED" ]]; then
    break
  fi
  sleep 10
done

exit_code="$(aws_cmd ecs describe-tasks \
  --cluster "$cluster_arn" \
  --tasks "$task_arn" \
  --query "tasks[0].containers[0].exitCode" \
  --output text)"

stopped_reason="$(aws_cmd ecs describe-tasks \
  --cluster "$cluster_arn" \
  --tasks "$task_arn" \
  --query "tasks[0].stoppedReason" \
  --output text)"

echo "Stopped reason: $stopped_reason"
echo "Exit code: $exit_code"

if [[ "$exit_code" =~ ^[0-9]+$ ]]; then
  exit "$exit_code"
fi
