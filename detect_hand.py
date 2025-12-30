#!/usr/bin/env python3
"""
Open Palm Detection Add-on for Home Assistant

Detects open palm gestures from RTSP camera stream (including IR/low-light)
and sends MQTT events when palm is shown for configured duration.

Author: Home Assistant Add-on
Version: 1.0.0
"""

import os
import sys
import json
import time
import re
import logging
import signal
from collections import deque
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass
from threading import Thread, Event, Lock

import cv2
import numpy as np
import mediapipe as mp
import paho.mqtt.client as mqtt


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class Config:
    """Configuration loaded from Home Assistant options.json or environment variables."""
    
    # RTSP Configuration
    rtsp_url: str
    
    # MQTT Configuration
    mqtt_host: str
    mqtt_port: int
    mqtt_username: str
    mqtt_password: str
    mqtt_topic: str
    
    # Detection Configuration
    detection_duration_seconds: float
    detection_threshold_percent: int
    cooldown_seconds: float
    confidence_threshold: float
    
    # Performance Configuration
    frame_skip: int
    max_frame_width: int
    processing_fps: int
    
    # IR/Low-Light Configuration
    ir_mode_enabled: bool
    clahe_clip_limit: float
    clahe_grid_size: int
    brightness_boost: float
    contrast_boost: float
    
    # Logging Configuration
    log_level: str
    log_detection_events: bool
    log_frame_stats: bool
    
    # Connection Configuration
    rtsp_reconnect_delay_seconds: int
    rtsp_max_reconnect_attempts: int
    mqtt_reconnect_delay_seconds: int

    @classmethod
    def load(cls) -> 'Config':
        """
        Load configuration from Home Assistant options.json file.
        Falls back to environment variables if file not found.
        """
        options = {}
        options_path = '/data/options.json'
        
        # Try to load from Home Assistant options.json
        if os.path.exists(options_path):
            try:
                with open(options_path, 'r') as f:
                    options = json.load(f)
                print(f"Configuration loaded from {options_path}")
            except Exception as e:
                print(f"Warning: Could not load {options_path}: {e}")
                print("Falling back to environment variables")
        else:
            print(f"Options file not found at {options_path}, using environment variables")
        
        # Helper to get value from options or env with default
        def get_value(key: str, env_key: str, default, value_type=str):
            # First try options.json (keys use underscores)
            if key in options:
                val = options[key]
                # Handle boolean conversion
                if value_type == bool:
                    if isinstance(val, bool):
                        return val
                    return str(val).lower() == 'true'
                return value_type(val)
            
            # Fall back to environment variable
            env_val = os.environ.get(env_key)
            if env_val is not None:
                if value_type == bool:
                    return env_val.lower() == 'true'
                return value_type(env_val)
            
            # Return default
            return default
        
        return cls(
            rtsp_url=get_value('rtsp_url', 'RTSP_URL', ''),
            mqtt_host=get_value('mqtt_host', 'MQTT_HOST', 'core-mosquitto'),
            mqtt_port=get_value('mqtt_port', 'MQTT_PORT', 1883, int),
            mqtt_username=get_value('mqtt_username', 'MQTT_USERNAME', ''),
            mqtt_password=get_value('mqtt_password', 'MQTT_PASSWORD', ''),
            mqtt_topic=get_value('mqtt_topic', 'MQTT_TOPIC', 'home/gesture/detect-hand'),
            detection_duration_seconds=get_value('detection_duration_seconds', 'DETECTION_DURATION_SECONDS', 4.0, float),
            detection_threshold_percent=get_value('detection_threshold_percent', 'DETECTION_THRESHOLD_PERCENT', 80, int),
            cooldown_seconds=get_value('cooldown_seconds', 'COOLDOWN_SECONDS', 5.0, float),
            confidence_threshold=get_value('confidence_threshold', 'CONFIDENCE_THRESHOLD', 0.5, float),
            frame_skip=get_value('frame_skip', 'FRAME_SKIP', 2, int),
            max_frame_width=get_value('max_frame_width', 'MAX_FRAME_WIDTH', 640, int),
            processing_fps=get_value('processing_fps', 'PROCESSING_FPS', 10, int),
            ir_mode_enabled=get_value('ir_mode_enabled', 'IR_MODE_ENABLED', True, bool),
            clahe_clip_limit=get_value('clahe_clip_limit', 'CLAHE_CLIP_LIMIT', 3.0, float),
            clahe_grid_size=get_value('clahe_grid_size', 'CLAHE_GRID_SIZE', 8, int),
            brightness_boost=get_value('brightness_boost', 'BRIGHTNESS_BOOST', 1.2, float),
            contrast_boost=get_value('contrast_boost', 'CONTRAST_BOOST', 1.3, float),
            log_level=get_value('log_level', 'LOG_LEVEL', 'INFO'),
            log_detection_events=get_value('log_detection_events', 'LOG_DETECTION_EVENTS', True, bool),
            log_frame_stats=get_value('log_frame_stats', 'LOG_FRAME_STATS', False, bool),
            rtsp_reconnect_delay_seconds=get_value('rtsp_reconnect_delay_seconds', 'RTSP_RECONNECT_DELAY_SECONDS', 5, int),
            rtsp_max_reconnect_attempts=get_value('rtsp_max_reconnect_attempts', 'RTSP_MAX_RECONNECT_ATTEMPTS', 0, int),
            mqtt_reconnect_delay_seconds=get_value('mqtt_reconnect_delay_seconds', 'MQTT_RECONNECT_DELAY_SECONDS', 5, int),
        )


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(config: Config) -> logging.Logger:
    """Set up logging with the configured level."""
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    
    # Create logger
    logger = logging.getLogger('palm_detection')
    logger.setLevel(log_level)
    
    # Create handler with format
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    
    # Format includes timestamp for debugging
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    
    return logger


