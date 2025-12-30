# Open Palm Detection Add-on for Home Assistant

Detects open palm gestures from RTSP camera streams (including IR/low-light cameras) and sends MQTT events to Home Assistant.

## Features

- **Open Palm Detection**: Uses MediaPipe for accurate hand landmark detection
- **IR/Low-Light Support**: CLAHE preprocessing and brightness/contrast adjustments for grayscale IR cameras
- **MQTT Integration**: Sends events to Home Assistant via MQTT
- **Resource Efficient**: Configurable frame skipping and resolution limits for low-power devices
- **Configurable Detection**: Adjustable detection duration, threshold, and cooldown periods
- **Auto-Reconnect**: Automatic reconnection for both RTSP and MQTT on connection loss
- **Verbose Logging**: Detailed logs for debugging and tuning

## Installation

1. Copy this addon folder to your Home Assistant `/addons/` directory
2. In Home Assistant, go to **Settings → Add-ons → Add-on Store**
3. Click the three dots menu and select **Reload**
4. Find "Open Palm Detection" in the local add-ons section
5. Click **Install**
6. Configure the addon (see Configuration section below)
7. Start the addon

## Configuration

### RTSP Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `rtsp_url` | Full RTSP URL including credentials | `rtsp://user:pass@192.168.1.7/ISAPI/Streaming/channels/101` |

### MQTT Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `mqtt_host` | MQTT broker hostname | `core-mosquitto` |
| `mqtt_port` | MQTT broker port | `1883` |
| `mqtt_username` | MQTT username | (empty) |
| `mqtt_password` | MQTT password | (empty) |
| `mqtt_topic` | Topic to publish events | `home/gesture/detect-hand` |

### Detection Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `detection_duration_seconds` | Duration palm must be visible | `4.0` |
| `detection_threshold_percent` | Percentage of frames with palm required | `80` |
| `cooldown_seconds` | Cooldown after sending event | `5.0` |
| `confidence_threshold` | Minimum detection confidence (0.1-1.0) | `0.5` |

### Performance Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `frame_skip` | Process every Nth frame (0=all) | `2` |
| `max_frame_width` | Maximum frame width for processing | `640` |
| `processing_fps` | Target processing FPS | `10` |

### IR/Low-Light Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `ir_mode_enabled` | Enable IR/low-light preprocessing | `true` |
| `clahe_clip_limit` | CLAHE contrast limit (1.0-10.0) | `3.0` |
| `clahe_grid_size` | CLAHE tile grid size | `8` |
| `brightness_boost` | Brightness multiplier (0.5-3.0) | `1.2` |
| `contrast_boost` | Contrast multiplier (0.5-3.0) | `1.3` |

### Logging Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `log_level` | Log verbosity (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `log_detection_events` | Log each palm detection | `true` |
| `log_frame_stats` | Log frame processing statistics | `false` |

### Connection Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `rtsp_reconnect_delay_seconds` | Delay between RTSP reconnect attempts | `5` |
| `rtsp_max_reconnect_attempts` | Max reconnect attempts (0=infinite) | `0` |
| `mqtt_reconnect_delay_seconds` | Delay between MQTT reconnect attempts | `5` |

## MQTT Event Format

When an open palm is detected for the configured duration, the addon publishes:

**Topic**: `home/gesture/detect-hand` (configurable)

**Payload**:
```json
{"channel": "101"}
```

The channel number is extracted from the RTSP URL path.

## Tuning for IR/Low-Light Cameras

If detection is unreliable in IR mode:

1. **Enable debug logging**: Set `log_level` to `DEBUG` and `log_frame_stats` to `true`
2. **Adjust CLAHE**: Increase `clahe_clip_limit` (try 4.0-6.0) for more contrast
3. **Boost brightness**: Increase `brightness_boost` if image is too dark
4. **Lower confidence**: Reduce `confidence_threshold` to 0.3-0.4 for more detections
5. **Reduce threshold**: Lower `detection_threshold_percent` to 60-70%

## Resource Usage

The addon is designed for low-power devices like Intel N95. To reduce CPU usage:

- Increase `frame_skip` (e.g., 3-5)
- Reduce `max_frame_width` (e.g., 480)
- Reduce `processing_fps` (e.g., 5)

## Troubleshooting

### No RTSP connection
- Check RTSP URL format: `rtsp://user:pass@ip/path`
- Verify camera is accessible from Home Assistant host
- Check firewall rules

### No palm detections
- Enable DEBUG logging
- Verify camera image quality
- Adjust IR preprocessing settings
- Lower `confidence_threshold`

### High CPU usage
- Increase `frame_skip`
- Reduce `max_frame_width`
- Reduce `processing_fps`

### MQTT connection issues
- Verify MQTT broker is running
- Check username/password
- Use `core-mosquitto` for Home Assistant's built-in broker

## License

MIT License - See LICENSE file for details.
