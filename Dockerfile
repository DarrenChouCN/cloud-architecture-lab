FROM python:3.10-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
ENV MODEL_DIR=/app/models
ENV MODEL_PT_PATH=/app/models/model.pt
ENV MD_MODEL_PATH=/app/models/mdv5a.pt

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libglib2.0-0 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel

RUN pip install --no-cache-dir \
    torch torchvision \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY src/ ./src/

RUN mkdir -p /app/models /app/outputs

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]