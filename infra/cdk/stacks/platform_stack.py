from constructs import Construct
from aws_cdk import (
    Stack,
    CfnOutput,
    Duration,
    aws_ec2 as ec2,
    aws_ecr as ecr,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_elasticloadbalancingv2 as elbv2,
    aws_events as events,
    aws_iam as iam,
    aws_logs as logs,
    aws_rds as rds,
    aws_secretsmanager as secretsmanager,
)

class PlatformStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(self, "Vpc", max_azs=2)
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        api_repo = ecr.Repository(self, "ApiRepo", repository_name="poke-api")
        ui_repo = ecr.Repository(self, "UiRepo", repository_name="poke-ui")
        proposal_repo = ecr.Repository(
            self, "ProposalGeneratorRepo", repository_name="poke-proposal-generator"
        )
        strategy_repo = ecr.Repository(
            self, "StrategyRunnerRepo", repository_name="poke-strategy-runner"
        )
        universe_repo = ecr.Repository(
            self, "UniverseUpdaterRepo", repository_name="poke-universe-updater"
        )
        price_repo = ecr.Repository(
            self, "PriceExtractorRepo", repository_name="poke-price-extractor"
        )

        # Postgres (RDS)
        db = rds.DatabaseInstance(
            self,
            "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_15_12
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            credentials=rds.Credentials.from_generated_secret("pokeadmin"),
            database_name="poke",
            allocated_storage=20,
            max_allocated_storage=100,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.MICRO),
            multi_az=False,
            publicly_accessible=False,
            deletion_protection=False,
        )

        # UI service + public ALB
        ui_log_group = logs.LogGroup(
            self,
            "UiLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        ui_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "UiService",
            cluster=cluster,
            public_load_balancer=True,
            desired_count=1,
            cpu=512,
            memory_limit_mib=1024,
            listener_port=80,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_ecr_repository(ui_repo, tag="latest"),
                container_port=8501,
                environment={"API_BASE": "http://localhost"},
                log_driver=ecs.LogDrivers.aws_logs(
                    stream_prefix="ui",
                    log_group=ui_log_group,
                ),
            ),
            health_check_grace_period=Duration.seconds(60),
        )

        # API service (behind same ALB via /api/*)
        api_task_def = ecs.FargateTaskDefinition(
            self, "ApiTaskDef", cpu=512, memory_limit_mib=1024
        )
        api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )

        api_task_def.add_container(
            "ApiContainer",
            image=ecs.ContainerImage.from_ecr_repository(api_repo, tag="latest"),
            port_mappings=[ecs.PortMapping(container_port=8000)],
            environment={
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "poke",
                "DB_USER": "pokeadmin",
            },
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, field="password"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="api",
                log_group=api_log_group,
            ),
        )

        api_service = ecs.FargateService(
            self,
            "ApiService",
            cluster=cluster,
            task_definition=api_task_def,
            desired_count=1,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            enable_execute_command=True,
        )

        proposal_log_group = logs.LogGroup(
            self,
            "ProposalGeneratorLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        proposal_task_def = ecs.FargateTaskDefinition(
            self, "ProposalGeneratorTaskDef", cpu=512, memory_limit_mib=1024
        )
        proposal_task_def.add_container(
            "ProposalGeneratorContainer",
            image=ecs.ContainerImage.from_ecr_repository(proposal_repo, tag="latest"),
            environment={
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "poke",
                "DB_USER": "pokeadmin",
            },
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, field="password"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="proposal-generator",
                log_group=proposal_log_group,
            ),
        )
        proposal_sg = ec2.SecurityGroup(
            self,
            "ProposalGeneratorSecurityGroup",
            vpc=vpc,
            description="Security group for proposal generator tasks",
        )
        strategy_log_group = logs.LogGroup(
            self,
            "StrategyRunnerLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        strategy_task_def = ecs.FargateTaskDefinition(
            self, "StrategyRunnerTaskDef", cpu=512, memory_limit_mib=1024
        )
        strategy_task_def.add_container(
            "StrategyRunnerContainer",
            image=ecs.ContainerImage.from_ecr_repository(strategy_repo, tag="latest"),
            environment={
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "poke",
                "DB_USER": "pokeadmin",
                "STRATEGY_NAME": "exp_smoothing_v1",
                "STRATEGY_VERSION": "v1",
            },
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, field="password"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="strategy-runner",
                log_group=strategy_log_group,
            ),
        )
        strategy_sg = ec2.SecurityGroup(
            self,
            "StrategyRunnerSecurityGroup",
            vpc=vpc,
            description="Security group for strategy runner tasks",
        )
        universe_log_group = logs.LogGroup(
            self,
            "UniverseUpdaterLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        universe_task_def = ecs.FargateTaskDefinition(
            self, "UniverseUpdaterTaskDef", cpu=512, memory_limit_mib=1024
        )
        ptcg_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "PtcgApiKey", "ptcg/api_key"
        )
        universe_task_def.add_container(
            "UniverseUpdaterContainer",
            image=ecs.ContainerImage.from_ecr_repository(universe_repo, tag="latest"),
            environment={
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "poke",
                "DB_USER": "pokeadmin",
            },
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, field="password"),
                "PTCG_API_KEY": ecs.Secret.from_secrets_manager(ptcg_secret),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="universe-updater",
                log_group=universe_log_group,
            ),
        )
        universe_sg = ec2.SecurityGroup(
            self,
            "UniverseUpdaterSecurityGroup",
            vpc=vpc,
            description="Security group for universe updater tasks",
        )
        price_log_group = logs.LogGroup(
            self,
            "PriceExtractorLogGroup",
            retention=logs.RetentionDays.ONE_WEEK,
        )
        price_task_def = ecs.FargateTaskDefinition(
            self, "PriceExtractorTaskDef", cpu=512, memory_limit_mib=1024
        )
        price_task_def.add_container(
            "PriceExtractorContainer",
            image=ecs.ContainerImage.from_ecr_repository(price_repo, tag="latest"),
            environment={
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "poke",
                "DB_USER": "pokeadmin",
            },
            secrets={
                "DB_PASSWORD": ecs.Secret.from_secrets_manager(db.secret, field="password"),
            },
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="price-extractor",
                log_group=price_log_group,
            ),
        )
        price_sg = ec2.SecurityGroup(
            self,
            "PriceExtractorSecurityGroup",
            vpc=vpc,
            description="Security group for price extractor tasks",
        )

        # Networking rules
        db.connections.allow_default_port_from(api_service, "API to Postgres")
        db.connections.allow_default_port_from(
            proposal_sg, "Proposal generator to Postgres"
        )
        db.connections.allow_default_port_from(
            strategy_sg, "Strategy runner to Postgres"
        )
        db.connections.allow_default_port_from(
            universe_sg, "Universe updater to Postgres"
        )
        db.connections.allow_default_port_from(
            price_sg, "Price extractor to Postgres"
        )
        api_service.connections.allow_from(
            ui_service.load_balancer, ec2.Port.tcp(8000), "ALB to API"
        )

        # Path routing /api/* -> API
        ui_service.listener.add_targets(
            "ApiTargets",
            port=8000,
            targets=[api_service],
            health_check=elbv2.HealthCheck(
                path="/api/health",
                healthy_http_codes="200",
                interval=Duration.seconds(30),
            ),
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*"])],
        )

        alb_dns = ui_service.load_balancer.load_balancer_dns_name
        ui_service.task_definition.default_container.add_environment(
            "API_BASE", f"http://{alb_dns}"
        )

        proposal_rule_role = iam.Role(
            self,
            "ProposalGeneratorRuleRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        proposal_rule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[proposal_task_def.task_definition_arn],
                conditions={"ArnLike": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        proposal_pass_role_arns = []
        if proposal_task_def.execution_role:
            proposal_pass_role_arns.append(proposal_task_def.execution_role.role_arn)
        if proposal_task_def.task_role:
            proposal_pass_role_arns.append(proposal_task_def.task_role.role_arn)
        if proposal_pass_role_arns:
            proposal_rule_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=proposal_pass_role_arns,
                )
            )

        proposal_subnets = vpc.select_subnets(
            subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
        )
        events.CfnRule(
            self,
            "ProposalGeneratorDailyRule",
            # EventBridge Rules use UTC; 13:00 UTC == 08:00 America/New_York (standard time).
            schedule_expression="cron(0 13 * * ? *)",
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    arn=cluster.cluster_arn,
                    id="ProposalGeneratorEcsTarget",
                    role_arn=proposal_rule_role.role_arn,
                    ecs_parameters=events.CfnRule.EcsParametersProperty(
                        task_definition_arn=proposal_task_def.task_definition_arn,
                        task_count=1,
                        launch_type="FARGATE",
                        network_configuration=events.CfnRule.NetworkConfigurationProperty(
                            aws_vpc_configuration=events.CfnRule.AwsVpcConfigurationProperty(
                                subnets=proposal_subnets.subnet_ids,
                                security_groups=[proposal_sg.security_group_id],
                                assign_public_ip="DISABLED",
                            )
                        ),
                    ),
                )
            ],
        )
        strategy_rule_role = iam.Role(
            self,
            "StrategyRunnerRuleRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        strategy_rule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[strategy_task_def.task_definition_arn],
                conditions={"ArnLike": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        strategy_pass_role_arns = []
        if strategy_task_def.execution_role:
            strategy_pass_role_arns.append(strategy_task_def.execution_role.role_arn)
        if strategy_task_def.task_role:
            strategy_pass_role_arns.append(strategy_task_def.task_role.role_arn)
        if strategy_pass_role_arns:
            strategy_rule_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=strategy_pass_role_arns,
                )
            )

        events.CfnRule(
            self,
            "StrategyRunnerDailyRule",
            # EventBridge Rules use UTC; 13:05 UTC == 08:05 America/New_York (standard time).
            schedule_expression="cron(5 13 * * ? *)",
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    arn=cluster.cluster_arn,
                    id="StrategyRunnerEcsTarget",
                    role_arn=strategy_rule_role.role_arn,
                    ecs_parameters=events.CfnRule.EcsParametersProperty(
                        task_definition_arn=strategy_task_def.task_definition_arn,
                        task_count=1,
                        launch_type="FARGATE",
                        network_configuration=events.CfnRule.NetworkConfigurationProperty(
                            aws_vpc_configuration=events.CfnRule.AwsVpcConfigurationProperty(
                                subnets=proposal_subnets.subnet_ids,
                                security_groups=[strategy_sg.security_group_id],
                                assign_public_ip="DISABLED",
                            )
                        ),
                    ),
                )
            ],
        )
        universe_rule_role = iam.Role(
            self,
            "UniverseUpdaterRuleRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        universe_rule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[universe_task_def.task_definition_arn],
                conditions={"ArnLike": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        universe_pass_role_arns = []
        if universe_task_def.execution_role:
            universe_pass_role_arns.append(universe_task_def.execution_role.role_arn)
        if universe_task_def.task_role:
            universe_pass_role_arns.append(universe_task_def.task_role.role_arn)
        if universe_pass_role_arns:
            universe_rule_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=universe_pass_role_arns,
                )
            )

        events.CfnRule(
            self,
            "UniverseUpdaterDailyRule",
            # EventBridge Rules use UTC; 12:55 UTC == 07:55 America/New_York (standard time).
            schedule_expression="cron(55 12 * * ? *)",
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    arn=cluster.cluster_arn,
                    id="UniverseUpdaterEcsTarget",
                    role_arn=universe_rule_role.role_arn,
                    ecs_parameters=events.CfnRule.EcsParametersProperty(
                        task_definition_arn=universe_task_def.task_definition_arn,
                        task_count=1,
                        launch_type="FARGATE",
                        network_configuration=events.CfnRule.NetworkConfigurationProperty(
                            aws_vpc_configuration=events.CfnRule.AwsVpcConfigurationProperty(
                                subnets=proposal_subnets.subnet_ids,
                                security_groups=[universe_sg.security_group_id],
                                assign_public_ip="DISABLED",
                            )
                        ),
                    ),
                )
            ],
        )
        price_rule_role = iam.Role(
            self,
            "PriceExtractorRuleRole",
            assumed_by=iam.ServicePrincipal("events.amazonaws.com"),
        )
        price_rule_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:RunTask"],
                resources=[price_task_def.task_definition_arn],
                conditions={"ArnLike": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        price_pass_role_arns = []
        if price_task_def.execution_role:
            price_pass_role_arns.append(price_task_def.execution_role.role_arn)
        if price_task_def.task_role:
            price_pass_role_arns.append(price_task_def.task_role.role_arn)
        if price_pass_role_arns:
            price_rule_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["iam:PassRole"],
                    resources=price_pass_role_arns,
                )
            )

        events.CfnRule(
            self,
            "PriceExtractorDailyRule",
            # EventBridge Rules use UTC; 13:00 UTC == 08:00 America/New_York (standard time).
            schedule_expression="cron(0 13 * * ? *)",
            state="ENABLED",
            targets=[
                events.CfnRule.TargetProperty(
                    arn=cluster.cluster_arn,
                    id="PriceExtractorEcsTarget",
                    role_arn=price_rule_role.role_arn,
                    ecs_parameters=events.CfnRule.EcsParametersProperty(
                        task_definition_arn=price_task_def.task_definition_arn,
                        task_count=1,
                        launch_type="FARGATE",
                        network_configuration=events.CfnRule.NetworkConfigurationProperty(
                            aws_vpc_configuration=events.CfnRule.AwsVpcConfigurationProperty(
                                subnets=proposal_subnets.subnet_ids,
                                security_groups=[price_sg.security_group_id],
                                assign_public_ip="DISABLED",
                            )
                        ),
                    ),
                )
            ],
        )

        CfnOutput(self, "AlbUrl", value=f"http://{alb_dns}")
        CfnOutput(self, "ApiRepoUri", value=api_repo.repository_uri)
        CfnOutput(self, "UiRepoUri", value=ui_repo.repository_uri)
        CfnOutput(self, "UniverseUpdaterRepoUri", value=universe_repo.repository_uri)
        CfnOutput(self, "PriceExtractorRepoUri", value=price_repo.repository_uri)
        CfnOutput(self, "DbEndpoint", value=db.db_instance_endpoint_address)
