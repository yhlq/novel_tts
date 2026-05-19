# novel_tts — 小说多角色语音合成
# GPU 镜像（推荐）：需 NVIDIA Container Toolkit
# 构建: docker build -t novel-tts .
# 运行: docker compose up -d

ARG PYTHON_VERSION=3.12
ARG CUDA_IMAGE=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

FROM ${CUDA_IMAGE} AS runtime

LABEL maintainer="novel_tts"
LABEL description="Novel multi-character TTS (Qwen3-TTS + FastAPI)"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/huggingface \
    TRANSFORMERS_CACHE=/models/huggingface \
    APP_HOME=/app \
    PORT=7860

WORKDIR ${APP_HOME}

# 系统依赖：音频处理、sox（qwen-tts 可选依赖）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    sox \
    libsox-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

# 安装 Qwen3-TTS（项目内 vendored 副本）
COPY bk/qwen3-tts-usages/Qwen3-TTS /tmp/Qwen3-TTS
RUN pip install -e /tmp/Qwen3-TTS \
    && rm -rf /tmp/Qwen3-TTS/.git

# 应用代码
COPY main.py config.docker.json ./
COPY src/ ./src/
COPY static/ ./static/
COPY docs/novel_example.txt ./novel_example.txt

# 容器内默认使用 docker 配置（HuggingFace 模型 ID + 挂载目录）
RUN cp config.docker.json config.json

# 运行时目录（可通过 volume 持久化）
RUN mkdir -p \
    logs \
    static/audio \
    static/uploads \
    static/voice_prompts \
    static/voice_anchors \
    models

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f "http://127.0.0.1:${PORT}/api/config" || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
