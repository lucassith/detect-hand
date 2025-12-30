# Changelog

All notable changes to the Open Palm Detection Add-on will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.2] - 2025-12-30

### Added
- Debug frame saving feature - saves original, preprocessed, and annotated frames
- Detailed finger-by-finger detection logging (Thumb:Y, Index:N, etc.)
- Hand landmark visualization on debug frames
- Automatic debug frame cleanup to prevent disk fill

### Fixed
- Improved hand detection logging to show when hands are found but not recognized as open palm
- MediaPipe solutions import compatibility fix

## [1.0.1] - 2025-12-30

### Fixed
- Removed remote image reference for local addon builds
- Fixed MediaPipe import compatibility with Debian base image
- Added protobuf version constraint for MediaPipe compatibility

## [1.0.0] - 2025-12-30

### Added
- Initial release
- Open palm detection using MediaPipe
- RTSP stream support
- MQTT event publishing with channel number
- IR/Low-light camera support with CLAHE preprocessing
- Configurable detection duration and threshold
- Cooldown period between events
- Auto-reconnect for RTSP and MQTT connections
- Verbose logging for debugging
- Resource-efficient frame processing with configurable skip and FPS limits
- Full configuration via Home Assistant addon UI
