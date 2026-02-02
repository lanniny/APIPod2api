FROM python:3.11-slim

WORKDIR /app

COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

COPY gateway_server.py pool_manager.py ./
COPY static/ ./static/

# 数据目录（可通过 DATA_DIR 环境变量覆盖）
RUN mkdir -p /app/data

EXPOSE 9000

# 设置默认数据目录
ENV DATA_DIR=/app/data

CMD ["python", "gateway_server.py", "--host", "0.0.0.0"]
