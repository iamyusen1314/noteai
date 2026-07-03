FROM python:3.11-slim

WORKDIR /app

# 系统依赖（OpenCV 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# 依赖先复制（利用 Docker 缓存）
COPY model/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

# 复制代码
COPY model/ ./model/
COPY scripts/docker_entrypoint.sh ./scripts/docker_entrypoint.sh
COPY NoteAI_Pro_Demo_Framer.html ./NoteAI_Pro_Demo_Framer.html

WORKDIR /app/model

# 数据目录（持久化挂载点）
RUN mkdir -p data
RUN chmod +x /app/scripts/docker_entrypoint.sh

ENV PORT=8000
EXPOSE 8000

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
