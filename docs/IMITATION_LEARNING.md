# Training Spectro imitation from gameplay videos

## Goal

Train a policy that receives the same observations as the bot, for example screen frames, detected objects, HP, ammo, enemies, walls, and game state, and predicts player actions such as movement direction, attack, super, gadget, and aiming angle.

## Data sources

Best quality data comes from recordings where actions are known:

1. Record gameplay while also logging keyboard, mouse, joystick, or ADB touch inputs.
2. Save frames with timestamps.
3. Save actions with timestamps.
4. Align every frame to the closest action.

Plain videos without input logs are useful but weaker. For those, actions must be inferred from motion and button animations, which is noisy.

## Recommended data format

```text
datasets/imitation/
  session_001/
    frames/000001.jpg
    frames/000002.jpg
    actions.jsonl
    meta.json
```

Each `actions.jsonl` row should look like this:

```json
{"t": 12.351, "frame": "frames/000123.jpg", "move_angle": 90, "move_strength": 1.0, "aim_angle": 15, "attack": 0, "super": 0, "gadget": 0, "state": "match", "brawler": "shelly"}
```

## Video-only pipeline

If you only have videos of strong players:

1. Extract frames with ffmpeg.
2. Run Spectro vision detectors on frames.
3. Estimate player movement by tracking the player center between frames.
4. Estimate attacks by detecting projectile spawn, ammo reduction, button flash, or aim joystick movement if visible.
5. Filter uncertain labels instead of training on bad labels.
6. Train first on high-confidence segments only.

## Model options

Start simple:

1. Use current handcrafted features from `imitation_features.py`.
2. Train a small MLP or gradient boosting model for movement and actions.
3. Later move to CNN plus LSTM or transformer if you have many hours of data.

A practical output head:

```text
move_angle_class: 16 directions plus no movement
attack: yes/no
super: yes/no
gadget: yes/no
aim_angle_class: 32 directions
```

## Training stages

1. Behavioral cloning on human data.
2. Offline validation by replaying videos and comparing predicted actions.
3. Safe live test with attack disabled, movement only.
4. Full live test with low-risk modes.
5. Aggregate failures, add them to dataset, retrain. This is DAgger-style improvement.

## Important notes

Use Brawler-specific features. Different brawlers need different ranges, reload timing, attack width, and aggression. Also store map mode and current game state, because a good action in lobby or matchmaking is not a good action in match.
