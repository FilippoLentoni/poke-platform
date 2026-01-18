#!/usr/bin/env python3
import os
import aws_cdk as cdk
from stacks.platform_stack import PlatformStack

app = cdk.App()

PlatformStack(
    app,
    "PokePlatformStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region=os.getenv("CDK_DEFAULT_REGION", "us-east-2"),
    ),
)

app.synth()
