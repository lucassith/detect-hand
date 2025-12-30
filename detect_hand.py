#!/usr/bin/env python3
"""
Gesture Detection Add-on for Home Assistant

Detects raised arm gestures from RTSP camera stream (including IR/low-light)
and sends MQTT events when gesture is held for configured duration.

Uses MediaPipe Pose for full-body pose detection, which works at longer distances
than hand detection.

Author: Home Assistant Add-on
Version: 1.1.0
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
from dataclasses import dataclass, field
from threading import Event, Lock

import cv2
import numpy as np
import paho.mqtt.client as mqtt

# MediaPipe import with diagnostics
try:
    import mediapipe as mp
    print(f"MediaPipe imported from: {mp.__file__}")
    print(f"MediaPipe version: {mp.__version__}")
    
    # Verify pose solution is available
    from mediapipe.python.solutions import pose as mp_pose
    from mediapipe.python.solutions import drawing_utils as mp_drawing
    print("MediaPipe Pose module loaded successfully")
except Exception as e:
    print(f"MediaPipe import error: {e}")
    import traceback
    traceback.print_exc()
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
    clahe_clip_limit: float
    clahe_grid_size: int
    brightness_boost: float
    contrast_boost: float
    
    # Logging Configuration
    log_level: str
    log_detection_events: bool
    log_frame_stats: bool
    
    # Debug Configuration
    debug_save_frames: bool
    debug_save_interval: int
    debug_frame_path: str
    
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
        print(f"Raw ROI zones from config: {raw_zones}")
        for zone in raw_zones:
            print(f"Processing zone: {zone}, type: {type(zone)}")
            if isinstance(zone, dict):
                roi_zones.append(ROIZone(
                    name=zone.get('name', 'unnamed'),
                    x1=int(zone.get('x1', 0)),
                    y1=int(zone.get('y1', 0)),
                    x2=int(zone.get('x2', 100)),
                    y2=int(zone.get('y2', 100)),
                ))
                print(f"Added ROI zone: {roi_zones[-1]}")
        print(f"Total ROI zones loaded: {len(roi_zones)}")
        
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
            gesture_type=get_value('gesture_type', 'GESTURE_TYPE', 'arm_raised'),
            arm_raised_threshold=get_value('arm_raised_threshold', 'ARM_RAISED_THRESHOLD', 0.15, float),
            require_both_arms=get_value('require_both_arms', 'REQUIRE_BOTH_ARMS', False, bool),
            min_pose_height_ratio=get_value('min_pose_height_ratio', 'MIN_POSE_HEIGHT_RATIO', 0.15, float),
            min_landmark_visibility=get_value('min_landmark_visibility', 'MIN_LANDMARK_VISIBILITY', 0.5, float),
            validate_pose_anatomy=get_value('validate_pose_anatomy', 'VALIDATE_POSE_ANATOMY', True, bool),
            roi_enabled=get_value('roi_enabled', 'ROI_ENABLED', False, bool),
            roi_zones=roi_zones,
            frame_skip=get_value('frame_skip', 'FRAME_SKIP', 2, int),
            max_frame_width=get_value('max_frame_width', 'MAX_FRAME_WIDTH', 1280, int),
            processing_fps=get_value('processing_fps', 'PROCESSING_FPS', 10, int),
            ir_mode_enabled=get_value('ir_mode_enabled', 'IR_MODE_ENABLED', False, bool),
            clahe_clip_limit=get_value('clahe_clip_limit', 'CLAHE_CLIP_LIMIT', 3.0, float),
            clahe_grid_size=get_value('clahe_grid_size', 'CLAHE_GRID_SIZE', 8, int),
            brightness_boost=get_value('brightness_boost', 'BRIGHTNESS_BOOST', 1.2, float),
            contrast_boost=get_value('contrast_boost', 'CONTRAST_BOOST', 1.3, float),
            log_level=get_value('log_level', 'LOG_LEVEL', 'INFO'),
            log_detection_events=get_value('log_detection_events', 'LOG_DETECTION_EVENTS', True, bool),
            log_frame_stats=get_value('log_frame_stats', 'LOG_FRAME_STATS', False, bool),
            debug_save_frames=get_value('debug_save_frames', 'DEBUG_SAVE_FRAMES', False, bool),
            debug_save_interval=get_value('debug_save_interval', 'DEBUG_SAVE_INTERVAL', 30, int),
            debug_frame_path=get_value('debug_frame_path', 'DEBUG_FRAME_PATH', '/share/detect-hand-debug'),
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


# =============================================================================
# Channel Extraction
# =============================================================================

def extract_channel_from_url(rtsp_url: str) -> str:
    """Extract channel number from RTSP URL."""
    match = re.search(r'/channels/(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    match = re.search(r'[?&]channel=(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    match = re.search(r'/ch(\d+)', rtsp_url)
    if match:
        return match.group(1)
    
    return "unknown"


# =============================================================================
# Image Preprocessing for IR/Low-Light
# =============================================================================

class IRPreprocessor:
    """Preprocessor for IR/low-light camera images."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
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
        """Preprocess frame for better detection in IR/low-light conditions."""
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()
        
        enhanced = self.clahe.apply(gray)
        
        brightness_offset = int((self.config.brightness_boost - 1.0) * 128)
        enhanced = cv2.convertScaleAbs(
            enhanced, 
            alpha=self.config.contrast_boost, 
            beta=brightness_offset
        )
        
        rgb = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2RGB)
        
        return rgb


