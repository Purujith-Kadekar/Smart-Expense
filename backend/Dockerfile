# Backend — Flask API + local OCR + the ingestion Lambda handler.
#
# Build context is the project root, so both backend/ and lambda/ can be
# copied in.
#
# The OCR_ENGINE build arg picks the engine and therefore the image size:
#
#   --build-arg OCR_ENGINE=easyocr    ~2 GB   default, more accurate
#   --build-arg OCR_ENGINE=tesseract  ~350 MB faster build, good enough
#                                             for clean printed receipts
FROM python:3.11-slim

ARG OCR_ENGINE=easyocr
ENV OCR_ENGINE=${OCR_ENGINE}

# Where EasyOCR weights live. Baked in at build time so the running
# container never needs network access.
ENV EASYOCR_MODULE_PATH=/opt/easyocr

# System packages:
#   tesseract-ocr           the OCR binary (pytesseract is only a wrapper)
#   libglib2.0-0, libgl1    OpenCV runtime libs that EasyOCR links against;
#                           without them `import easyocr` dies with
#                           "libGL.so.1: cannot open shared object file"
#   curl                    used by the compose healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        libglib2.0-0 \
        libgl1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Flask deps first — this layer is cached across OCR rebuilds.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# OCR deps. Pillow and pytesseract are cheap, so install them either way;
# EasyOCR plus CPU-only torch is the expensive branch.
RUN pip install --no-cache-dir Pillow==10.4.0 pytesseract==0.3.13 && \
    if [ "$OCR_ENGINE" = "easyocr" ]; then \
        pip install --no-cache-dir \
            --index-url https://download.pytorch.org/whl/cpu \
            torch==2.4.1 torchvision==0.19.1 && \
        pip install --no-cache-dir easyocr==1.7.2 ; \
    fi

# Pre-download the EasyOCR weights (~100 MB) into the image. This is the
# ONLY step that needs the network, and it happens at build time — so the
# container runs fully offline, which is the whole point of the local-first
# constraint.
RUN if [ "$OCR_ENGINE" = "easyocr" ]; then \
        mkdir -p "$EASYOCR_MODULE_PATH/model" "$EASYOCR_MODULE_PATH/user_network" && \
        python -c "import easyocr, os; \
easyocr.Reader(['en'], gpu=False, verbose=False, \
    model_storage_directory=os.path.join(os.environ['EASYOCR_MODULE_PATH'], 'model'), \
    user_network_directory=os.path.join(os.environ['EASYOCR_MODULE_PATH'], 'user_network'))" ; \
    fi

COPY backend/ /app/
COPY lambda/ /lambda/

# Both directories importable: the backend imports lambda_function directly
# rather than going through a real Lambda invocation.
ENV PYTHONPATH="/app:/lambda"
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Two workers, 120s timeout. The default 30s timeout kills the worker
# mid-OCR on a large receipt photo, which surfaces as a 502 from nginx.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", \
     "--timeout", "120", "--access-logfile", "-", "app:app"]
