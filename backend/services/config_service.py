import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _terminal_log(message: str) -> None:
    """In ra terminal, xử lý encoding Windows."""
    try:
        print(message, flush=True)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"), flush=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = PROJECT_ROOT / "data" / "llm_config.json"

VALID_PROVIDERS = {"gemini", "openai", "openrouter", "mock"}

DEFAULT_CONFIG = {
    "llm_provider": "mock",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "openrouter_api_key": "",
    "openrouter_model": "google/gemma-3-27b-it:free",
}


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


def _ensure_config_dir() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_config_file() -> Optional[Dict[str, str]]:
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {**DEFAULT_CONFIG, **data}
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _write_config_file(config: Dict[str, str]) -> None:
    _ensure_config_dir()
    merged = {**DEFAULT_CONFIG, **config}
    CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _migrate_from_env() -> Dict[str, str]:
    """Chuyển cấu hình LLM cũ từ .env sang file JSON (chạy một lần)."""
    config = {
        "llm_provider": os.getenv("LLM_PROVIDER", DEFAULT_CONFIG["llm_provider"]).lower(),
        "gemini_api_key": os.getenv("GEMINI_API_KEY", "") or "",
        "gemini_model": os.getenv("GEMINI_MODEL", DEFAULT_CONFIG["gemini_model"]),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "") or "",
        "openai_model": os.getenv("OPENAI_MODEL", DEFAULT_CONFIG["openai_model"]),
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", "") or "",
        "openrouter_model": os.getenv("OPENROUTER_MODEL", DEFAULT_CONFIG["openrouter_model"]),
    }
    if any(
        [
            config["gemini_api_key"],
            config["openai_api_key"],
            config["openrouter_api_key"],
            config["llm_provider"] != "mock",
        ]
    ):
        _write_config_file(config)
    return config


def _load_raw_config() -> Dict[str, str]:
    file_config = _read_config_file()
    if file_config:
        return file_config
    return _migrate_from_env()


def apply_config_to_env(config: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Áp dụng cấu hình LLM vào biến môi trường để LLMService đọc được."""
    cfg = config or _load_raw_config()
    os.environ["LLM_PROVIDER"] = cfg.get("llm_provider", "mock")
    os.environ["GEMINI_API_KEY"] = cfg.get("gemini_api_key", "")
    os.environ["GEMINI_MODEL"] = cfg.get("gemini_model", DEFAULT_CONFIG["gemini_model"])
    os.environ["OPENAI_API_KEY"] = cfg.get("openai_api_key", "")
    os.environ["OPENAI_MODEL"] = cfg.get("openai_model", DEFAULT_CONFIG["openai_model"])
    os.environ["OPENROUTER_API_KEY"] = cfg.get("openrouter_api_key", "")
    os.environ["OPENROUTER_MODEL"] = cfg.get("openrouter_model", DEFAULT_CONFIG["openrouter_model"])
    return cfg


def init_llm_config() -> None:
    """Gọi khi khởi động app: load .env (telegram...) rồi overlay cấu hình LLM từ JSON."""
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)
    apply_config_to_env()


def get_llm_settings() -> Dict[str, Any]:
    cfg = _load_raw_config()
    apply_config_to_env(cfg)
    provider = cfg.get("llm_provider", "mock")
    return {
        "llm_provider": provider,
        "preferred_core": provider,
        "gemini_api_key_masked": _mask_key(cfg.get("gemini_api_key", "")),
        "openai_api_key_masked": _mask_key(cfg.get("openai_api_key", "")),
        "openrouter_api_key_masked": _mask_key(cfg.get("openrouter_api_key", "")),
        "gemini_api_key_set": bool(cfg.get("gemini_api_key")),
        "openai_api_key_set": bool(cfg.get("openai_api_key")),
        "openrouter_api_key_set": bool(cfg.get("openrouter_api_key")),
        "gemini_model": cfg.get("gemini_model", DEFAULT_CONFIG["gemini_model"]),
        "openai_model": cfg.get("openai_model", DEFAULT_CONFIG["openai_model"]),
        "openrouter_model": cfg.get("openrouter_model", DEFAULT_CONFIG["openrouter_model"]),
        "config_path": str(CONFIG_PATH),
    }


def _log_config_changes(old: Dict[str, str], new: Dict[str, str]) -> None:
    """In thay đổi cấu hình LLM ra terminal (key được mask)."""
    changes: list[str] = []

    if old.get("llm_provider") != new.get("llm_provider"):
        changes.append(f"Provider: {old.get('llm_provider')} -> {new.get('llm_provider')}")

    key_fields = [
        ("gemini_api_key", "Gemini API Key"),
        ("openai_api_key", "OpenAI API Key"),
        ("openrouter_api_key", "OpenRouter API Key"),
    ]
    for field, label in key_fields:
        if old.get(field) != new.get(field):
            old_masked = _mask_key(old.get(field, "")) or "(trống)"
            new_masked = _mask_key(new.get(field, "")) or "(trống)"
            changes.append(f"{label}: {old_masked} -> {new_masked}")

    model_fields = [
        ("gemini_model", "Gemini Model"),
        ("openai_model", "OpenAI Model"),
        ("openrouter_model", "OpenRouter Model"),
    ]
    for field, label in model_fields:
        if old.get(field) != new.get(field):
            changes.append(f"{label}: {old.get(field)} -> {new.get(field)}")

    if not changes:
        msg = "[LLM Config] Luu cau hinh - khong co thay doi"
        logger.info(msg)
        _terminal_log(msg)
        return

    header = "[LLM Config] Cau hinh AI da thay doi:"
    logger.info(header)
    _terminal_log(header)
    for line in changes:
        msg = f"  * {line}"
        logger.info(msg)
        _terminal_log(msg)

    summary = (
        f"  -> Provider dang dung: {new.get('llm_provider')} | "
        f"Gemini: {_mask_key(new.get('gemini_api_key', '')) or '-'} | "
        f"OpenAI: {_mask_key(new.get('openai_api_key', '')) or '-'} | "
        f"OpenRouter: {_mask_key(new.get('openrouter_api_key', '')) or '-'}"
    )
    logger.info(summary)
    _terminal_log(summary)


def update_llm_settings(
    llm_provider: Optional[str] = None,
    gemini_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openrouter_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
    openai_model: Optional[str] = None,
    openrouter_model: Optional[str] = None,
) -> Dict[str, Any]:
    old_cfg = dict(_load_raw_config())
    cfg = dict(old_cfg)

    if llm_provider is not None:
        provider = llm_provider.lower().strip()
        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Provider không hợp lệ: {provider}. Hợp lệ: {', '.join(VALID_PROVIDERS)}")
        cfg["llm_provider"] = provider

    if gemini_api_key is not None and gemini_api_key.strip():
        cfg["gemini_api_key"] = gemini_api_key.strip()
    if openai_api_key is not None and openai_api_key.strip():
        cfg["openai_api_key"] = openai_api_key.strip()
    if openrouter_api_key is not None and openrouter_api_key.strip():
        cfg["openrouter_api_key"] = openrouter_api_key.strip()

    if gemini_model is not None and gemini_model.strip():
        cfg["gemini_model"] = gemini_model.strip()
    if openai_model is not None and openai_model.strip():
        cfg["openai_model"] = openai_model.strip()
    if openrouter_model is not None and openrouter_model.strip():
        cfg["openrouter_model"] = openrouter_model.strip()

    _write_config_file(cfg)
    _log_config_changes(old_cfg, cfg)
    apply_config_to_env(cfg)
    return get_llm_settings()
