# Langfuse (self-hosted)

This wrapper uses the official `langfuse-terraform-aws` module.

## Deploy

```bash
cd infra/langfuse
terraform init
terraform apply --target module.langfuse.aws_route53_zone.zone
```

Delegate the Route53 NS records for `langfuse.poketrader.ai`, then:

```bash
terraform apply
```

If you hit the known EKS/Fargate race condition, run:

```bash
aws eks update-kubeconfig --name langfuse
kubectl --namespace kube-system rollout restart deploy coredns
kubectl --namespace langfuse delete pod langfuse-clickhouse-shard0-{0,1,2} langfuse-zookeeper-{0,1,2}
```

## Outputs you will need

- Base URL: `https://langfuse.poketrader.ai`
- OTEL endpoint: `https://langfuse.poketrader.ai/api/public/otel`

Create API keys in the Langfuse UI and set:

```bash
LANGFUSE_BASE_URL=https://langfuse.poketrader.ai
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
```

For OTEL tracing:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://langfuse.poketrader.ai/api/public/otel
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(public:secret)>
```
