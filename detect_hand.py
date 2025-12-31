#!/usr/bin/env python3
"""
Gesture Detection Add-on for Home Assistant - Version 2.0

Uses YOLOv8-pose for robust pose detection that works with IR/grayscale cameras.
Detects raised arm gestures and sends MQTT events.

Author: Home Assistant Add-on
Version: 2.0.0
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
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass
from threading import Event, Lock

import cv2
import numpy as np
import paho.mqtt.client as mqtt

# YOLOv8 import
try:
    from ultralytics import YOLO
    print("YOLOv8 imported successfully")
except Exception as e:
    print(f"YOLOv8 import error: {e}")
    raise


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ROIZone:
    """Region of Interest zone definition."""
    name: str
    x1: int  # Percentage 0-100
    y1: int
    x2: int
    y2: int


@dataclass
class Config:
    """Configuration loaded from Home Assistant options.json."""
    
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
    model_complexity: int  # 0=nano, 1=small, 2=medium, 3=large
    
    # Gesture Configuration
    gesture_type: str
    arm_raised_threshold: float
    require_both_arms: bool
    
    # Pose Validation
    min_pose_height_ratio: float
    min_landmark_visibility: float
    validate_pose_anatomy: bool
    
    # ROI Configuration
    roi_enabled: bool
    roi_zones: List[ROIZone]
    
    # Performance Configuration
    frame_skip: int
    max_frame_width: int
    processing_fps: int
    
    # IR/Low-Light Configuration
    ir_mode_enabled: bool
    ir_preprocessing_mode: str
    clahe_clip_limit: float
    clahe_grid_size: int
    brightness_boost: float
    contrast_boost: float
    ir_gamma_correction: float
    ir_denoise: bool
    
    # Logging Configuration
    log_level: str
    log_detection_events: bool
    log_frame_stats: bool
    
    # Debug Configuration
    debug_save_frames: bool
    debug_save_interval: int
    debug_frame_path: str
    debug_draw_roi: bool
    
    # Connection Configuration
    rtsp_reconnect_delay_seconds: int
    rtsp_max_reconnect_attempts: int
    mqtt_reconnect_delay_seconds: int

    @classmethod
    def load(cls) -> 'Config':
        """Load configuration from Home Assistant options.json."""
        options = {}
        options_path = '/data/options.json'
        
        if os.path.exists(options_path):
            try:
                with open(options_path, 'r') as f:
                    options = json.load(f)
                print(f"Configuration loaded from {options_path}")
            except Exception as e:
                print(f"Warning: Could not load {options_path}: {e}")
        else:
            print(f"Options file not found at {options_path}, using defaults")
        
        def get_value(key: str, env_key: str, default, value_type=str):
            if key in options:
                val = options[key]
                if value_type == bool:
                    if isinstance(val, bool):
                        return val
                    return str(val).lower() == 'true'
                return value_type(val)
            env_val = os.environ.get(env_key)
            if env_val is not None:
                if value_type == bool:
                    return env_val.lower() == 'true'
                return value_type(env_val)
            return default
        
        # Parse ROI zones
        roi_zones = []
        raw_zones = options.get('roi_zones', [])
        for zone in raw_zones:
            if isinstance(zone, dict):
                roi_zones.append(ROIZone(
                    name=zone.get('name', 'unnamed'),
                    x1=int(zone.get('x1', 0)),
                    y1=int(zone.get('y1', 0)),
                    x2=int(zone.get('x2', 100)),
                    y2=int(zone.get('y2', 100)),
                ))
        
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
            confidence_threshold=get_value('confidence_threshold', 'CONFIDENCE_THRESHOLD', 0.3, float),
            model_complexity=get_value('model_complexity', 'MODEL_COMPLEXITY', 1, int),
            gesture_type=get_value('gesture_type', 'GESTURE_TYPE', 'arm_raised'),
            arm_raised_threshold=get_value('arm_raised_threshold', 'ARM_RAISED_THRESHOLD', 0.02, float),
            require_both_arms=get_value('require_both_arms', 'REQUIRE_BOTH_ARMS', False, bool),
            min_pose_height_ratio=get_value('min_pose_height_ratio', 'MIN_POSE_HEIGHT_RATIO', 0.15, float),
            min_landmark_visibility=get_value('min_landmark_visibility', 'MIN_LANDMARK_VISIBILITY', 0.3, float),
            validate_pose_anatomy=get_value('validate_pose_anatomy', 'VALIDATE_POSE_ANATOMY', False, bool),
            roi_enabled=get_value('roi_enabled', 'ROI_ENABLED', False, bool),
            roi_zones=roi_zones,
            frame_skip=get_value('frame_skip', 'FRAME_SKIP', 0, int),
            max_frame_width=get_value('max_frame_width', 'MAX_FRAME_WIDTH', 1280, int),
            processing_fps=get_value('processing_fps', 'PROCESSING_FPS', 10, int),
            ir_mode_enabled=get_value('ir_mode_enabled', 'IR_MODE_ENABLED', True, bool),
            ir_preprocessing_mode=get_value('ir_preprocessing_mode', 'IR_PREPROCESSING_MODE', 'none'),
            clahe_clip_limit=get_value('clahe_clip_limit', 'CLAHE_CLIP_LIMIT', 2.0, float),
            clahe_grid_size=get_value('clahe_grid_size', 'CLAHE_GRID_SIZE', 8, int),
            brightness_boost=get_value('brightness_boost', 'BRIGHTNESS_BOOST', 1.0, float),
            contrast_boost=get_value('contrast_boost', 'CONTRAST_BOOST', 1.0, float),
            ir_gamma_correction=get_value('ir_gamma_correction', 'IR_GAMMA_CORRECTION', 1.0, float),
            ir_denoise=get_value('ir_denoise', 'IR_DENOISE', False, bool),
            log_level=get_value('log_level', 'LOG_LEVEL', 'INFO'),
            log_detection_events=get_value('log_detection_events', 'LOG_DETECTION_EVENTS', True, bool),
            log_frame_stats=get_value('log_frame_stats', 'LOG_FRAME_STATS', False, bool),
            debug_save_frames=get_value('debug_save_frames', 'DEBUG_SAVE_FRAMES', False, bool),
            debug_save_interval=get_value('debug_save_interval', 'DEBUG_SAVE_INTERVAL', 30, int),
            debug_frame_path=get_value('debug_frame_path', 'DEBUG_FRAME_PATH', '/share/detect-hand-debug'),
            debug_draw_roi=get_value('debug_draw_roi', 'DEBUG_DRAW_ROI', True, bool),
            rtsp_reconnect_delay_seconds=get_value('rtsp_reconnect_delay_seconds', 'RTSP_RECONNECT_DELAY_SECONDS', 5, int),
            rtsp_max_reconnect_attempts=get_value('rtsp_max_reconnect_attempts', 'RTSP_MAX_RECONNECT_ATTEMPTS', 0, int),
            mqtt_reconnect_delay_seconds=get_value('mqtt_reconnect_delay_seconds', 'MQTT_RECONNECT_DELAY_SECONDS', 5, int),
        )


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(config: Config) -> logging.Logger:
    """Set up logging."""
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)
    logger = logging.getLogger('gesture_detection')
    logger.setLevel(log_level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def extract_channel_from_url(rtsp_url: str) -> str:
    """Extract channel number from RTSP URL."""
    match = re.search(r'/channels/(\d+)', rtsp_url)
    if match:
        return match.group(1)
    match = re.search(r'[?&]channel=(\d+)', rtsp_url)
    if match:
        return match.group(1)
    return "unknown"


# =============================================================================
# YOLOv8 Pose Detector
# =============================================================================

class YOLOPoseDetector:
    """
    Pose detector using YOLOv8-pose.
    
    YOLOv8-pose keypoints (17 points):
    0: nose, 1: left_eye, 2: right_eye, 3: left_ear, 4: right_ear,
    5: left_shoulder, 6: right_shoulder, 7: left_elbow, 8: right_elbow,
    9: left_wrist, 10: right_wrist, 11: left_hip, 12: right_hip,
    13: left_knee, 14: right_knee, 15: left_ankle, 16: right_ankle
    """
    
    # Keypoint indices
    NOSE = 0
    LEFT_EYE = 1
    RIGHT_EYE = 2
    LEFT_SHOULDER = 5
    RIGHT_SHOULDER = 6
    LEFT_ELBOW = 7
    RIGHT_ELBOW = 8
    LEFT_WRIST = 9
    RIGHT_WRIST = 10
    LEFT_HIP = 11
    RIGHT_HIP = 12
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Select model based on complexity
        # 0=nano, 1=small, 2=medium, 3=large
        model_names = ['yolov8n-pose.pt', 'yolov8s-pose.pt', 'yolov8m-pose.pt', 'yolov8l-pose.pt']
        model_name = model_names[min(config.model_complexity, 3)]
        
        self.logger.info(f"Loading YOLOv8 pose model: {model_name}")
        self.model = YOLO(model_name)
        self.logger.info(f"YOLOv8 pose model loaded successfully")
        
        if config.roi_enabled and config.roi_zones:
            self.logger.info(f"ROI filtering enabled with {len(config.roi_zones)} zone(s)")
    
    def detect_gesture(self, frame: np.ndarray) -> Tuple[bool, Dict[str, Any], Any]:
        """
        Detect if the configured gesture is visible in the frame.
        
        Returns:
            Tuple of (gesture_detected, details_dict, results_for_drawing)
        """
        # Run YOLOv8 pose detection
        results = self.model(frame, conf=self.config.confidence_threshold, verbose=False)
        
        if len(results) == 0 or results[0].keypoints is None:
            self.logger.debug("No detections from YOLO")
            return False, {'persons': 0}, results
        
        keypoints = results[0].keypoints
        boxes = results[0].boxes
        
        if keypoints.xy is None or len(keypoints.xy) == 0:
            self.logger.debug("No keypoints detected")
            return False, {'persons': 0}, results
        
        num_persons = len(keypoints.xy)
        self.logger.debug(f"Detected {num_persons} person(s)")
        
        frame_h, frame_w = frame.shape[:2]
        
        for person_idx in range(num_persons):
            kpts = keypoints.xy[person_idx].cpu().numpy()  # Shape: (17, 2)
            
            # Get confidence scores if available
            if keypoints.conf is not None:
                confs = keypoints.conf[person_idx].cpu().numpy()
            else:
                confs = np.ones(17)
            
            # Check if person is in ROI
            if self.config.roi_enabled and self.config.roi_zones:
                in_roi, zone_name = self._check_roi(kpts, frame_w, frame_h)
                if not in_roi:
                    self.logger.debug(f"Person {person_idx} outside ROI")
                    continue
                self.logger.debug(f"Person {person_idx} in ROI '{zone_name}'")
            
            # Check pose quality
            if not self._validate_pose(kpts, confs, frame_h):
                self.logger.debug(f"Person {person_idx} pose validation failed")
                continue
            
            # Check for gesture
            gesture_detected, details = self._check_arm_raised(kpts, confs, frame_h)
            
            if gesture_detected:
                details['person_idx'] = person_idx
                details['persons'] = num_persons
                self.logger.debug(f"Gesture detected on person {person_idx}: {details}")
                return True, details, results
        
        return False, {'persons': num_persons}, results
    
    def _check_roi(self, kpts: np.ndarray, frame_w: int, frame_h: int) -> Tuple[bool, Optional[str]]:
        """Check if person is within ROI."""
        # Use hip center as person position
        left_hip = kpts[self.LEFT_HIP]
        right_hip = kpts[self.RIGHT_HIP]
        
        if left_hip[0] > 0 and right_hip[0] > 0:
            person_x = (left_hip[0] + right_hip[0]) / 2 / frame_w * 100
            person_y = (left_hip[1] + right_hip[1]) / 2 / frame_h * 100
        else:
            # Fall back to nose
            nose = kpts[self.NOSE]
            person_x = nose[0] / frame_w * 100
            person_y = nose[1] / frame_h * 100
        
        for zone in self.config.roi_zones:
            if zone.x1 <= person_x <= zone.x2 and zone.y1 <= person_y <= zone.y2:
                return True, zone.name
        
        return False, None
    
    def _validate_pose(self, kpts: np.ndarray, confs: np.ndarray, frame_h: int) -> bool:
        """Validate pose quality."""
        # Check if key points are detected (non-zero)
        nose = kpts[self.NOSE]
        left_shoulder = kpts[self.LEFT_SHOULDER]
        right_shoulder = kpts[self.RIGHT_SHOULDER]
        
        # At least nose and one shoulder should be detected
        nose_detected = nose[0] > 0 and nose[1] > 0
        left_shoulder_detected = left_shoulder[0] > 0 and left_shoulder[1] > 0
        right_shoulder_detected = right_shoulder[0] > 0 and right_shoulder[1] > 0
        
        if not nose_detected:
            self.logger.debug("Nose not detected")
            return False
        
        if not (left_shoulder_detected or right_shoulder_detected):
            self.logger.debug("No shoulders detected")
            return False
        
        # Check pose height
        valid_y = [kpts[i][1] for i in range(17) if kpts[i][0] > 0 and kpts[i][1] > 0]
        if len(valid_y) < 3:
            return False
        
        pose_height = (max(valid_y) - min(valid_y)) / frame_h
        if pose_height < self.config.min_pose_height_ratio:
            self.logger.debug(f"Pose too small: {pose_height:.3f} < {self.config.min_pose_height_ratio}")
            return False
        
        return True
    
    def _check_arm_raised(self, kpts: np.ndarray, confs: np.ndarray, frame_h: int) -> Tuple[bool, Dict]:
        """Check if arm is raised above head."""
        nose = kpts[self.NOSE]
        left_wrist = kpts[self.LEFT_WRIST]
        right_wrist = kpts[self.RIGHT_WRIST]
        left_elbow = kpts[self.LEFT_ELBOW]
        right_elbow = kpts[self.RIGHT_ELBOW]
        left_shoulder = kpts[self.LEFT_SHOULDER]
        right_shoulder = kpts[self.RIGHT_SHOULDER]
        
        threshold_pixels = self.config.arm_raised_threshold * frame_h
        
        # Check left arm
        left_wrist_detected = left_wrist[0] > 0 and left_wrist[1] > 0
        left_elbow_detected = left_elbow[0] > 0 and left_elbow[1] > 0
        left_shoulder_detected = left_shoulder[0] > 0 and left_shoulder[1] > 0
        
        left_raised = False
        if left_wrist_detected and left_shoulder_detected:
            # Wrist above nose (lower Y value = higher in image)
            wrist_above_nose = (nose[1] - left_wrist[1]) > threshold_pixels
            # Also check elbow above shoulder
            elbow_above_shoulder = left_elbow_detected and left_elbow[1] < left_shoulder[1]
            left_raised = wrist_above_nose and elbow_above_shoulder
        
        # Check right arm
        right_wrist_detected = right_wrist[0] > 0 and right_wrist[1] > 0
        right_elbow_detected = right_elbow[0] > 0 and right_elbow[1] > 0
        right_shoulder_detected = right_shoulder[0] > 0 and right_shoulder[1] > 0
        
        right_raised = False
        if right_wrist_detected and right_shoulder_detected:
            wrist_above_nose = (nose[1] - right_wrist[1]) > threshold_pixels
            elbow_above_shoulder = right_elbow_detected and right_elbow[1] < right_shoulder[1]
            right_raised = wrist_above_nose and elbow_above_shoulder
        
        details = {
            'nose_y': nose[1],
            'left_wrist_y': left_wrist[1] if left_wrist_detected else -1,
            'right_wrist_y': right_wrist[1] if right_wrist_detected else -1,
            'left_raised': left_raised,
            'right_raised': right_raised,
            'threshold_pixels': threshold_pixels,
        }
        
        self.logger.debug(
            f"Arm check: L_raised={left_raised}, R_raised={right_raised}, "
            f"nose_y={nose[1]:.0f}, L_wrist_y={left_wrist[1]:.0f}, R_wrist_y={right_wrist[1]:.0f}"
        )
        
        if self.config.require_both_arms:
            return left_raised and right_raised, details
        else:
            return left_raised or right_raised, details
    
    def draw_results(self, frame: np.ndarray, results, draw_roi: bool = True) -> np.ndarray:
        """Draw detection results on frame."""
        annotated = frame.copy()
        h, w = annotated.shape[:2]
        
        # Draw ROI zones
        if draw_roi and self.config.roi_enabled and self.config.roi_zones:
            for zone in self.config.roi_zones:
                x1 = int(zone.x1 * w / 100)
                y1 = int(zone.y1 * h / 100)
                x2 = int(zone.x2 * w / 100)
                y2 = int(zone.y2 * h / 100)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 255), 2)
                cv2.putText(annotated, zone.name, (x1 + 5, y1 + 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # Draw YOLO results
        if results and len(results) > 0:
            annotated = results[0].plot(img=annotated)
        
        return annotated
    
    def close(self):
        """Cleanup."""
        pass


# =============================================================================
# Detection Window Tracker
# =============================================================================

class DetectionWindow:
    """Tracks gesture detections over a sliding time window."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.detections: deque = deque()
        self.last_event_time: Optional[datetime] = None
        self.lock = Lock()
    
    def add_detection(self, detected: bool, timestamp: Optional[datetime] = None) -> bool:
        """Add detection and check if event should trigger."""
        if timestamp is None:
            timestamp = datetime.now()
        
        with self.lock:
            self.detections.append((timestamp, detected))
            
            # Remove old detections
            window_start = timestamp - timedelta(seconds=self.config.detection_duration_seconds)
            while self.detections and self.detections[0][0] < window_start:
                self.detections.popleft()
            
            # Check cooldown
            if self.last_event_time:
                cooldown_end = self.last_event_time + timedelta(seconds=self.config.cooldown_seconds)
                if timestamp < cooldown_end:
                    return False
            
            if len(self.detections) < 2:
                return False
            
            positive_count = sum(1 for _, d in self.detections if d)
            total_count = len(self.detections)
            percentage = (positive_count / total_count) * 100
            
            self.logger.debug(f"Detection window: {positive_count}/{total_count} = {percentage:.1f}%")
            
            window_duration = (self.detections[-1][0] - self.detections[0][0]).total_seconds()
            
            if window_duration >= self.config.detection_duration_seconds * 0.9:
                if percentage >= self.config.detection_threshold_percent:
                    self.logger.info(f"Threshold met: {percentage:.1f}% over {window_duration:.1f}s")
                    self.last_event_time = timestamp
                    self.detections.clear()
                    return True
            
            return False
    
    def reset(self):
        with self.lock:
            self.detections.clear()


