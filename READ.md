# Poke Trader Platform (Human-in-the-Loop)

A human-in-the-loop trading platform for Pokemon cards.  
The platform generates daily BUY/SELL recommendations with explainability, traders approve/reject in a Streamlit UI, and the system tracks portfolio and executions over time.

This repo is designed to scale from:
- Pokemon-only MVP
→ to multi-collectible platform (Rolex, sneakers, etc.)
→ with pluggable strategies (“bring your own buy/sell model”) and benchmarking.

---

## 1) User Experience (Product Spec)

### Daily cadence
**08:00 AM** — Automated pipeline runs:
1) Pull market data (prices/listings/liquidity + card metadata).
2) Run “research agent” to read web sources and convert them into signals (structured or NL brief).
3) Compute features and run strategies (heuristic / ML / AI).
4) Produce today’s proposals (BUY/SELL/HOLD) + explainability report.
5) Persist:
   - raw/clean data to S3
   - proposals and strategy outputs to Postgres

**10:00 AM** — Trader logs into UI:
- sees today’s proposals + explainability
- approves/rejects (and optionally leaves rejection reason)
- asks follow-up questions in a chat panel (grounded on evidence + data)

Post-approval:
- SELL execution creates listings and tracks status
- BUY is assisted/manual initially (link + target price); later automation is optional and venue-dependent
- portfolio value and open listings are tracked over time

---

## 2) Architecture (Current + Target)

### Current (Milestone 2 implemented)
- **Streamlit UI** on ECS Fargate (service)
- **FastAPI API** on ECS Fargate (service)
- **ALB** path routing:
  - `/` → Streamlit UI
  - `/api/*` → FastAPI
- **RDS Postgres** for state (proposals, decisions)
- **ECR** for container images
- **CDK (Python)** to provision infra

### Target (Milestone 3+)
Add scheduled/burst compute:
- **ECS Fargate tasks** for:
  - collectors (prices/meta)
  - research agent (GPT-based signals)
  - feature builder
  - strategy runner (arbitrage)
  - reconciler (executions/portfolio)
- **EventBridge Scheduler** to trigger the 08:00 pipeline
- **Step Functions** optionally to orchestrate multi-step pipeline reliably
- **S3** to store:
  - raw snapshots
  - clean normalized parquet
  - evidence pages
  - strategy artifacts (reports, backtests)

---

## 3) Tech Stack Decisions

### Why ECS/Fargate
- Run always-on services (UI + API) as Fargate services behind ALB.
- Run batch/scheduled pipelines as Fargate tasks (serverless compute).
- EC2 is **dev-only** (remote workstation), never production.

### Why Postgres
- Strong for state: proposals, approvals, portfolio ledger, executions.
- Easy to query and evolve schema.
- Works well with Python/FastAPI.

### Why “signals” should be structured
Even if you keep a natural-language brief:
- strategies should consume **structured signals** for repeatability
- allows benchmarking across strategies (apples-to-apples)
- improves explainability by grounding outputs in facts/metrics

---


