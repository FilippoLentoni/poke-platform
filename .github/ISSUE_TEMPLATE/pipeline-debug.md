---
name: Pipeline Not Running
about: Debug checklist for daily pipeline issues
title: "[Pipeline] Not running"
labels: bug, ops
---

## Checklist
- [ ] Stack exists (`aws cloudformation describe-stacks --stack-name PokePlatformStack`)
- [ ] EventBridge rules enabled (`scripts/verify_pipeline.sh`)
- [ ] Rule Invocations/FailedInvocations checked (`scripts/verify_pipeline.sh` or `scripts/debug_eventbridge_ecs.sh`)
- [ ] ECS tasks created / exit codes captured (`aws ecs list-tasks` + `aws ecs describe-tasks`)
- [ ] Manual run attempted (`scripts/run_task_manual.sh <task>`)
- [ ] DB checks run (`psql -f scripts/db_checks.sql`)
- [ ] Logs inspected (`scripts/tail_logs.sh <component>`)

## Notes
Describe what you observed (errors, exit codes, timestamps, regions, stack name).
