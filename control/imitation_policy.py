"""Numpy-only inference for the imitation movement policy.

Drop these three files into the bot project root:
    imitation_features.py
    imitation_policy.py
    imitation_policy.npz

No ONNX / torch needed - inference is a tiny numpy MLP forward pass.

Typical use inside play.py:

    from imitation_policy import get_policy
    pol = get_policy()                       # loads once (cached)
    if pol is not None:
        out = pol.predict(player_pos, enemy_centers, teammate_centers,
                          wall_boxes, frame_w, frame_h)
        if out and out["move_class"] != 0 and out["confidence"] >= 0.30:
            desired_angle = out["angle"]     # feed into find_best_angle(...)

The policy only proposes a MOVEMENT direction. Attack/aim stays with the
bot's existing combat logic (the trained attack head is not reliable yet).
"""
from pathlib import Path
import numpy as np
from control import imitation_features as F

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent / "models" / "imitation_policy.npz")
_CACHE = {}


def _relu(x):
    return np.maximum(x, 0.0)


def _softmax(z):
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


class ImitationPolicy:
    def __init__(self, path=_DEFAULT_PATH):
        data = np.load(path)
        self.W1 = data["W1"]; self.b1 = data["b1"]
        self.W2 = data["W2"]; self.b2 = data["b2"]
        self.Wm = data["Wm"]; self.bm = data["bm"]
        self.Wa = data["Wa"]; self.ba = data["ba"]
        self.mean = data["mean"]; self.std = data["std"]
        fv = int(data["feature_version"][0])
        fd = int(data["feature_dim"][0])
        if fv != F.FEATURE_VERSION:
            raise ValueError("feature_version mismatch: model=%d code=%d"
                             % (fv, F.FEATURE_VERSION))
        if fd != F.FEATURE_DIM:
            raise ValueError("feature_dim mismatch: model=%d code=%d"
                             % (fd, F.FEATURE_DIM))
        self.dir_angles = list(data["dir_angles"])

    def predict(self, player, enemies, teammates, walls, w, h):
        """Returns dict or None (None = no player box, do not use model).

        dict keys:
            move_class : 0 = idle, 1..8 = direction
            angle      : desired movement angle in degrees, or None if idle
            confidence : softmax prob of the chosen movement class
            attack_prob: raw attack probability (NOT reliable in v1)
        """
        feats = F.featurize(player, enemies, teammates, walls, w, h)
        if feats is None:
            return None
        x = (np.asarray(feats, dtype=np.float64) - self.mean) / self.std
        a1 = _relu(x @ self.W1 + self.b1)
        a2 = _relu(a1 @ self.W2 + self.b2)
        move_logits = a2 @ self.Wm + self.bm
        atk_logit = float((a2 @ self.Wa + self.ba).ravel()[0])
        probs = _softmax(move_logits)
        cls = int(probs.argmax())
        return {
            "move_class": cls,
            "angle": F.class_to_angle(cls),
            "confidence": float(probs[cls]),
            "attack_prob": 1.0 / (1.0 + np.exp(-atk_logit)),
            "move_probs": probs.tolist(),
        }


def get_policy(path=_DEFAULT_PATH):
    """Load (and cache) the policy. Returns None if the model file is missing
    or fails to load, so the bot can safely fall back to its own logic."""
    if path in _CACHE:
        return _CACHE[path]
    try:
        pol = ImitationPolicy(path)
    except Exception as e:
        print("[imitation_policy] disabled:", e)
        pol = None
    _CACHE[path] = pol
    return pol
