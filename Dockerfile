# Open Palm Detection Add-on for Home Assistant
# Supports IR/low-light camera streams
# Using Debian base for MediaPipe compatibility

ARG BUILD_FROM
FROM ${BUILD_FROM}

# Set shell
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /app

# Upgrade pip first
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel

# Install compatible versions - protobuf must be compatible with mediapipe
RUN pip3 install --no-cache-dir \
    "numpy>=1.24.0,<2.0.0" \
    "protobuf>=3.20,<5" \
    "opencv-python-headless>=4.8.0" \
    "paho-mqtt>=2.0.0"

# Install MediaPipe separately with specific version known to work
RUN pip3 install --no-cache-dir mediapipe==0.10.9 || \
    pip3 install --no-cache-dir mediapipe==0.10.8 || \
    pip3 install --no-cache-dir mediapipe==0.10.7 || \
    pip3 install --no-cache-dir mediapipe

# Debug: Show what's installed
RUN pip3 list | grep -i -E "(mediapipe|protobuf|numpy|opencv)"

# Verify mediapipe installation works
RUN python3 -c "\
import sys; \
print('Python:', sys.version); \
import mediapipe; \
print('MediaPipe location:', mediapipe.__file__); \
print('MediaPipe version:', mediapipe.__version__); \
from mediapipe.python.solutions import hands; \
print('Hands module loaded successfully'); \
"

# Copy application files
COPY detect_hand.py /app/
COPY run.sh /app/

# Make run script executable
RUN chmod +x /app/run.sh

# Set entrypoint
ENTRYPOINT ["/app/run.sh"]
