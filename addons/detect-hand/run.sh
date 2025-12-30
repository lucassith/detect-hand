#!/usr/bin/with-contenv bashio
# ==============================================================================
# Open Palm Detection Add-on
# Starts the palm detection service with configuration from Home Assistant
# ==============================================================================

set -e

# Read configuration from Home Assistant
CONFIG_PATH="/data/options.json"

# Log startup
bashio::log.info "Starting Open Palm Detection Add-on..."
bashio::log.info "Reading configuration from ${CONFIG_PATH}"

# Export configuration as environment variables for Python script
export RTSP_URL=$(bashio::config 'rtsp_url')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USERNAME=$(bashio::config 'mqtt_username')
export MQTT_PASSWORD=$(bashio::config 'mqtt_password')
export MQTT_TOPIC=$(bashio::config 'mqtt_topic')

export DETECTION_DURATION_SECONDS=$(bashio::config 'detection_duration_seconds')
export DETECTION_THRESHOLD_PERCENT=$(bashio::config 'detection_threshold_percent')
export COOLDOWN_SECONDS=$(bashio::config 'cooldown_seconds')
export CONFIDENCE_THRESHOLD=$(bashio::config 'confidence_threshold')

export FRAME_SKIP=$(bashio::config 'frame_skip')
export MAX_FRAME_WIDTH=$(bashio::config 'max_frame_width')
export PROCESSING_FPS=$(bashio::config 'processing_fps')

export IR_MODE_ENABLED=$(bashio::config 'ir_mode_enabled')
export CLAHE_CLIP_LIMIT=$(bashio::config 'clahe_clip_limit')
export CLAHE_GRID_SIZE=$(bashio::config 'clahe_grid_size')
export BRIGHTNESS_BOOST=$(bashio::config 'brightness_boost')
export CONTRAST_BOOST=$(bashio::config 'contrast_boost')

export LOG_LEVEL=$(bashio::config 'log_level')
export LOG_DETECTION_EVENTS=$(bashio::config 'log_detection_events')
export LOG_FRAME_STATS=$(bashio::config 'log_frame_stats')

export RTSP_RECONNECT_DELAY_SECONDS=$(bashio::config 'rtsp_reconnect_delay_seconds')
export RTSP_MAX_RECONNECT_ATTEMPTS=$(bashio::config 'rtsp_max_reconnect_attempts')
export MQTT_RECONNECT_DELAY_SECONDS=$(bashio::config 'mqtt_reconnect_delay_seconds')

bashio::log.info "Configuration loaded successfully"
bashio::log.info "RTSP URL: ${RTSP_URL%%@*}@[REDACTED]"
bashio::log.info "MQTT Host: ${MQTT_HOST}:${MQTT_PORT}"
bashio::log.info "MQTT Topic: ${MQTT_TOPIC}"
bashio::log.info "Detection Duration: ${DETECTION_DURATION_SECONDS}s"
bashio::log.info "Detection Threshold: ${DETECTION_THRESHOLD_PERCENT}%"
bashio::log.info "Cooldown: ${COOLDOWN_SECONDS}s"
bashio::log.info "IR Mode: ${IR_MODE_ENABLED}"
bashio::log.info "Log Level: ${LOG_LEVEL}"

# Start the Python detection script
bashio::log.info "Starting palm detection service..."
exec python3 /app/detect_hand.py
