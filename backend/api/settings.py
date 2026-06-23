import logging
from fastapi import APIRouter, Depends, HTTPException, Cookie, Request
from pydantic import BaseModel
from typing import Optional

from backend.services.config_service import get_llm_settings, update_llm_settings
import backend.services.global_services as global_services

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    llm_provider: Optional[str] = None
    preferred_core: Optional[str] = None  # alias for llm_provider (backward compat)
    gemini_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    openai_model: Optional[str] = None
    openrouter_model: Optional[str] = None


@router.get("")
def get_settings(student_id: Optional[str] = Cookie(None)):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")
    return get_llm_settings()


@router.post("")
def update_settings(
    settings: SettingsUpdate,
    student_id: Optional[str] = Cookie(None),
):
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Resolve provider: prefer explicit llm_provider, fallback to preferred_core
    provider = settings.llm_provider or settings.preferred_core

    try:
        result = update_llm_settings(
            llm_provider=provider,
            gemini_api_key=settings.gemini_api_key,
            openrouter_api_key=settings.openrouter_api_key,
            openai_api_key=settings.openai_api_key,
            gemini_model=settings.gemini_model,
            openai_model=settings.openai_model,
            openrouter_model=settings.openrouter_model,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update LLM settings: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi lưu cấu hình: {str(e)}")

    # Reload the singleton LLM service from global_services (reliable cross-module instance)
    llm_svc = global_services.llm_service
    if llm_svc:
        llm_svc.reload_config()
        logger.info("LLMService reloaded successfully after settings update.")
    else:
        logger.warning("global_services.llm_service is None — LLM not reloaded.")

    return {
        "status": "success",
        "message": "Cấu hình AI đã được lưu và áp dụng ngay lập tức",
        **result,
    }


@router.get("/test")
async def test_connection(student_id: Optional[str] = Cookie(None)):
    """Kiểm tra kết nối với provider LLM hiện tại."""
    if not student_id:
        raise HTTPException(status_code=401, detail="Not logged in")

    llm_svc = global_services.llm_service
    if not llm_svc:
        raise HTTPException(status_code=503, detail="LLM service chưa khởi động")

    cfg = get_llm_settings()
    provider = cfg.get("llm_provider", "mock")

    if provider == "mock":
        return {"status": "ok", "provider": "mock", "message": "Chế độ Mock đang hoạt động (không gọi API thật)"}

    try:
        test_reply = await llm_svc.generate_response(
            system_prompt="You are a test assistant. Reply with exactly: 'Connection OK'",
            user_prompt="ping"
        )
        return {
            "status": "ok",
            "provider": provider,
            "message": f"Kết nối thành công! Phản hồi: {test_reply[:100]}"
        }
    except Exception as e:
        return {
            "status": "error",
            "provider": provider,
            "message": f"Lỗi kết nối: {str(e)}"
        }
