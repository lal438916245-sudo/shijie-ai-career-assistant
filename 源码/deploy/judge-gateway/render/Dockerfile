FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
COPY judge_gateway.py judge_ledger.py start_render.py policy.json previous-policy.json /app/
USER app
EXPOSE 10000
CMD ["python", "start_render.py"]
