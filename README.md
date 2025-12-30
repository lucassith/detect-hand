# Gesture Detection Add-on for Home Assistant

Detects raised arm gestures from RTSP camera streams (including IR/low-light cameras) and sends MQTT events to Home Assistant. Designed to work at **10-20 meter distances**.

## Features

- **Raised Arm Detection**: Uses MediaPipe Pose for full-body pose detection
- **Long Distance**: Works at 10-20 meters (unlike hand detection)
- **IR/Low-Light Support**: Optional preprocessing for grayscale IR cameras
- **MQTT Integration**: Sends events to Home Assistant via MQTT
- **Configurable Detection**: Adjustable duration, threshold, and cooldown
- **Debug Frame Saving**: Save annotated frames for troubleshooting
- **ROI Zones**: Define detection regions (prepared for future use)

## Installation

1. Copy this addon folder to your Home Assistant `/addons/` directory
2. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
3. Click the three dots menu and select **Reload**
4. Find "Gesture Detection" in the local add-ons section
5. Click **Install**
6. Configure the addon (see Configuration section below)
7. Start the addon

## Configuration

### RTSP Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `rtsp_url` | Full RTSP URL with credentials | `rtsp://user:pass@ip/path` |

### MQTT Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `mqtt_host` | MQTT broker hostname | `core-mosquitto` |
| `mqtt_port` | MQTT broker port | `1883` |
| `mqtt_username` | MQTT username | (empty) |
| `mqtt_password` | MQTT password | (empty) |
| `mqtt_topic` | Topic to publish events | `home/gesture/detect-hand` |

### Gesture Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `gesture_type` | Type of gesture (`arm_raised`, `both_arms_raised`) | `arm_raised` |
| `arm_raised_threshold` | How far above nose wrist must be (0.0-0.5) | `0.15` |
| `require_both_arms` | Require both arms raised | `false` |

### Detection Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `detection_duration_seconds` | Duration gesture must be held | `4.0` |
| `detection_threshold_percent` | Percentage of frames with gesture | `80` |
| `cooldown_seconds` | Cooldown after sending event | `5.0` |
| `confidence_threshold` | Minimum pose detection confidence | `0.3` |

### Performance Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `frame_skip` | Process every Nth frame | `2` |
| `max_frame_width` | Maximum frame width | `1280` |
| `processing_fps` | Target processing FPS | `10` |

### ROI Configuration (Future)

| Option | Description | Default |
|--------|-------------|---------|
| `roi_enabled` | Enable ROI filtering | `false` |
| `roi_zones` | List of detection zones | `[]` |

## MQTT Event Format

When a gesture is detected for the configured duration:

**Topic**: `home/gesture/detect-hand` (configurable)

**Payload**:
```json
{"channel": "101", "gesture": "arm_raised"}
```

## Example Automation

```yaml
automation:
  - alias: "Toggle Lights on Arm Raise"
    trigger:
      - platform: mqtt
        topic: "home/gesture/detect-hand"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.channel == '101' }}"
    action:
      - service: light.toggle
        target:
          entity_id: light.entrance
```

## Troubleshooting

### No detections at all
1. Enable DEBUG logging and `debug_save_frames: true`
2. Check `/share/detect-hand-debug/` for saved frames
3. Look for pose landmarks in annotated frames
4. Lower `confidence_threshold` to 0.2

### False positives
1. Increase `arm_raised_threshold` to 0.2-0.25
2. Increase `detection_duration_seconds` to 5-6
3. Increase `detection_threshold_percent` to 85-90

### High CPU usage
1. Increase `frame_skip` to 3-5
2. Reduce `max_frame_width` to 960
3. Reduce `processing_fps` to 5

## License

MIT License
