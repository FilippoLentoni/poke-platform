FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY agents /app/agents
COPY observability /app/observability

EXPOSE 8000
CMD ["python", "-m", "agents.orchestration_agent.agent"]
