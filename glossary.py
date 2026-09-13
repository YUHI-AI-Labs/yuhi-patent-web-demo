"""Small, hand-built English -> Japanese glossary for common mechanical parts.

This is a deliberate shortcut: the real product's Japanese semantic labels
come from an AI interpretation step (services/runtime/src/graph/interpret.ts)
that this public demo does not run (no AI is configured here, matching the
"AIが設定されていない" honest-degradation path the desktop app itself uses).
Without it, an uploaded STEP file's raw part names are whatever the CAD
author typed - often English. This glossary buys back some recall against a
Japanese-language patent corpus for the common case without pretending to
be a translation model.
"""

import re

GLOSSARY = {
    "housing": "ハウジング",
    "bearing": "軸受",
    "shaft": "回転軸",
    "rotating shaft": "回転軸",
    "sensor": "センサ",
    "temperature sensor": "温度センサ",
    "cover": "カバー",
    "spring": "ばね",
    "gear": "歯車",
    "motor": "モーター",
    "valve": "バルブ",
    "pump": "ポンプ",
    "frame": "フレーム",
    "bracket": "ブラケット",
    "mount": "マウント",
    "seal": "シール",
    "gasket": "ガスケット",
    "wheel": "車輪",
    "joint": "接合部",
    "arm": "アーム",
    "plate": "プレート",
    "block": "ブロック",
    "cylinder": "シリンダー",
    "piston": "ピストン",
    "screw": "ねじ",
    "bolt": "ボルト",
    "nut": "ナット",
    "washer": "ワッシャー",
    "flange": "フランジ",
    "disk": "ディスク",
    "disc": "ディスク",
    "ring": "リング",
    "case": "ケース",
    "body": "本体",
    "base": "ベース",
    "panel": "パネル",
    "rail": "レール",
    "rod": "ロッド",
    "pin": "ピン",
    "hinge": "ヒンジ",
    "battery": "バッテリー",
    "camera": "カメラ",
    "lens": "レンズ",
    "fan": "ファン",
    "actuator": "アクチュエーター",
    "controller": "コントローラー",
}


def to_search_terms(name: str) -> list[str]:
    """Turn a raw CAD part name into a small set of Japanese-leaning search terms."""
    if not name:
        return []
    cleaned = re.sub(r"[_\-]+", " ", name).strip().lower()
    cleaned = re.sub(r"\d+", " ", cleaned).strip()
    terms: list[str] = []
    if cleaned in GLOSSARY:
        terms.append(GLOSSARY[cleaned])
    for word in cleaned.split():
        if word in GLOSSARY and GLOSSARY[word] not in terms:
            terms.append(GLOSSARY[word])
    if not terms and cleaned:
        # No glossary hit: fall back to the cleaned original text. It likely
        # will not match Japanese patent text, and that is shown honestly.
        terms.append(cleaned)
    return terms
