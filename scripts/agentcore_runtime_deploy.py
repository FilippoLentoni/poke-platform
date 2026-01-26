from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import boto3
import yaml
from bedrock_agentcore_starter_toolkit import Runtime

SSM_PREFIX = os.getenv("AGENTCORE_SSM_PREFIX", "/app/poke-platform/agentcore")
DEFAULT_USER = os.getenv("AGENTCORE_TEST_USER", "testuser")
DEFAULT_PASSWORD = os.getenv("AGENTCORE_TEST_PASSWORD", "MyPassword123!")


def _ssm_name(suffix: str) -> str:
    return f"{SSM_PREFIX}/{suffix}"


def get_ssm_parameter(name: str, with_decryption: bool = True) -> Optional[str]:
    ssm = boto3.client("ssm")
    try:
        response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    except ssm.exceptions.ParameterNotFound:
        return None
    return response["Parameter"]["Value"]


def put_ssm_parameter(name: str, value: str, secure: bool = False) -> None:
    ssm = boto3.client("ssm")
    ssm.put_parameter(
        Name=name,
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=True,
    )


def _secret_hash(username: str, client_id: str, client_secret: str) -> str:
    message = bytes(username + client_id, "utf-8")
    key = bytes(client_secret, "utf-8")
    return base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()


def reauthenticate_user(client_id: str, client_secret: str) -> str:
    region = boto3.session.Session().region_name
    cognito_client = boto3.client("cognito-idp", region_name=region)
    secret_hash = _secret_hash(DEFAULT_USER, client_id, client_secret)
    auth_response = cognito_client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": DEFAULT_USER,
            "PASSWORD": DEFAULT_PASSWORD,
            "SECRET_HASH": secret_hash,
        },
    )
    return auth_response["AuthenticationResult"]["AccessToken"]


def get_or_create_cognito_pool(refresh_token: bool = False) -> Dict[str, str]:
    region = boto3.session.Session().region_name
    cognito_client = boto3.client("cognito-idp", region_name=region)

    pool_id = get_ssm_parameter(_ssm_name("pool_id"), with_decryption=False)
    client_id = get_ssm_parameter(_ssm_name("client_id"), with_decryption=False)
    client_secret = get_ssm_parameter(_ssm_name("client_secret"))
    discovery_url = get_ssm_parameter(_ssm_name("cognito_discovery_url"), with_decryption=False)

    if pool_id and client_id and client_secret and discovery_url:
        bearer_token = (
            reauthenticate_user(client_id, client_secret) if refresh_token else ""
        )
        return {
            "pool_id": pool_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "discovery_url": discovery_url,
            "bearer_token": bearer_token,
        }

    user_pool_response = cognito_client.create_user_pool(
        PoolName="AgentCoreRuntimePool", Policies={"PasswordPolicy": {"MinimumLength": 8}}
    )
    pool_id = user_pool_response["UserPool"]["Id"]

    app_client_response = cognito_client.create_user_pool_client(
        UserPoolId=pool_id,
        ClientName="AgentCoreRuntimePoolClient",
        GenerateSecret=True,
        ExplicitAuthFlows=[
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
            "ALLOW_USER_SRP_AUTH",
        ],
    )
    client_id = app_client_response["UserPoolClient"]["ClientId"]
    client_secret = app_client_response["UserPoolClient"]["ClientSecret"]

    cognito_client.admin_create_user(
        UserPoolId=pool_id,
        Username=DEFAULT_USER,
        TemporaryPassword="Temp123!",
        MessageAction="SUPPRESS",
    )
    cognito_client.admin_set_user_password(
        UserPoolId=pool_id,
        Username=DEFAULT_USER,
        Password=DEFAULT_PASSWORD,
        Permanent=True,
    )

    secret_hash = _secret_hash(DEFAULT_USER, client_id, client_secret)
    auth_response = cognito_client.initiate_auth(
        ClientId=client_id,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": DEFAULT_USER,
            "PASSWORD": DEFAULT_PASSWORD,
            "SECRET_HASH": secret_hash,
        },
    )
    bearer_token = auth_response["AuthenticationResult"]["AccessToken"]
    discovery_url = (
        f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
    )

    put_ssm_parameter(_ssm_name("pool_id"), pool_id)
    put_ssm_parameter(_ssm_name("client_id"), client_id)
    put_ssm_parameter(_ssm_name("client_secret"), client_secret, secure=True)
    put_ssm_parameter(_ssm_name("cognito_discovery_url"), discovery_url)

    return {
        "pool_id": pool_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "discovery_url": discovery_url,
        "bearer_token": bearer_token,
    }


