# Changelog

All notable changes to the Gesture Detection Add-on will be documented in this file.

## [1.1.9] - 2025-12-30

### Added
- **New `ir_preprocessing_mode`** setting with three options:
  - `none`: Just convert grayscale to RGB (preserves original)
  - `minimal`: Light CLAHE only (recommended for good IR cameras)
  - `full`: Full pipeline (denoise, gamma, CLAHE, brightness/contrast)

### Changed
- Default mode is now `minimal` to prevent over-processing
- Reduced default CLAHE clip limit to 2.0
- Disabled brightness/contrast boost by default (set to 1.0)
- Disabled gamma correction by default (set to 1.0)

### Fixed
- Over-aggressive IR preprocessing that was blowing out images

## [1.1.8] - 2025-12-30

### Fixed
- Schema validation now allows `arm_raised_threshold` as low as 0.01

## [1.1.7] - 2025-12-30

### Fixed
- **Lowered `arm_raised_threshold` from 0.15 to 0.02** - was too strict
- Previously required wrist to be 15% of frame height above nose
- Now just requires wrist to be 2% above nose

## [1.1.6] - 2025-12-30

### Added
- **Enhanced IR preprocessing** to improve pose detection in IR/night mode
- `ir_gamma_correction` - brightens dark areas (default: 0.8)
- `ir_denoise` - reduces IR camera noise (default: true)
- Improved preprocessing pipeline: Denoise → Gamma → CLAHE → Brightness/Contrast

### Changed
- IR mode now enabled by default with optimized settings
- Increased default `clahe_clip_limit` to 4.0
- Increased default `brightness_boost` to 1.4
- Increased default `contrast_boost` to 1.5

## [1.1.5] - 2025-12-30

### Changed
- Adjusted default ROI zone to better cover walkway area

## [1.1.4] - 2025-12-30

### Added
- `debug_draw_roi` option to control whether ROI zones are drawn on debug frames
- Default: true (ROI zones are drawn)

## [1.1.3] - 2025-12-30

### Fixed
- ROI zones now always drawn on debug frames (even when no pose detected)
- Added debug logging for ROI zone loading
- Coordinates are percentages (0-100), not pixels

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
