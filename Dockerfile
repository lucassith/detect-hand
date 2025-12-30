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

# Install system dependencies (minimal - let pip handle Python packages)
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

# Install Python dependencies one by one to avoid conflicts
# Install numpy first (required by others)
RUN pip3 install --no-cache-dir "numpy>=1.24.0,<2.0.0"

# Install OpenCV (headless version for smaller size)
RUN pip3 install --no-cache-dir opencv-python-headless>=4.8.0

# Install MediaPipe (must be after numpy and opencv)
RUN pip3 install --no-cache-dir mediapipe>=0.10.0

# Install MQTT client
RUN pip3 install --no-cache-dir paho-mqtt>=2.0.0

# Verify mediapipe installation
RUN python3 -c "import mediapipe as mp; print('MediaPipe version:', mp.__version__); print('Solutions:', hasattr(mp, 'solutions'))"

# Copy application files
COPY detect_hand.py /app/
COPY run.sh /app/

# Make run script executable
RUN chmod +x /app/run.sh

# Set entrypoint
ENTRYPOINT ["/app/run.sh"]
