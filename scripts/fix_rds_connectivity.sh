#!/usr/bin/env bash
set -euo pipefail

REGION="${REGION:-us-east-2}"
SECRET_ARN="${SECRET_ARN:-arn:aws:secretsmanager:us-east-2:878817878019:secret:PokePlatformStackPostgresSe-uD7oKVjyUmYi-NFBVMe}"

aws_cmd() {
  aws --region "$REGION" "$@"
}

require_bin() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

echo "Region: $REGION"
echo "Secret ARN: $SECRET_ARN"

secret_string="$(aws_cmd secretsmanager get-secret-value \
  --secret-id "$SECRET_ARN" \
  --query "SecretString" \
  --output text)"

if [[ -z "$secret_string" || "$secret_string" == "None" ]]; then
  echo "Failed to read SecretString from $SECRET_ARN"
  exit 1
fi

db_instance_id="$(printf '%s' "$secret_string" | sed -n 's/.*"dbInstanceIdentifier"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
db_host="$(printf '%s' "$secret_string" | sed -n 's/.*"host"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"

if [[ -z "$db_instance_id" || -z "$db_host" ]]; then
  echo "Could not parse dbInstanceIdentifier or host from SecretString."
  echo "SecretString: $secret_string"
  exit 1
fi

echo "RDS Instance ID: $db_instance_id"
echo "RDS Host: $db_host"

db_info="$(aws_cmd rds describe-db-instances --db-instance-identifier "$db_instance_id")"
db_vpc_id="$(printf '%s' "$db_info" | sed -n 's/.*"VpcId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
db_endpoint_address="$(printf '%s' "$db_info" | sed -n 's/.*"Address"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
db_endpoint_port="$(printf '%s' "$db_info" | sed -n 's/.*"Port"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' | head -n1)"

db_sgs="$(aws_cmd rds describe-db-instances \
  --db-instance-identifier "$db_instance_id" \
  --query "DBInstances[0].VpcSecurityGroups[].VpcSecurityGroupId" \
  --output text)"

if [[ -z "$db_vpc_id" || -z "$db_sgs" ]]; then
  echo "Failed to discover RDS VPC or security groups."
  exit 1
fi

echo "RDS VPC: $db_vpc_id"
echo "RDS SGs: $db_sgs"
echo "RDS Endpoint: ${db_endpoint_address}:${db_endpoint_port}"

instance_id="${INSTANCE_ID:-}"
if [[ -z "$instance_id" ]]; then
  token="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" || true)"
  if [[ -n "$token" ]]; then
    instance_id="$(curl -s -H "X-aws-ec2-metadata-token: ${token}" \
      http://169.254.169.254/latest/meta-data/instance-id || true)"
  fi
fi

if [[ -z "$instance_id" ]]; then
  private_ip="$(hostname -I | awk '{print $1}')"
  if [[ -n "$private_ip" ]]; then
    instance_id="$(aws ec2 describe-instances \
      --filters "Name=private-ip-address,Values=$private_ip" \
      --query "Reservations[0].Instances[0].InstanceId" \
      --output text \
      --region "$REGION" || true)"
  fi
fi

if [[ -z "$instance_id" || "$instance_id" == "None" ]]; then
  echo "Failed to resolve EC2 instance ID. Set INSTANCE_ID=i-xxxx and retry."
  exit 1
fi

ec2_vpc_id="$(aws_cmd ec2 describe-instances \
  --instance-ids "$instance_id" \
  --query "Reservations[0].Instances[0].VpcId" \
  --output text)"
ec2_sgs="$(aws_cmd ec2 describe-instances \
  --instance-ids "$instance_id" \
  --query "Reservations[0].Instances[0].SecurityGroups[].GroupId" \
  --output text)"

echo "EC2 Instance ID: $instance_id"
echo "EC2 VPC: $ec2_vpc_id"
echo "EC2 SGs: $ec2_sgs"

if [[ "$ec2_vpc_id" != "$db_vpc_id" ]]; then
  echo "ERROR: EC2 instance VPC ($ec2_vpc_id) does not match RDS VPC ($db_vpc_id)."
  echo "Move the instance to the RDS VPC or create VPC peering."
  exit 1
fi

changed=0
for rds_sg in $db_sgs; do
  for ec2_sg in $ec2_sgs; do
    allowed_sgs="$(aws_cmd ec2 describe-security-groups \
      --group-ids "$rds_sg" \
      --query "SecurityGroups[0].IpPermissions[?IpProtocol=='tcp' && FromPort==\`5432\` && ToPort==\`5432\`].UserIdGroupPairs[].GroupId" \
      --output text)"

    if echo "$allowed_sgs" | tr '\t' '\n' | grep -qx "$ec2_sg"; then
      echo "Ingress already allows tcp/5432 from $ec2_sg -> $rds_sg"
      continue
    fi

    aws_cmd ec2 authorize-security-group-ingress \
      --group-id "$rds_sg" \
      --protocol tcp \
      --port 5432 \
      --source-group "$ec2_sg"
    echo "Added ingress tcp/5432 from $ec2_sg to $rds_sg"
    changed=1
  done
done

if [[ "$changed" -eq 0 ]]; then
  echo "No SG changes required."
fi

host_to_test="${db_endpoint_address:-$db_host}"
port_to_test="${db_endpoint_port:-5432}"

echo "Testing connectivity to ${host_to_test}:${port_to_test}..."
if require_bin nc; then
  nc -vz "$host_to_test" "$port_to_test" || true
else
  if require_bin yum; then
    sudo yum -y install nmap-ncat >/dev/null 2>&1 || true
  fi
  if require_bin nc; then
    nc -vz "$host_to_test" "$port_to_test" || true
  else
    timeout 3 bash -c "</dev/tcp/${host_to_test}/${port_to_test}" || true
  fi
fi

echo "Next steps: retry your psql connection."
