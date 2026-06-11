# Spectro refactor plan

This project should be refactored in stages to avoid breaking emulator control, vision inference, lobby automation, and trophy logic at the same time.

## Target tree

```text
spectro/
  main.py
  app/
    runtime_control.py
    discord_control.py
  core/
    config.py
    state.py
    events.py
    logging.py
  game/
    stage_manager.py
    trophy_tracker.py
    brawler_queue.py
    brawltracker_client.py
  vision/
    detector.py
    state_finder.py
    hp_estimator.py
    datasets.py
  control/
    window_controller.py
    navigation.py
    lobby_automation.py
    play.py
    imitation_policy.py
    imitation_features.py
    adaptive_brain.py
  gui/
    hub.py
    select_brawler.py
  integrations/
    discord_notifier.py
    brawltracker.py
  tools/
  tests/
  configs/
  assets/
```

## Migration order

1. Add package folders and compatibility wrappers, no behavior change.
2. Move config loading into `spectro/core/config.py`.
3. Move Brawltracker parsing into `spectro/game/brawltracker_client.py`.
4. Split `stage_manager.py` into queue, trophy sync, and state handlers.
5. Split `play.py` into perception, decision, aiming, movement, and skill usage.
6. Keep `main.py` at `spectro/main.py`; move runtime panel into `spectro/app` and movement/policy code into `spectro/control`.
7. Update tests after every step.
8. Remove compatibility wrappers only after stable test runs.

## Rule

Do not move everything in one commit. The current code controls a live emulator, so large untested moves can silently break input, frame capture, or match-state handling.
