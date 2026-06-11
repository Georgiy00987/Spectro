# Spectro architecture

The runtime code now lives in the `spectro` package. Root-level files are compatibility wrappers so existing scripts, tests, and `python main.py` still work.

## Main tree

```text
spectro/
  main.py                      # application entrypoint
  app/
    runtime_control.py          # minimal runtime control panel
    discord_control.py          # Discord slash-command control
  core/
    utils.py                    # config, files, shared helpers, API helpers
    logger_setup.py             # terminal/file logging bootstrap
    performance_profile.py      # performance profiles
    cuda_runtime_paths.py       # CUDA/ONNX runtime path helpers
  game/
    stage_manager.py            # game-state transitions and push flow
    trophy_observer.py          # fallback local trophy math
    brawltracker_api.py         # Brawltracker parsing client
    adaptive_brain.py           # combat adaptation state
    time_management.py          # periodic timers
  control/
    play.py                     # live gameplay policy and control actions
    imitation_policy.py         # imitation-policy inference
    imitation_features.py       # imitation feature extraction
    lobby_automation.py         # lobby and brawler selection automation
    navigation.py               # grid navigation
    window_controller.py        # emulator/scrcpy/ADB IO
  vision/
    detect.py                   # ONNX detection wrapper
    state_finder.py             # screen state recognition
    hp_estimator.py             # HP estimation
    hp_debug.py                 # HP debug helpers
  gui/
    hub.py
    login.py
    main.py
    select_brawler.py
    api.py
  integrations/
    discord_notifier.py         # Discord webhook notifications
    syncbrawlers2api.py         # Brawltracker sync script/client
    api.py                      # asset/API helpers
```

## Compatibility wrappers

Files such as `main.py`, `play.py`, `stage_manager.py`, `utils.py`, `gui/hub.py`, and `control/play.py` remain at their old paths, but only re-export from `spectro.*`. This keeps old imports working while the real implementation is organized by responsibility.

## Import rule

New code should import from `spectro.*`, for example:

```python
from spectro.game.stage_manager import StageManager
from spectro.control.play import Play
from spectro.core.utils import load_toml_as_dict
```

Do not add new logic to root-level compatibility wrappers.
