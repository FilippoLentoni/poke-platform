FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY runner.py /app/runner.py
COPY strategies /app/strategies

CMD ["python", "/app/runner.py"]