# =============================================================================
# MQTT Publisher
# =============================================================================

class MQTTPublisher:
    """Handles MQTT publishing."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.channel = extract_channel_from_url(config.rtsp_url)
        self.logger.info(f"Channel: {self.channel}")
    
    def connect(self) -> bool:
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"gesture_detection_{self.channel}"
            )
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            if self.config.mqtt_username:
                self.client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password)
            
            self.logger.info(f"Connecting to MQTT: {self.config.mqtt_host}:{self.config.mqtt_port}")
            self.client.connect(self.config.mqtt_host, self.config.mqtt_port, keepalive=60)
            self.client.loop_start()
            
            timeout = 10
            start = time.time()
            while not self.connected and time.time() - start < timeout:
                time.sleep(0.1)
            
            return self.connected
        except Exception as e:
            self.logger.error(f"MQTT error: {e}")
            return False
    
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = reason_code == 0
        self.logger.info(f"MQTT {'connected' if self.connected else 'failed'}")
    
    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        self.logger.warning("MQTT disconnected")
    
    def publish_event(self, gesture_type: str = "arm_raised") -> bool:
        if not self.connected:
            return False
        try:
            payload = json.dumps({"channel": self.channel, "gesture": gesture_type})
            result = self.client.publish(self.config.mqtt_topic, payload, qos=1)
            self.logger.info(f"MQTT published: {payload}")
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        except Exception as e:
            self.logger.error(f"MQTT publish error: {e}")
            return False
    
    def disconnect(self):
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()


# =============================================================================
# RTSP Stream
# =============================================================================

class RTSPStream:
    """Handles RTSP streaming."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.cap: Optional[cv2.VideoCapture] = None
        self.connected = False
        self.reconnect_attempts = 0
        self.frame_width = 0
        self.frame_height = 0
    
    def connect(self) -> bool:
        redacted = re.sub(r'://[^:]+:[^@]+@', '://[REDACTED]@', self.config.rtsp_url)
        self.logger.info(f"Connecting to: {redacted}")
        
        try:
            self.cap = cv2.VideoCapture(self.config.rtsp_url, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if not self.cap.isOpened():
                return False
            
            self.frame_width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.frame_height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = self.cap.get(cv2.CAP_PROP_FPS)
            
            self.logger.info(f"Stream: {self.frame_width}x{self.frame_height} @ {fps:.1f} FPS")
            self.connected = True
            self.reconnect_attempts = 0
            return True
        except Exception as e:
            self.logger.error(f"RTSP error: {e}")
            return False
    
    def read_frame(self) -> Optional[np.ndarray]:
        if not self.cap or not self.connected:
            return None
        try:
            ret, frame = self.cap.read()
            if not ret:
                self.connected = False
                return None
            
            # Resize if needed
            if self.frame_width > self.config.max_frame_width:
                scale = self.config.max_frame_width / self.frame_width
                new_w = self.config.max_frame_width
                new_h = int(self.frame_height * scale)
                frame = cv2.resize(frame, (new_w, new_h))
            
            return frame
        except:
            self.connected = False
            return None
    
    def reconnect(self) -> bool:
        self.reconnect_attempts += 1
        max_attempts = self.config.rtsp_max_reconnect_attempts
        if max_attempts > 0 and self.reconnect_attempts > max_attempts:
            return False
        self.disconnect()
        time.sleep(self.config.rtsp_reconnect_delay_seconds)
        return self.connect()
    
    def disconnect(self):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.connected = False


# =============================================================================
# Main Service
# =============================================================================

class GestureDetectionService:
    """Main service."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config)
        
        self.logger.info("=" * 60)
        self.logger.info("Gesture Detection Service v2.0 (YOLOv8)")
        self.logger.info("=" * 60)
        
        self.rtsp = RTSPStream(config, self.logger)
        self.mqtt = MQTTPublisher(config, self.logger)
        self.detector = YOLOPoseDetector(config, self.logger)
        self.detection_window = DetectionWindow(config, self.logger)
        
        self.running = False
        self.stop_event = Event()
        self.last_debug_save = 0.0
        
        self.stats = {
            'frames_processed': 0,
            'gestures_detected': 0,
            'events_sent': 0,
            'start_time': None,
        }
        
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        self.logger.info(f"Signal {signum}, shutting down...")
        self.stop()
    
    def start(self):
        if not self.mqtt.connect():
            self.logger.error("MQTT connection failed")
            return False
        
        if not self.rtsp.connect():
            self.logger.error("RTSP connection failed")
            return False
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        self._processing_loop()
        return True
    
    def _processing_loop(self):
        frame_count = 0
        frame_interval = 1.0 / self.config.processing_fps
        last_time = time.time()
        
        self.logger.info(f"Processing: FPS={self.config.processing_fps}, skip={self.config.frame_skip}")
        
        while self.running and not self.stop_event.is_set():
            try:
                if not self.rtsp.connected:
                    if not self.rtsp.reconnect():
                        break
                    self.detection_window.reset()
                    continue
                
                if not self.mqtt.connected:
                    self.mqtt.connect()
                    time.sleep(1)
                    continue
                
                # Rate limit
                current = time.time()
                if current - last_time < frame_interval:
                    time.sleep(frame_interval - (current - last_time))
                last_time = time.time()
                
                frame = self.rtsp.read_frame()
                if frame is None:
                    continue
                
                frame_count += 1
                if self.config.frame_skip > 0 and frame_count % (self.config.frame_skip + 1) != 0:
                    continue
                
                # Detect gesture
                gesture_detected, details, results = self.detector.detect_gesture(frame)
                
                self.stats['frames_processed'] += 1
                
                if gesture_detected:
                    self.stats['gestures_detected'] += 1
                    self.logger.info(f"Gesture detected: {self.config.gesture_type}")
                
                if self.detection_window.add_detection(gesture_detected):
                    if self.mqtt.publish_event(self.config.gesture_type):
                        self.stats['events_sent'] += 1
                        self.logger.info(f"Event sent! Total: {self.stats['events_sent']}")
                
                # Debug frames
                if self.config.debug_save_frames:
                    self._save_debug_frame(frame, results, gesture_detected)
                
                if self.config.log_frame_stats and self.stats['frames_processed'] % 100 == 0:
                    self._log_stats()
                
            except Exception as e:
                self.logger.error(f"Loop error: {e}", exc_info=True)
                time.sleep(1)
        
        self._log_stats()
    
    def _save_debug_frame(self, frame: np.ndarray, results, gesture_detected: bool):
        current = time.time()
        if current - self.last_debug_save < self.config.debug_save_interval:
            return
        self.last_debug_save = current
        
        try:
            os.makedirs(self.config.debug_frame_path, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            detected_str = "DETECTED" if gesture_detected else "none"
            
            # Save original
            cv2.imwrite(os.path.join(self.config.debug_frame_path, f"original_{ts}_{detected_str}.jpg"), frame)
            
            # Save annotated
            annotated = self.detector.draw_results(frame, results, self.config.debug_draw_roi)
            cv2.imwrite(os.path.join(self.config.debug_frame_path, f"annotated_{ts}_{detected_str}.jpg"), annotated)
            
            self.logger.info(f"Debug frames saved: {ts}")
            
            # Cleanup old files
            import glob
            files = sorted(glob.glob(os.path.join(self.config.debug_frame_path, "*.jpg")), key=os.path.getmtime)
            for f in files[:-60]:
                os.remove(f)
        except Exception as e:
            self.logger.error(f"Debug save error: {e}")
    
    def _log_stats(self):
        runtime = (datetime.now() - self.stats['start_time']).total_seconds()
        fps = self.stats['frames_processed'] / runtime if runtime > 0 else 0
        self.logger.info(
            f"Stats: frames={self.stats['frames_processed']}, "
            f"gestures={self.stats['gestures_detected']}, "
            f"events={self.stats['events_sent']}, fps={fps:.1f}"
        )
    
    def stop(self):
        self.running = False
        self.stop_event.set()
        self.detector.close()
        self.rtsp.disconnect()
        self.mqtt.disconnect()


def main():
    config = Config.load()
    if not config.rtsp_url:
        print("ERROR: RTSP_URL required")
        sys.exit(1)
    
    service = GestureDetectionService(config)
    try:
        service.start()
    except KeyboardInterrupt:
        service.stop()


if __name__ == '__main__':
    main()