# =============================================================================
# Pose/Gesture Detection
# =============================================================================

class GestureDetector:
    """Detects gestures using MediaPipe Pose."""
    
    # MediaPipe Pose landmark indices
    NOSE = 0
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_HIP = 23
    RIGHT_HIP = 24
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        
        # Initialize MediaPipe Pose
        self.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,  # 0=lite, 1=full, 2=heavy
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=config.confidence_threshold,
            min_tracking_confidence=config.confidence_threshold * 0.8,
        )
        
        self.logger.info(
            f"Gesture detector initialized: type={config.gesture_type}, "
            f"confidence={config.confidence_threshold}, "
            f"arm_threshold={config.arm_raised_threshold}"
        )
        
        if config.roi_enabled and config.roi_zones:
            self.logger.info(f"ROI filtering enabled with {len(config.roi_zones)} zone(s):")
            for zone in config.roi_zones:
                self.logger.info(f"  - {zone.name}: ({zone.x1},{zone.y1}) to ({zone.x2},{zone.y2})")
    
    def detect_gesture(self, frame_rgb: np.ndarray) -> Tuple[bool, Dict[str, Any], Optional[Any]]:
        """
        Detect if the configured gesture is visible in the frame.
        
        Args:
            frame_rgb: RGB frame
            
        Returns:
            Tuple of (gesture_detected, details_dict, pose_results)
        """
        results = self.pose.process(frame_rgb)
        
        if not results.pose_landmarks:
            self.logger.debug("No person/pose detected in frame")
            return False, {'persons': 0}, results
        
        landmarks = results.pose_landmarks.landmark
        
        # Validate pose to filter false positives (like cars)
        is_valid, validation_details = self._validate_pose(landmarks, frame_rgb.shape)
        if not is_valid:
            self.logger.debug(f"Pose rejected: {validation_details}")
            return False, {'persons': 0, 'rejected': validation_details}, results
        
        # Check if pose is within ROI
        in_roi, zone_name = self._check_roi(landmarks)
        if not in_roi:
            return False, {'persons': 1, 'rejected': 'outside_roi'}, results
        
        validation_details['roi_zone'] = zone_name
        
        # Get key landmark positions
        nose = landmarks[self.NOSE]
        left_shoulder = landmarks[self.LEFT_SHOULDER]
        right_shoulder = landmarks[self.RIGHT_SHOULDER]
        left_wrist = landmarks[self.LEFT_WRIST]
        right_wrist = landmarks[self.RIGHT_WRIST]
        left_elbow = landmarks[self.LEFT_ELBOW]
        right_elbow = landmarks[self.RIGHT_ELBOW]
        
        # Calculate visibility
        min_vis = self.config.min_landmark_visibility
        pose_visible = (
            nose.visibility > min_vis and
            (left_shoulder.visibility > min_vis * 0.6 or right_shoulder.visibility > min_vis * 0.6)
        )
        
        if not pose_visible:
            self.logger.debug(f"Pose detected but low visibility: nose={nose.visibility:.2f}")
            return False, {'persons': 1, 'visibility': 'low'}, results
        
        self.logger.debug(f"Valid pose detected: nose_vis={nose.visibility:.2f}, validation={validation_details}")
        
        # Check gesture based on type
        if self.config.gesture_type == 'arm_raised':
            detected, details = self._check_arm_raised(
                nose, left_shoulder, right_shoulder,
                left_wrist, right_wrist, left_elbow, right_elbow
            )
        elif self.config.gesture_type == 'both_arms_raised':
            detected, details = self._check_both_arms_raised(
                nose, left_shoulder, right_shoulder,
                left_wrist, right_wrist
            )
        else:
            detected = False
            details = {'error': f'Unknown gesture type: {self.config.gesture_type}'}
        
        details['persons'] = 1
        details['validation'] = validation_details
        return detected, details, results
    
    def _validate_pose(self, landmarks, frame_shape) -> Tuple[bool, Dict[str, Any]]:
        """
        Validate that detected pose looks like a real person.
        Filters out false positives from objects like cars.
        
        Checks:
        1. Pose has reasonable height (not too small/compressed)
        2. Key landmarks are visible
        3. Anatomical structure makes sense (head above shoulders above hips)
        """
        details = {}
        
        nose = landmarks[self.NOSE]
        left_shoulder = landmarks[self.LEFT_SHOULDER]
        right_shoulder = landmarks[self.RIGHT_SHOULDER]
        left_hip = landmarks[self.LEFT_HIP]
        right_hip = landmarks[self.RIGHT_HIP]
        
        # Check 1: Pose height ratio
        # Calculate vertical extent of the pose
        all_y = [lm.y for lm in landmarks if lm.visibility > 0.3]
        if len(all_y) < 5:
            details['reason'] = 'too_few_visible_landmarks'
            details['visible_count'] = len(all_y)
            return False, details
        
        min_y = min(all_y)
        max_y = max(all_y)
        pose_height = max_y - min_y
        
        details['pose_height_ratio'] = pose_height
        
        if pose_height < self.config.min_pose_height_ratio:
            details['reason'] = 'pose_too_small'
            details['required'] = self.config.min_pose_height_ratio
            return False, details
        
        # Check 2: Key landmark visibility
        key_landmarks_visible = (
            nose.visibility > self.config.min_landmark_visibility * 0.8 and
            (left_shoulder.visibility > self.config.min_landmark_visibility * 0.5 or 
             right_shoulder.visibility > self.config.min_landmark_visibility * 0.5)
        )
        
        details['nose_visibility'] = nose.visibility
        details['left_shoulder_visibility'] = left_shoulder.visibility
        details['right_shoulder_visibility'] = right_shoulder.visibility
        
        if not key_landmarks_visible:
            details['reason'] = 'key_landmarks_not_visible'
            return False, details
        
        # Check 3: Anatomical validation (if enabled)
        if self.config.validate_pose_anatomy:
            # Head should be above shoulders
            avg_shoulder_y = (left_shoulder.y + right_shoulder.y) / 2
            head_above_shoulders = nose.y < avg_shoulder_y
            
            # Shoulders should be above hips (for standing person)
            avg_hip_y = (left_hip.y + right_hip.y) / 2
            shoulders_above_hips = avg_shoulder_y < avg_hip_y
            
            # Shoulder width should be reasonable compared to height
            shoulder_width = abs(left_shoulder.x - right_shoulder.x)
            width_height_ratio = shoulder_width / pose_height if pose_height > 0 else 0
            
            details['head_above_shoulders'] = head_above_shoulders
            details['shoulders_above_hips'] = shoulders_above_hips
            details['width_height_ratio'] = width_height_ratio
            
            # A real person standing should have head above shoulders
            if not head_above_shoulders:
                details['reason'] = 'head_not_above_shoulders'
                return False, details
            
            # Width/height ratio for a person is typically 0.3-0.8
            # Cars would have a very different ratio
            if width_height_ratio > 1.5 or width_height_ratio < 0.1:
                details['reason'] = 'abnormal_proportions'
                return False, details
        
        details['reason'] = 'valid'
        return True, details
    
    def _check_roi(self, landmarks) -> Tuple[bool, Optional[str]]:
        """
        Check if the detected pose is within any of the defined ROI zones.
        
        Returns:
            Tuple of (is_in_roi, zone_name)
        """
        if not self.config.roi_enabled or not self.config.roi_zones:
            return True, None  # ROI disabled, allow all
        
        # Use the hip center as the person's position (most stable point)
        left_hip = landmarks[self.LEFT_HIP]
        right_hip = landmarks[self.RIGHT_HIP]
        
        # Calculate center of hips as person's position
        person_x = (left_hip.x + right_hip.x) / 2 * 100  # Convert to percentage
        person_y = (left_hip.y + right_hip.y) / 2 * 100
        
        # Also check nose position as backup
        nose = landmarks[self.NOSE]
        nose_x = nose.x * 100
        nose_y = nose.y * 100
        
        for zone in self.config.roi_zones:
            # Check if person center is in zone
            hip_in_zone = (zone.x1 <= person_x <= zone.x2 and 
                          zone.y1 <= person_y <= zone.y2)
            
            # Also accept if nose is in zone
            nose_in_zone = (zone.x1 <= nose_x <= zone.x2 and 
                           zone.y1 <= nose_y <= zone.y2)
            
            if hip_in_zone or nose_in_zone:
                self.logger.debug(
                    f"Person in ROI '{zone.name}': hip=({person_x:.1f},{person_y:.1f}), "
                    f"nose=({nose_x:.1f},{nose_y:.1f})"
                )
                return True, zone.name
        
        self.logger.debug(
            f"Person outside ROI: hip=({person_x:.1f},{person_y:.1f}), "
            f"nose=({nose_x:.1f},{nose_y:.1f})"
        )
        return False, None
    
    def _check_arm_raised(self, nose, left_shoulder, right_shoulder,
                          left_wrist, right_wrist, left_elbow, right_elbow) -> Tuple[bool, Dict]:
        """
        Check if at least one arm is raised above the head.
        
        An arm is considered raised if:
        - Wrist is above the nose (y coordinate is lower in image coords)
        - With some threshold to account for detection noise
        """
        threshold = self.config.arm_raised_threshold
        
        # Calculate if wrists are above nose
        # In image coordinates, y=0 is top, so "above" means lower y value
        left_raised = (nose.y - left_wrist.y) > threshold
        right_raised = (nose.y - right_wrist.y) > threshold
        
        # Also check if elbow is above shoulder (arm is actually up, not just wrist position)
        left_elbow_up = left_elbow.y < left_shoulder.y
        right_elbow_up = right_elbow.y < right_shoulder.y
        
        # Arm is truly raised if wrist above nose AND elbow above shoulder
        left_arm_raised = left_raised and left_elbow_up and left_wrist.visibility > 0.3
        right_arm_raised = right_raised and right_elbow_up and right_wrist.visibility > 0.3
        
        details = {
            'left_wrist_y': left_wrist.y,
            'right_wrist_y': right_wrist.y,
            'nose_y': nose.y,
            'left_raised': left_arm_raised,
            'right_raised': right_arm_raised,
            'left_wrist_visibility': left_wrist.visibility,
            'right_wrist_visibility': right_wrist.visibility,
        }
        
        detected = left_arm_raised or right_arm_raised
        
        self.logger.debug(
            f"Arm check: L_raised={left_arm_raised}, R_raised={right_arm_raised}, "
            f"nose_y={nose.y:.3f}, L_wrist_y={left_wrist.y:.3f}, R_wrist_y={right_wrist.y:.3f}"
        )
        
        return detected, details
    
    def _check_both_arms_raised(self, nose, left_shoulder, right_shoulder,
                                 left_wrist, right_wrist) -> Tuple[bool, Dict]:
        """Check if both arms are raised above shoulders."""
        threshold = self.config.arm_raised_threshold
        
        left_raised = (left_shoulder.y - left_wrist.y) > threshold
        right_raised = (right_shoulder.y - right_wrist.y) > threshold
        
        details = {
            'left_raised': left_raised,
            'right_raised': right_raised,
        }
        
        detected = left_raised and right_raised
        
        self.logger.debug(
            f"Both arms check: L={left_raised}, R={right_raised}"
        )
        
        return detected, details
    
    def draw_landmarks(self, frame: np.ndarray, results) -> np.ndarray:
        """Draw pose landmarks on frame for debugging."""
        annotated = frame.copy()
        h, w = annotated.shape[:2]
        
        # Draw ROI zones first (so they appear behind landmarks)
        if self.config.roi_enabled and self.config.roi_zones:
            for zone in self.config.roi_zones:
                x1 = int(zone.x1 * w / 100)
                y1 = int(zone.y1 * h / 100)
                x2 = int(zone.x2 * w / 100)
                y2 = int(zone.y2 * h / 100)
                
                # Draw rectangle
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 255), 2)
                
                # Draw zone name
                cv2.putText(annotated, zone.name, (x1 + 5, y1 + 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # Draw pose landmarks
        if results and results.pose_landmarks:
            mp_drawing.draw_landmarks(
                annotated,
                results.pose_landmarks,
                mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=mp_drawing.DrawingSpec(
                    color=(0, 255, 0), thickness=2, circle_radius=3
                ),
                connection_drawing_spec=mp_drawing.DrawingSpec(
                    color=(255, 0, 0), thickness=2
                )
            )
        
        return annotated
    
    def close(self):
        """Release MediaPipe resources."""
        self.pose.close()
        self.logger.debug("Gesture detector closed")


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
        
        self.logger.debug(
            f"Detection window initialized: duration={config.detection_duration_seconds}s, "
            f"threshold={config.detection_threshold_percent}%, "
            f"cooldown={config.cooldown_seconds}s"
        )
    
    def add_detection(self, detected: bool, timestamp: Optional[datetime] = None) -> bool:
        """Add a detection result and check if event should be triggered."""
        if timestamp is None:
            timestamp = datetime.now()
        
        with self.lock:
            self.detections.append((timestamp, detected))
            
            window_start = timestamp - timedelta(seconds=self.config.detection_duration_seconds)
            while self.detections and self.detections[0][0] < window_start:
                self.detections.popleft()
            
            if self.last_event_time:
                cooldown_end = self.last_event_time + timedelta(seconds=self.config.cooldown_seconds)
                if timestamp < cooldown_end:
                    remaining = (cooldown_end - timestamp).total_seconds()
                    self.logger.debug(f"In cooldown: {remaining:.1f}s remaining")
                    return False
            
            if len(self.detections) < 2:
                return False
            
            positive_count = sum(1 for _, d in self.detections if d)
            total_count = len(self.detections)
            percentage = (positive_count / total_count) * 100
            
            self.logger.debug(
                f"Detection window: {positive_count}/{total_count} = {percentage:.1f}% "
                f"(threshold: {self.config.detection_threshold_percent}%)"
            )
            
            if total_count >= 2:
                window_duration = (self.detections[-1][0] - self.detections[0][0]).total_seconds()
                
                if window_duration >= self.config.detection_duration_seconds * 0.9:
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
        
        self.channel = extract_channel_from_url(config.rtsp_url)
        self.logger.info(f"Extracted channel from RTSP URL: {self.channel}")
    
    def connect(self) -> bool:
        """Connect to MQTT broker."""
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"gesture_detection_{self.channel}"
            )
            
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            if self.config.mqtt_username:
                self.client.username_pw_set(
                    self.config.mqtt_username,
                    self.config.mqtt_password
                )
                self.logger.debug(f"MQTT credentials set for user: {self.config.mqtt_username}")
            
            self.logger.info(
                f"Connecting to MQTT broker: {self.config.mqtt_host}:{self.config.mqtt_port}"
            )
            self.client.connect(
                self.config.mqtt_host,
                self.config.mqtt_port,
                keepalive=60
            )
            
            self.client.loop_start()
            
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
    
    def publish_gesture_event(self, gesture_type: str = "arm_raised") -> bool:
        """Publish gesture detection event to MQTT."""
        if not self.client or not self.connected:
            self.logger.error("Cannot publish: MQTT not connected")
            return False
        
        try:
            payload = json.dumps({
                "channel": self.channel,
                "gesture": gesture_type
            })
            
            result = self.client.publish(
                self.config.mqtt_topic,
                payload,
                qos=1
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
        
        self.frame_width = 0
        self.frame_height = 0
        self.fps = 0
    
    def connect(self) -> bool:
        """Connect to RTSP stream."""
        redacted_url = re.sub(r'://[^:]+:[^@]+@', '://[REDACTED]@', self.config.rtsp_url)
        self.logger.info(f"Connecting to RTSP stream: {redacted_url}")
        
        try:
            self.cap = cv2.VideoCapture(self.config.rtsp_url, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            if not self.cap.isOpened():
                self.logger.error("Failed to open RTSP stream")
                return False
            
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
        """Read a frame from the RTSP stream."""
        if not self.cap or not self.connected:
            return None
        
        try:
            ret, frame = self.cap.read()
            
            if not ret or frame is None:
                self.logger.warning("Failed to read frame from RTSP stream")
                self.connected = False
                return None
            
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
        """Attempt to reconnect to RTSP stream."""
        self.reconnect_attempts += 1
        
        max_attempts = self.config.rtsp_max_reconnect_attempts
        if max_attempts > 0 and self.reconnect_attempts > max_attempts:
            self.logger.error(f"Max reconnect attempts ({max_attempts}) exceeded")
            return False
        
        self.logger.info(f"Reconnecting to RTSP stream (attempt {self.reconnect_attempts})...")
        
        self.disconnect()
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

class GestureDetectionService:
    """Main service orchestrating gesture detection."""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = setup_logging(config)
        
        self.logger.info("=" * 60)
        self.logger.info("Gesture Detection Service Starting")
        self.logger.info(f"Gesture type: {config.gesture_type}")
        self.logger.info("=" * 60)
        
        # Initialize components
        self.rtsp = RTSPStream(config, self.logger)
        self.mqtt = MQTTPublisher(config, self.logger)
        self.detector = GestureDetector(config, self.logger)
        self.detection_window = DetectionWindow(config, self.logger)
        
        # IR preprocessor (optional)
        self.preprocessor: Optional[IRPreprocessor] = None
        if config.ir_mode_enabled:
            self.preprocessor = IRPreprocessor(config, self.logger)
            self.logger.info("IR/Low-light preprocessing enabled")
        
        # Control flags
        self.running = False
        self.stop_event = Event()
        
        # Debug frame saving
        self.last_debug_save = 0.0
        if config.debug_save_frames:
            self.logger.info(f"Debug frame saving enabled: {config.debug_frame_path}")
        
        # Statistics
        self.stats = {
            'frames_processed': 0,
            'gestures_detected': 0,
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
        
        if not self.mqtt.connect():
            self.logger.error("Failed to connect to MQTT broker, exiting")
            return False
        
        if not self.rtsp.connect():
            self.logger.error("Failed to connect to RTSP stream, exiting")
            self.mqtt.disconnect()
            return False
        
        self.running = True
        self.stats['start_time'] = datetime.now()
        
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
                if not self.rtsp.connected:
                    self.logger.warning("RTSP connection lost, attempting reconnect...")
                    if not self.rtsp.reconnect():
                        self.logger.error("Failed to reconnect to RTSP stream")
                        break
                    self.detection_window.reset()
                    continue
                
                if not self.mqtt.connected:
                    self.logger.warning("MQTT connection lost, attempting reconnect...")
                    if not self.mqtt.connect():
                        self.logger.warning("MQTT reconnect failed, will retry...")
                        time.sleep(self.config.mqtt_reconnect_delay_seconds)
                        continue
                
                current_time = time.time()
                elapsed = current_time - last_process_time
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
                last_process_time = time.time()
                
                frame = self.rtsp.read_frame()
                if frame is None:
                    continue
                
                frame_count += 1
                
                if self.config.frame_skip > 0 and frame_count % (self.config.frame_skip + 1) != 0:
                    continue
                
                # Preprocess for IR/low-light
                if self.preprocessor:
                    frame_rgb = self.preprocessor.preprocess(frame)
                else:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Detect gesture
                gesture_detected, details, detection_results = self.detector.detect_gesture(frame_rgb)
                
                self.stats['frames_processed'] += 1
                
                if gesture_detected:
                    self.stats['gestures_detected'] += 1
                    if self.config.log_detection_events:
                        self.logger.info(f"Gesture detected: {self.config.gesture_type}")
                
                # Update detection window
                if self.detection_window.add_detection(gesture_detected):
                    if self.mqtt.publish_gesture_event(self.config.gesture_type):
                        self.stats['events_sent'] += 1
                        self.logger.info(
                            f"MQTT event sent! Total events: {self.stats['events_sent']}"
                        )
                
                # Save debug frames if enabled
                if self.config.debug_save_frames:
                    self._save_debug_frame(frame, frame_rgb, detection_results, gesture_detected)
                
                # Log frame stats periodically
                if self.config.log_frame_stats and self.stats['frames_processed'] % 100 == 0:
                    self._log_stats()
                
            except Exception as e:
                self.logger.error(f"Processing loop error: {e}", exc_info=True)
                time.sleep(1)
        
        self.logger.info("Processing loop ended")
        self._log_stats()
    
    def _save_debug_frame(self, original_frame: np.ndarray, processed_frame: np.ndarray,
                          detection_results, gesture_detected: bool):
        """Save debug frames periodically for troubleshooting."""
        current_time = time.time()
        
        if current_time - self.last_debug_save < self.config.debug_save_interval:
            return
        
        self.last_debug_save = current_time
        
        try:
            os.makedirs(self.config.debug_frame_path, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            detected_str = "DETECTED" if gesture_detected else "none"
            
            # Save original frame
            original_path = os.path.join(
                self.config.debug_frame_path,
                f"original_{timestamp}_{detected_str}.jpg"
            )
            cv2.imwrite(original_path, original_frame)
            
            # Save preprocessed frame
            processed_bgr = cv2.cvtColor(processed_frame, cv2.COLOR_RGB2BGR)
            processed_path = os.path.join(
                self.config.debug_frame_path,
                f"processed_{timestamp}_{detected_str}.jpg"
            )
            cv2.imwrite(processed_path, processed_bgr)
            
            # Save annotated frame with ROI zones and pose landmarks (if any)
            # Always draw ROI zones, draw pose only if detected
            annotated = self.detector.draw_landmarks(processed_frame, detection_results)
            annotated_bgr = cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR)
            annotated_path = os.path.join(
                self.config.debug_frame_path,
                f"annotated_{timestamp}_{detected_str}.jpg"
            )
            cv2.imwrite(annotated_path, annotated_bgr)
            
            has_pose = detection_results and detection_results.pose_landmarks
            self.logger.info(f"Debug frames saved: {timestamp} (pose={'yes' if has_pose else 'no'}, ROI={'yes' if self.config.roi_enabled else 'no'})")
            
            self._cleanup_debug_frames()
            
        except Exception as e:
            self.logger.error(f"Failed to save debug frame: {e}")
    
    def _cleanup_debug_frames(self):
        """Remove old debug frames to prevent disk fill."""
        try:
            import glob
            pattern = os.path.join(self.config.debug_frame_path, "*.jpg")
            files = sorted(glob.glob(pattern), key=os.path.getmtime)
            
            max_files = 60
            if len(files) > max_files:
                for f in files[:-max_files]:
                    os.remove(f)
        except Exception as e:
            self.logger.debug(f"Debug frame cleanup error: {e}")
    
    def _log_stats(self):
        """Log current statistics."""
        runtime = (datetime.now() - self.stats['start_time']).total_seconds()
        fps = self.stats['frames_processed'] / runtime if runtime > 0 else 0
        
        window_stats = self.detection_window.get_stats()
        
        self.logger.info(
            f"Stats: frames={self.stats['frames_processed']}, "
            f"gestures={self.stats['gestures_detected']}, "
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
    config = Config.load()
    
    if not config.rtsp_url:
        print("ERROR: RTSP_URL is required", file=sys.stderr)
        sys.exit(1)
    
    service = GestureDetectionService(config)
    
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
