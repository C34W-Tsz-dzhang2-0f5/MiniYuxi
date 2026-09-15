FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data

EXPOSE 8801

# 容器内监听 0.0.0.0；密钥请通过 -e 或 compose 的 environment 注入（切勿写死在镜像里）
CMD ["python", "run.py", "--host", "0.0.0.0", "--no-open"]