def create_agentcore_runtime_execution_role(agent_name: str) -> str:
    iam = boto3.client("iam")
    region = boto3.session.Session().region_name
    account_id = boto3.client("sts").get_caller_identity()["Account"]

    role_name = f"{agent_name}-AgentCoreRuntimeRole-{region}"
    policy_name = f"{agent_name}-AgentCoreRuntimePolicy-{region}"

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"
                    },
                },
            }
        ],
    }

    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECRImageAccess",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": [f"arn:aws:ecr:{region}:{account_id}:repository/*"],
            },
            {
                "Sid": "ECRTokenAccess",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogGroups"],
                "Resource": [f"arn:aws:logs:{region}:{account_id}:log-group:*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                "Resource": ["*"],
            },
            {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "cloudwatch:PutMetricData",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:ApplyGuardrail",
                    "bedrock:Retrieve",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{region}:{account_id}:*",
                ],
            },
        ],
    }

    bucket = os.getenv("S3_PRICE_BUCKET")
    if bucket:
        policy_document["Statement"].append(
            {
                "Sid": "S3PriceRead",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        )

    try:
        existing_role = iam.get_role(RoleName=role_name)
        return existing_role["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        pass

    role_response = iam.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(trust_policy),
        Description="IAM role for Poke Platform AgentCore Runtime",
    )

    policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
    try:
        iam.get_policy(PolicyArn=policy_arn)
    except iam.exceptions.NoSuchEntityException:
        policy_response = iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document),
            Description="Policy for Poke Platform AgentCore Runtime",
        )
        policy_arn = policy_response["Policy"]["Arn"]

    try:
        iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    except Exception as exc:
        if "already" not in str(exc).lower():
            raise

    put_ssm_parameter(_ssm_name("runtime_execution_role_arn"), role_response["Role"]["Arn"])
    return role_response["Role"]["Arn"]


def prepare_workspace(repo_root: Path, workspace: Path) -> None:
    src_dir = repo_root / "services" / "agent_runtime"
    if not src_dir.exists():
        raise FileNotFoundError(f"Agent runtime folder not found: {src_dir}")

    workspace.mkdir(parents=True, exist_ok=True)
    for name in ["agents", "observability"]:
        src = src_dir / name
        dest = workspace / name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

    shutil.copy2(src_dir / "requirements.txt", workspace / "requirements.txt")


def configure_runtime(args: argparse.Namespace) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    workspace = repo_root / args.workspace
    prepare_workspace(repo_root, workspace)

    os.chdir(workspace)

    execution_role_arn = create_agentcore_runtime_execution_role(args.agent_name)
    authorizer = None
    request_header_configuration = None
    if not args.no_auth:
        cognito = get_or_create_cognito_pool(refresh_token=args.refresh_token)
        authorizer = {
            "customJWTAuthorizer": {
                "allowedClients": [cognito["client_id"]],
                "discoveryUrl": cognito["discovery_url"],
            }
        }
        request_header_configuration = {
            "requestHeaderAllowlist": ["Authorization"],
        }
        if cognito.get("bearer_token"):
            put_ssm_parameter(_ssm_name("bearer_token"), cognito["bearer_token"], secure=True)

    runtime = Runtime()
    response = runtime.configure(
        entrypoint="agents/orchestration_agent/agent.py",
        execution_role=execution_role_arn,
        auto_create_ecr=True,
        requirements_file="requirements.txt",
        region=args.region,
        agent_name=args.agent_name,
        authorizer_configuration=authorizer,
        request_header_configuration=request_header_configuration,
    )

    print("Configuration completed:", response)


