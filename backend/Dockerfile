FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./
COPY run_two_lane_job.py ./
COPY run_pdf_scan_cpu_job.py ./
COPY run_pdf_scan_gpu_job.py ./
COPY run_pdf_scan_pipeline.py ./
COPY run_pdf_scan_gpu_pipeline.py ./
COPY middleware ./middleware
COPY models ./models
COPY pdf_scan_runtime ./pdf_scan_runtime
COPY services ./services
COPY utils ./utils

EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
