FROM python:3.13-slim
WORKDIR /app
COPY ["源码/deploy/judge-gateway/render/requirements.txt", "./"]
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app
COPY ["源码/deploy/judge-gateway/render/judge_gateway.py", "源码/deploy/judge-gateway/render/judge_ledger.py", "源码/deploy/judge-gateway/render/start_render.py", "源码/deploy/judge-gateway/render/policy.json", "源码/deploy/judge-gateway/render/previous-policy.json", "/app/"]
USER app
EXPOSE 10000
CMD ["python", "start_render.py"]