# =============================================================================
# Channel Extraction
# =============================================================================

def extract_channel_from_url(rtsp_url: str) -> str:
    """
    Extract channel number from RTSP URL.
    
    Examples:
        rtsp://user:pass@192.168.1.7/ISAPI/Streaming/channels/101 -> "101"
        rtsp://user:pass@192.168.1.7/cam/realmonitor?channel=2 -> "2"
    """
    # Try to match /channels/XXX pattern (Hikvision style)
    match = re.search(r'/channels/(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    # Try to match channel=XXX query parameter
    match = re.search(r'[?&]channel=(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    # Try to match /ch(\d+) pattern
    match = re.search(r'/ch(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    # Default to "unknown" if no pattern matches
    return "unknown"


# =============================================================================
# Image Preprocessing for IR/Low-Light
# =============================================================================

class IRPreprocessor:
    """Preprocessor for IR/low-light camera images."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Create CLAHE object for contrast enhancement
        self.clahe = cv2.createCLAHE(
            clipLimit=config.clahe_clip_limit,
            tileGridSize=(config.clahe_grid_size, config.clahe_grid_size)
        )
        
        self.logger.debug(
            f"IR Preprocessor initialized: CLAHE clip={config.clahe_clip_limit}, "
            f"grid={config.clahe_grid_size}, brightness={config.brightness_boost}, "
            f"contrast={config.contrast_boost}"
        )
    
    def preprocess(self, frame: np.ndarray) -> np.ndarray:
        """
        Preprocess frame for better palm detection in IR/low-light conditions.
        
        Args:
            frame: Input frame (BGR or grayscale)
            
        Returns:
            Preprocessed frame in RGB format (required by MediaPipe)
        """
        # Convert to grayscale if not already
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()
        
        # Apply CLAHE for adaptive contrast enhancement
        enhanced = self.clahe.apply(gray)
        
        # Apply brightness and contrast adjustments
        # Formula: output = contrast * input + brightness_offset
        brightness_offset = int((self.config.brightness_boost - 1.0) * 128)
        enhanced = cv2.convertScaleAbs(
            enhanced, 
            alpha=self.config.contrast_boost, 
            beta=brightness_offset
        )
        
        # Convert back to RGB (MediaPipe requires RGB input)
        rgb = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)
        
        return rgb
    
    def update_clahe(self, clip_limit: float, grid_size: int):
        """Update CLAHE parameters dynamically."""
        self.clahe = cv2.createCLAHE(
            clipLimit=clip_limit,
            tileGridSize=(grid_size, grid_size)
        )
        self.logger.info(f"CLAHE updated: clip={clip_limit}, grid={grid_size}")


# =============================================================================
# Palm Detection
# =============================================================================

class PalmDetector:
    """Detects open palm gestures using MediaPipe."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Initialize MediaPipe Hands
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            min_detection_confidence=config.confidence_threshold,
            min_tracking_confidence=config.confidence_threshold * 0.8,  # Slightly lower for tracking
        )
        
        self.logger.info(
            f"Palm detector initialized: confidence={config.confidence_threshold}, "
            f"tracking={config.confidence_threshold * 0.8:.2f}"
        )
    
    def detect_open_palm(self, frame_rgb: np.ndarray) -> Tuple[bool, float, int]:
        """
        Detect if an open palm is visible in the frame.
        
        An open palm is detected when:
        1. A hand is detected
        2. All fingers are extended (fingertips above knuckles)
        
        Args:
            frame_rgb: RGB frame
            
        Returns:
            Tuple of (is_open_palm, confidence, num_hands)
        """
        results = self.hands.process(frame_rgb)
        
        if not results.multi_hand_landmarks:
            return False, 0.0, 0
        
        num_hands = len(results.multi_hand_landmarks)
        
        for hand_idx, hand_landmarks in enumerate(results.multi_hand_landmarks):
            # Get handedness info if available
            if results.multi_handedness:
                hand_info = results.multi_handedness[hand_idx]
                hand_label = hand_info.classification[0].label
                confidence = hand_info.classification[0].score
            else:
                hand_label = "Unknown"
                confidence = 0.5
            
            # Check if palm is open (all fingers extended)
            if self._is_palm_open(hand_landmarks):
                self.logger.debug(
                    f"Open palm detected: hand={hand_label}, confidence={confidence:.2f}"
                )
                return True, confidence, num_hands
        
        return False, 0.0, num_hands
    
    def _is_palm_open(self, hand_landmarks) -> bool:
        """
        Determine if the palm is open based on finger positions.
        
        For an open palm:
        - All finger tips should be extended (above their respective PIP joints)
        - Thumb tip should be away from the palm
        
        Landmark indices:
        - Thumb: 1-4 (CMC, MCP, IP, TIP)
        - Index: 5-8 (MCP, PIP, DIP, TIP)
        - Middle: 9-12
        - Ring: 13-16
        - Pinky: 17-20
        - Wrist: 0
        """
        landmarks = hand_landmarks.landmark
        
        # Finger tip and PIP (or IP for thumb) indices
        finger_tips = [8, 12, 16, 20]  # Index, Middle, Ring, Pinky tips
        finger_pips = [6, 10, 14, 18]  # Corresponding PIP joints
        
        extended_count = 0
        
        # Check each finger (except thumb)
        for tip_idx, pip_idx in zip(finger_tips, finger_pips):
            tip = landmarks[tip_idx]
            pip = landmarks[pip_idx]
            
            # Finger is extended if tip is above (lower y value) PIP joint
            # Note: In image coordinates, y increases downward
            if tip.y < pip.y:
                extended_count += 1
        
        # Check thumb separately
        # Thumb is extended if tip is away from palm center
        thumb_tip = landmarks[4]
        thumb_ip = landmarks[3]
        thumb_mcp = landmarks[2]
        
        # For thumb, check if it's extended outward
        # Compare x distance from MCP to TIP vs MCP to IP
        thumb_extended = abs(thumb_tip.x - thumb_mcp.x) > abs(thumb_ip.x - thumb_mcp.x) * 0.8
        
        if thumb_extended:
            extended_count += 1
        
        # Palm is considered open if at least 4 fingers are extended
        is_open = extended_count >= 4
        
        self.logger.debug(
            f"Finger check: {extended_count}/5 extended, thumb_extended={thumb_extended}, "
            f"is_open={is_open}"
        )
        
        return is_open
    
    def close(self):
        """Release MediaPipe resources."""
        self.hands.close()
        self.logger.debug("Palm detector closed")


# =============================================================================
# Detection Window Tracker
# =============================================================================

class DetectionWindow:
    """
    Tracks palm detections over a sliding time window.
    
    Determines if palm has been visible for the required duration
    with the required detection threshold.
    """
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Store timestamps of positive detections
        self.detections: deque = deque()
        
        # Cooldown tracking
        self.last_event_time: Optional[datetime] = None
        
        # Lock for thread safety
        self.lock = Lock()
        
        self.logger.debug(
            f"Detection window initialized: duration={config.detection_duration_seconds}s, "
            f"threshold={config.detection_threshold_percent}%, "
            f"cooldown={config.cooldown_seconds}s"
        )
    
    def add_detection(self, detected: bool, timestamp: Optional[datetime] = None) -> bool:
        """
        Add a detection result and check if event should be triggered.
        
        Args:
            detected: Whether palm was detected in this frame
            timestamp: Detection timestamp (uses current time if None)
            
        Returns:
            True if event should be triggered (threshold met and not in cooldown)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        with self.lock:
            # Add detection with timestamp
            self.detections.append((timestamp, detected))
            
            # Remove old detections outside the window
            window_start = timestamp - timedelta(seconds=self.config.detection_duration_seconds)
            while self.detections and self.detections[0][0] < window_start:
                self.detections.popleft()
            
            # Check if we're in cooldown
            if self.last_event_time:
                cooldown_end = self.last_event_time + timedelta(seconds=self.config.cooldown_seconds)
                if timestamp < cooldown_end:
                    remaining = (cooldown_end - timestamp).total_seconds()
                    self.logger.debug(f"In cooldown: {remaining:.1f}s remaining")
                    return False
            
            # Calculate detection percentage
            if len(self.detections) < 2:
                return False
            
            positive_count = sum(1 for _, d in self.detections if d)
            total_count = len(self.detections)
            percentage = (positive_count / total_count) * 100
            
            self.logger.debug(
                f"Detection window: {positive_count}/{total_count} = {percentage:.1f}% "
                f"(threshold: {self.config.detection_threshold_percent}%)"
            )
            
            # Check if we have enough samples over the duration
            if total_count >= 2:  # Minimum samples
                window_duration = (self.detections[-1][0] - self.detections[0][0]).total_seconds()
                
                # Only trigger if we've been tracking for at least the detection duration
                if window_duration >= self.config.detection_duration_seconds * 0.9:  # 90% of duration
                    if percentage >= self.config.detection_threshold_percent:
                        self.logger.info(
                            f"Detection threshold met: {percentage:.1f}% over {window_duration:.1f}s"
                        )
                        self.last_event_time = timestamp
                        self.detections.clear()
                        return True
            
            return False
    
    def reset(self):
        """Reset the detection window."""
        with self.lock:
            self.detections.clear()
            self.logger.debug("Detection window reset")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current detection window statistics."""
        with self.lock:
            if not self.detections:
                return {
                    'total_samples': 0,
                    'positive_count': 0,
                    'percentage': 0.0,
                    'window_duration': 0.0,
                    'in_cooldown': False,
                }
            
            positive_count = sum(1 for _, d in self.detections if d)
            total_count = len(self.detections)
            percentage = (positive_count / total_count) * 100 if total_count > 0 else 0
            window_duration = (self.detections[-1][0] - self.detections[0][0]).total_seconds()
            
            in_cooldown = False
            if self.last_event_time:
                cooldown_end = self.last_event_time + timedelta(seconds=self.config.cooldown_seconds)
                in_cooldown = datetime.now() < cooldown_end
            
            return {
                'total_samples': total_count,
                'positive_count': positive_count,
                'percentage': percentage,
                'window_duration': window_duration,
                'in_cooldown': in_cooldown,
            }


# =============================================================================
# MQTT Publisher
# =============================================================================

class MQTTPublisher:
    """Handles MQTT connection and event publishing."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.stop_event = Event()
        
        # Extract channel from RTSP URL
        self.channel = extract_channel_from_url(config.rtsp_url)
        self.logger.info(f"Extracted channel from RTSP URL: {self.channel}")
    
    def connect(self) -> bool:
        """
        Connect to MQTT broker.
        
        Returns:
            True if connection successful
        """
        try:
            # Create MQTT client with new callback API
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"palm_detection_{self.channel}"
            )
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            # Set credentials if provided
            if self.config.mqtt_username:
                self.client.username_pw_set(
                    self.config.mqtt_username,
                    self.config.mqtt_password
                )
                self.logger.debug(f"MQTT credentials set for user: {self.config.mqtt_username}")
            
            # Connect
            self.logger.info(
                f"Connecting to MQTT broker: {self.config.mqtt_host}:{self.config.mqtt_port}"
            )
            self.client.connect(
                self.config.mqtt_host,
                self.config.mqtt_port,
                keepalive=60
            )
            
            # Start network loop in background
            self.client.loop_start()
            
            # Wait for connection
            timeout = 10
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)
            
            if self.connected:
                self.logger.info("MQTT connection established")
                return True
            else:
                self.logger.error("MQTT connection timeout")
                return False
                
        except Exception as e:
            self.logger.error(f"MQTT connection error: {e}")
            return False
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker."""
        if reason_code == 0:
            self.connected = True
            self.logger.info(f"MQTT connected successfully (flags: {flags})")
        else:
            self.logger.error(f"MQTT connection failed: {reason_code}")
    
    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback when disconnected from MQTT broker."""
        self.connected = False
        self.logger.warning(f"MQTT disconnected: {reason_code}")
    
    def publish_palm_event(self) -> bool:
        """
        Publish palm detection event to MQTT.
        
        Returns:
            True if publish successful
        """
        if not self.client or not self.connected:
            self.logger.error("Cannot publish: MQTT not connected")
            return False
        
        try:
            payload = json.dumps({"channel": self.channel})
            
            result = self.client.publish(
                self.config.mqtt_topic,
                payload,
                qos=1  # At least once delivery
            )
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.logger.info(
                    f"MQTT event published: topic={self.config.mqtt_topic}, "
                    f"payload={payload}"
                )
                return True
            else:
                self.logger.error(f"MQTT publish failed: {result.rc}")
                return False
                
        except Exception as e:
            self.logger.error(f"MQTT publish error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MQTT broker."""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.logger.info("MQTT disconnected")


# =============================================================================
# RTSP Stream Handler
# =============================================================================

class RTSPStream:
    """Handles RTSP stream connection and frame capture."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        self.cap: Optional[cv2.VideoCapture] = None
        self.connected = False
        self.reconnect_attempts = 0
        
        # Frame info
        self.frame_width = 0
        self.frame_height = 0
        self.fps = 0
    
    def connect(self) -> bool:
        """
        Connect to RTSP stream.
        
        Returns:
            True if connection successful
        """
        # Redact credentials for logging
        redacted_url = re.sub(r'://[^:]+:[^@]+@', '://[REDACTED]@', self.config.rtsp_url)
        self.logger.info(f"Connecting to RTSP stream: {redacted_url}")
        
        try:
            # Set OpenCV capture options for RTSP
            self.cap = cv2.VideoCapture(self.config.rtsp_url, cv2.CAP_FFMPEG)
            
            # Set buffer size to reduce latency
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if not self.cap.isOpened():
                self.logger.error("Failed to open RTSP stream")
                return False
            
            # Get stream info
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            self.logger.info(
                f"RTSP stream connected: {self.frame_width}x{self.frame_height} @ {self.fps:.1f} FPS"
            )
            
            self.connected = True
            self.reconnect_attempts = 0
            return True
            
        except Exception as e:
            self.logger.error(f"RTSP connection error: {e}")
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        """
        Read a frame from the RTSP stream.
        
        Returns:
            Frame as numpy array, or None if read failed
        """
        if not self.cap or not self.connected:
            return None
        
        try:
            ret, frame = self.cap.read()
            
            if not ret or frame is None:
                self.logger.warning("Failed to read frame from RTSP stream")
                self.connected = False
                return None
            
            # Resize if needed to save CPU
            if self.frame_width > self.config.max_frame_width:
                scale = self.config.max_frame_width / self.frame_width
                new_width = self.config.max_frame_width
                new_height = int(self.frame_height * scale)
                frame = cv2.resize(frame, (new_width, new_height))
            
            return frame
            
        except Exception as e:
            self.logger.error(f"Frame read error: {e}")
            self.connected = False
            return None
    
    def reconnect(self) -> bool:
        """
        Attempt to reconnect to RTSP stream.
        
        Returns:
            True if reconnection successful
        """
        self.reconnect_attempts += 1
        
        max_attempts = self.config.rtsp_max_reconnect_attempts
        if max_attempts > 0 and self.reconnect_attempts > max_attempts:
            self.logger.error(
                f"Max reconnect attempts ({max_attempts}) exceeded"
            )
            return False
        
        self.logger.info(
            f"Reconnecting to RTSP stream (attempt {self.reconnect_attempts})..."
        )
        
        # Close existing connection
        self.disconnect()
        
        # Wait before reconnecting
        time.sleep(self.config.rtsp_reconnect_delay_seconds)
        
        return self.connect()
    
    def disconnect(self):
        """Disconnect from RTSP stream."""
        if self.cap:
            self.cap.release()
            self.cap = None
        self.connected = False
        self.logger.debug("RTSP stream disconnected")


# =============================================================================
# Main Detection Service
# =============================================================================

class PalmDetectionService:
    """Main service orchestrating palm detection."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config)
        
        self.logger.info("=" * 60)
        self.logger.info("Open Palm Detection Service Starting")
        self.logger.info("=" * 60)
        
        # Initialize components
        self.rtsp = RTSPStream(config, self.logger)
        self.mqtt = MQTTPublisher(config, self.logger)
        self.detector = PalmDetector(config, self.logger)
        self.detection_window = DetectionWindow(config, self.logger)
        
        # IR preprocessor (optional)
        self.preprocessor: Optional[IRPreprocessor] = None
        if config.ir_mode_enabled:
            self.preprocessor = IRPreprocessor(config, self.logger)
            self.logger.info("IR/Low-light preprocessing enabled")
        
        # Control flags
        self.running = False
        self.stop_event = Event()
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'palms_detected': 0,
            'events_sent': 0,
            'start_time': None,
        }
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
    
    def start(self):
        """Start the detection service."""
        self.logger.info("Starting detection service...")
        
        # Connect to MQTT
        if not self.mqtt.connect():
            self.logger.error("Failed to connect to MQTT broker, exiting")
            return False
        
        # Connect to RTSP
        if not self.rtsp.connect():
            self.logger.error("Failed to connect to RTSP stream, exiting")
            self.mqtt.disconnect()
            return False
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        
        # Main processing loop
        self._processing_loop()
        
        return True
    
    def _processing_loop(self):
        """Main frame processing loop."""
        frame_count = 0
        last_process_time = time.time()
        frame_interval = 1.0 / self.config.processing_fps
        
        self.logger.info(
            f"Starting processing loop: target FPS={self.config.processing_fps}, "
            f"frame_skip={self.config.frame_skip}, interval={frame_interval:.3f}s"
        )
        
        while self.running and not self.stop_event.is_set():
            try:
                # Check RTSP connection
                if not self.rtsp.connected:
                    self.logger.warning("RTSP connection lost, attempting reconnect...")
                    if not self.rtsp.reconnect():
                        self.logger.error("Failed to reconnect to RTSP stream")
                        break
                    self.detection_window.reset()
                    continue
                
                # Check MQTT connection
                if not self.mqtt.connected:
                    self.logger.warning("MQTT connection lost, attempting reconnect...")
                    if not self.mqtt.connect():
                        self.logger.warning("MQTT reconnect failed, will retry...")
                        time.sleep(self.config.mqtt_reconnect_delay_seconds)
                        continue
                
                # Rate limiting
                current_time = time.time()
                elapsed = current_time - last_process_time
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
                last_process_time = time.time()
                
                # Read frame
                frame = self.rtsp.read_frame()
                if frame is None:
                    continue
                
                frame_count += 1
                
                # Skip frames if configured
                if self.config.frame_skip > 0 and frame_count % (self.config.frame_skip + 1) != 0:
                    continue
                
                # Preprocess for IR/low-light
                if self.preprocessor:
                    frame_rgb = self.preprocessor.preprocess(frame)
                else:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Detect palm
                palm_detected, confidence, num_hands = self.detector.detect_open_palm(frame_rgb)
                
                self.stats['frames_processed'] += 1
                
                if palm_detected:
                    self.stats['palms_detected'] += 1
                    if self.config.log_detection_events:
                        self.logger.debug(
                            f"Palm detected: confidence={confidence:.2f}, hands={num_hands}"
                        )
                
                # Update detection window
                if self.detection_window.add_detection(palm_detected):
                    # Threshold met, send MQTT event
                    if self.mqtt.publish_palm_event():
                        self.stats['events_sent'] += 1
                        self.logger.info(
                            f"MQTT event sent! Total events: {self.stats['events_sent']}"
                        )
                
                # Log frame stats periodically
                if self.config.log_frame_stats and self.stats['frames_processed'] % 100 == 0:
                    self._log_stats()
                
            except Exception as e:
                self.logger.error(f"Processing loop error: {e}", exc_info=True)
                time.sleep(1)  # Avoid tight error loop
        
        self.logger.info("Processing loop ended")
        self._log_stats()
    
    def _log_stats(self):
        """Log current statistics."""
        runtime = (datetime.now() - self.stats['start_time']).total_seconds()
        fps = self.stats['frames_processed'] / runtime if runtime > 0 else 0
        
        window_stats = self.detection_window.get_stats()
        
        self.logger.info(
            f"Stats: frames={self.stats['frames_processed']}, "
            f"palms={self.stats['palms_detected']}, "
            f"events={self.stats['events_sent']}, "
            f"fps={fps:.1f}, "
            f"runtime={runtime:.1f}s"
        )
        self.logger.debug(
            f"Detection window: samples={window_stats['total_samples']}, "
            f"positive={window_stats['positive_count']}, "
            f"percentage={window_stats['percentage']:.1f}%, "
            f"duration={window_stats['window_duration']:.1f}s, "
            f"cooldown={window_stats['in_cooldown']}"
        )
    
    def stop(self):
        """Stop the detection service."""
        self.logger.info("Stopping detection service...")
        self.running = False
        self.stop_event.set()
        
        # Cleanup
        self.detector.close()
        self.rtsp.disconnect()
        self.mqtt.disconnect()
        
        self._log_stats()
        self.logger.info("Detection service stopped")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point."""
    # Load configuration
    config = Config.load()
    
    # Validate required configuration
    if not config.rtsp_url:
        print("ERROR: RTSP_URL environment variable is required", file=sys.stderr)
        sys.exit(1)
    
    # Create and start service
    service = PalmDetectionService(config)
    
    try:
        success = service.start()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        service.stop()
        sys.exit(0)
    except Exception as e:
        print(f"FATAL ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
