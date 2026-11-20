FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
COPY judge_gateway.py judge_ledger.py /app/
COPY policy.json /app/policy.json
USER app
EXPOSE 8080
CMD ["python", "judge_gateway.py", "--policy", "/app/policy.json", "--ledger", "/data/gateway.db", "--host", "0.0.0.0", "--port", "8080"]
