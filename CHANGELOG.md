# Changelog

All notable changes to the Gesture Detection Add-on will be documented in this file.

## [1.1.2] - 2025-12-30

### Added
- **ROI (Region of Interest) filtering** - now active!
- Define zones where detection should happen, ignore the rest
- ROI zones drawn on debug frames (yellow rectangles)
- Zone name shown in detection logs

### Changed
- ROI enabled by default with example "walkway" zone
- Debug frames now show ROI zones for easy tuning

## [1.1.1] - 2025-12-30

### Added
- **Pose validation** to filter false positives (like cars detected as people)
- New settings: `min_pose_height_ratio`, `min_landmark_visibility`, `validate_pose_anatomy`
- Anatomical checks: head above shoulders, reasonable body proportions
- Detailed validation logging in debug mode

### Fixed
- False positives on objects like cars that MediaPipe incorrectly detects as humans
- Better filtering of low-quality pose detections

## [1.1.0] - 2025-12-30

### Changed
- **BREAKING**: Switched from hand detection to **pose detection**
- Now detects **raised arm above head** gesture instead of open palm
- Works at 10-20 meter distances (pose detection is more robust than hand detection)
- Renamed addon to "Gesture Detection"

### Added
- New gesture types: `arm_raised`, `both_arms_raised`
- `arm_raised_threshold` setting to tune sensitivity
- `require_both_arms` option
- ROI (Region of Interest) configuration (prepared for future use)
- Pose landmark visualization in debug frames
- MQTT payload now includes `gesture` field

### Fixed
- Detection now works reliably at long distances (10-20m)
- Better handling of IR camera images

## [1.0.3] - 2025-12-30

### Changed
- Lowered default confidence_threshold to 0.3 for better IR detection
- Increased default max_frame_width to 1280 for better detail
- Disabled IR preprocessing by default (raw images often work better)

## [1.0.2] - 2025-12-30

### Added
- Debug frame saving feature
- Detailed finger-by-finger detection logging
- Hand landmark visualization on debug frames

### Fixed
- MediaPipe solutions import compatibility

## [1.0.1] - 2025-12-30

### Fixed
- Removed remote image reference for local addon builds
- Fixed MediaPipe import compatibility with Debian base image

## [1.0.0] - 2025-12-30

### Added
- Initial release
- Open palm detection using MediaPipe Hands
- RTSP stream support
- MQTT event publishing
- IR/Low-light camera support
- Configurable detection parameters