def launch_runtime(args: argparse.Namespace) -> None:
    runtime = Runtime()
    env_vars = {}
    for item in args.env:
        if "=" not in item:
            raise ValueError(f"Invalid --env format: {item}. Use KEY=VALUE")
        key, value = item.split("=", 1)
        env_vars[key] = value

    config_path = Path(args.workspace).expanduser().resolve() / ".bedrock_agentcore.yaml"
    if config_path.exists():
        config_data = yaml.safe_load(config_path.read_text())
        agents = config_data.get("agents", {})
        agent_cfg = agents.get(args.agent_name)
        if agent_cfg is not None and not agent_cfg.get("source_path"):
            agent_cfg["source_path"] = str(Path(args.workspace).expanduser().resolve())
            config_path.write_text(yaml.safe_dump(config_data, sort_keys=False))
        runtime._config_path = config_path
    else:
        raise FileNotFoundError(
            f"Missing config at {config_path}. Run `configure` first."
        )

    launch_result = runtime.launch(auto_update_on_conflict=args.auto_update, env_vars=env_vars)
    print("Launch completed:", launch_result.agent_arn)
    put_ssm_parameter(_ssm_name("runtime_arn"), launch_result.agent_arn)

    if args.wait:
        wait_for_ready(runtime)


def wait_for_ready(runtime: Runtime) -> None:
    end_status = {"READY", "CREATE_FAILED", "DELETE_FAILED", "UPDATE_FAILED"}
    status_response = runtime.status()
    status = status_response.endpoint["status"]
    while status not in end_status:
        print(f"Waiting for deployment... Current status: {status}")
        time.sleep(10)
        status_response = runtime.status()
        status = status_response.endpoint["status"]
    print(f"Final status: {status}")


def invoke_runtime(args: argparse.Namespace) -> None:
    runtime = Runtime()
    bearer_token = args.bearer_token or get_ssm_parameter(_ssm_name("bearer_token"))
    if not bearer_token:
        raise RuntimeError("Missing bearer token. Set --bearer-token or store in SSM.")

    payload = {"prompt": args.prompt}
    response = runtime.invoke(payload, bearer_token=bearer_token, session_id=args.session_id)
    print(json.dumps(response, indent=2))


def status_runtime(args: argparse.Namespace) -> None:
    runtime = Runtime()
    status_response = runtime.status()
    print(json.dumps(status_response, indent=2, default=str))


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deploy AgentCore Runtime for Poke Platform")
    parser.add_argument("--region", default=boto3.session.Session().region_name)
    parser.add_argument("--agent-name", default="pokemon_trader_agent")
    parser.add_argument("--workspace", default=".agentcore_runtime_build")

    subparsers = parser.add_subparsers(dest="command", required=True)

    configure = subparsers.add_parser("configure", help="Configure AgentCore Runtime deployment")
    configure.add_argument("--no-auth", action="store_true", help="Skip Cognito authorizer setup")
    configure.add_argument("--refresh-token", action="store_true", help="Refresh Cognito access token")
    configure.set_defaults(func=configure_runtime)

    launch = subparsers.add_parser("launch", help="Launch AgentCore Runtime deployment")
    launch.add_argument("--env", action="append", default=[], help="Runtime env var KEY=VALUE")
    launch.add_argument("--auto-update", action="store_true", help="Auto-update on conflict")
    launch.add_argument("--wait", action="store_true", help="Wait for READY status")
    launch.set_defaults(func=launch_runtime)

    status = subparsers.add_parser("status", help="Get AgentCore Runtime status")
    status.set_defaults(func=status_runtime)

    invoke = subparsers.add_parser("invoke", help="Invoke AgentCore Runtime")
    invoke.add_argument("--prompt", required=True)
    invoke.add_argument("--session-id", default=None)
    invoke.add_argument("--bearer-token", default=None)
    invoke.set_defaults(func=invoke_runtime)

    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if not args.region:
        print("AWS region not configured. Set AWS_REGION or AWS_DEFAULT_REGION.")
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
