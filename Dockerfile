FROM python:3.11-slim

WORKDIR /app

COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

COPY gateway_server.py pool_manager.py ./
COPY static/ ./static/

EXPOSE 9000

CMD ["python", "gateway_server.py", "--host", "0.0.0.0"]
