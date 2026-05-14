# AIBO Studio v8.0 - RunPod Serverless Image
FROM runpod/pytorch:2.1.1-py3.10-cuda12.1.1-devel-ubuntu22.04

# 環境変数
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV CUDA_VISIBLE_DEVICES=0

# 必須パッケージ
RUN apt-get update && apt-get install -y \
    git wget curl ffmpeg libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

# 作業ディレクトリ
WORKDIR /workspace

# Python 依存関係
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# AIBO Studio コア
COPY 01_config.py .
COPY 02_colab_setup.py .
COPY 03_identity_engine.py .
COPY 02_aibo_v7_main.py .
COPY 04_pipeline_manager.py .
COPY pipeline_manager.py .

# RunPod handler
COPY handler.py .

# モデル重みは Network Volume にマウント (/runpod-volume/models/)
ENV MODEL_PATH=/runpod-volume/models

# RunPod エントリポイント
CMD ["python", "-u", "handler.py"]
