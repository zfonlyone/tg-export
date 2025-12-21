FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖 (tgcrypto ARM64 编译需要完整的 C 开发环境)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libc-dev \
    libffi-dev \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip
RUN pip install --upgrade pip setuptools wheel

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/app ./app

# 创建数据目录
RUN mkdir -p /app/data/exports /app/data/sessions

# 环境变量
ENV PYTHONPATH=/app
ENV DATA_DIR=/app/data
ENV EXPORT_DIR=/app/data/exports
ENV SESSIONS_DIR=/app/data/sessions

EXPOSE 9528

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9528"]
