import json
import os
from pathlib import Path

def load_config(name: str):
    """Load a JSON config from the config/ directory.
    Returns dict or raises FileNotFoundError.
    """
    cfg_path = Path(__file__).parent / "config" / f"{name}.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Config {name}.json not found")
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_config(name: str, data: dict):
    """Save a dict as JSON under config/.
    Overwrites existing file.
    """
    cfg_path = Path(__file__).parent / "config" / f"{name}.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(cfg_path)
