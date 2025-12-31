# Open Palm Detection Add-on Documentation

## Overview

This add-on monitors an RTSP camera stream and detects when someone shows an open palm (all fingers extended). When an open palm is detected for a configurable duration, an MQTT event is published that can trigger automations in Home Assistant.

## Use Cases

- **Hands-free light control**: Wave at a camera to turn on/off lights
- **Smart doorbell**: Wave at the entrance camera to trigger a notification
- **Accessibility**: Control devices with gestures for users with mobility limitations
- **Security**: Trigger alerts when specific gestures are detected

## How It Works

1. **Stream Capture**: The add-on connects to your RTSP camera stream
2. **Frame Processing**: Each frame is analyzed for hand landmarks using MediaPipe
3. **Palm Detection**: The algorithm checks if all five fingers are extended (open palm)
4. **Duration Tracking**: Detections are tracked over a sliding time window
5. **Event Trigger**: When the detection threshold is met, an MQTT message is published
6. **Cooldown**: A cooldown period prevents duplicate events

## IR/Low-Light Cameras

This add-on is specifically designed to work with IR security cameras. The preprocessing pipeline includes:

1. **Grayscale conversion**: IR cameras typically output grayscale images
2. **CLAHE (Contrast Limited Adaptive Histogram Equalization)**: Enhances local contrast without amplifying noise
3. **Brightness adjustment**: Boosts overall image brightness
4. **Contrast adjustment**: Enhances the difference between light and dark areas

### Tuning for Your Camera

Every camera is different. Here's how to tune the settings:

1. **Start with DEBUG logging** to see detection confidence values
2. **Adjust CLAHE clip limit**:
   - If image looks washed out: decrease to 2.0-2.5
   - If image lacks contrast: increase to 4.0-5.0
3. **Adjust brightness/contrast boost**:
   - If hands aren't detected: try increasing both to 1.3-1.5
   - If there are too many false positives: decrease to 1.0-1.1
4. **Lower confidence threshold** for IR cameras (0.3-0.5 often works better than 0.5-0.7)

## Resource Usage

The add-on is designed for devices like Intel N95 or Raspberry Pi 4. Typical resource usage:

| Setting | CPU Usage | Memory |
|---------|-----------|--------|
| Default (640px, 10 FPS, skip 2) | ~30-40% | ~300MB |
| Low power (480px, 5 FPS, skip 4) | ~15-20% | ~250MB |
| High accuracy (640px, 15 FPS, skip 1) | ~50-60% | ~350MB |

## Example Automation

```yaml
automation:
  - alias: "Living Room Light Toggle on Palm Wave"
    trigger:
      - platform: mqtt
        topic: "home/gesture/detect-hand"
    condition:
      - condition: template
        value_template: "{{ trigger.payload_json.channel == '101' }}"
    action:
      - service: light.toggle
        target:
          entity_id: light.living_room
```

## Troubleshooting

### No detections

1. Check RTSP stream is accessible: try opening in VLC
2. Enable DEBUG logging and check for errors
3. Verify camera resolution is at least 320x240
4. For IR cameras, ensure IR LEDs are active
5. Try lowering `confidence_threshold` to 0.3

### Too many false positives

1. Increase `confidence_threshold` to 0.6-0.7
2. Increase `detection_threshold_percent` to 85-90%
3. Increase `detection_duration_seconds` to 5-6 seconds
4. Check for reflective surfaces in camera view

### High CPU usage

1. Increase `frame_skip` to 3-5
2. Reduce `max_frame_width` to 480
3. Reduce `processing_fps` to 5
4. Disable `log_frame_stats` and set `log_level` to INFO

### MQTT connection issues

1. Verify MQTT broker is running: `Settings → Add-ons → Mosquitto broker`
2. Check username/password are correct
3. For Home Assistant's built-in broker, use `core-mosquitto` as host
4. Check the broker allows connections from add-ons

### RTSP connection drops

1. Increase `rtsp_reconnect_delay_seconds` to 10-15
2. Check network stability between Home Assistant and camera
3. Some cameras limit concurrent connections - close other RTSP viewers
4. Try using substream URL if main stream is too high resolution

## Technical Details

### Hand Landmark Detection

The add-on uses MediaPipe's hand landmark model which detects 21 points on each hand:

- Wrist (1 point)
- Thumb (4 points: CMC, MCP, IP, TIP)
- Index finger (4 points: MCP, PIP, DIP, TIP)
- Middle finger (4 points)
- Ring finger (4 points)
- Pinky (4 points)

### Open Palm Algorithm

A palm is considered "open" when:

1. At least 4 of 5 fingers have their TIP above their PIP joint (extended)
2. The thumb TIP is extended away from the palm

This allows for slight natural finger curl while still requiring an intentional open palm gesture.

### Detection Window

The sliding window algorithm:

1. Records each frame's detection result with timestamp
2. Removes samples older than `detection_duration_seconds`
3. Calculates percentage of positive detections
4. Triggers event when percentage exceeds threshold and window is full

## Support

For issues and feature requests, please check:

1. The add-on logs (Settings → Add-ons → Open Palm Detection → Logs)
2. Enable DEBUG logging for detailed diagnostics
3. Check network connectivity to camera and MQTT broker
