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

# Install Python dependencies
RUN pip3 install --no-cache-dir \
    "numpy>=1.24.0,<2.0.0" \
    "opencv-python-headless>=4.8.0" \
    "paho-mqtt>=2.0.0" \
    "ultralytics>=8.0.0"

# Debug: Show what's installed
RUN pip3 list | grep -i -E "(ultralytics|numpy|opencv|torch)"

# Verify YOLOv8 installation
RUN python3 -c "\
from ultralytics import YOLO; \
print('YOLOv8 imported successfully'); \
"

# Copy application files
COPY detect_hand.py /app/
COPY run.sh /app/

# Make run script executable
RUN chmod +x /app/run.sh

# Set entrypoint
ENTRYPOINT ["/app/run.sh"]
