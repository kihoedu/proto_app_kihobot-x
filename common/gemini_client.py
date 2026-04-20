"""
Gemini · Ollama 통합 LLM 클라이언트 (langchain-google-genai 기준)
=================================================================
양쪽 엔진이 공유하는 LLM 호출 인터페이스.
"""
import os
import logging
from langchain_google_genai import ChatGoogleGenerativeAI

from common.config import GEMINI_API_KEY, GEMINI_MODEL, OLLAMA_MODEL, OLLAMA_HOST

logger = logging.getLogger("kihobot.llm")


def get_llm(provider: str = None, model: str = None, temperature: float = 0.1):
    """
    공통 LLM 인스턴스 반환.
    provider: "gemini" | "ollama" | None (auto)
    """
    prov = (provider or _auto_provider()).lower()

    if prov == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            model=model or OLLAMA_MODEL,
            base_url=OLLAMA_HOST,
            temperature=temperature,
        )

    if prov == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY 가 .env 에 설정되어 있지 않습니다.")
        return ChatGoogleGenerativeAI(
            model=model or GEMINI_MODEL,
            google_api_key=GEMINI_API_KEY,
            temperature=temperature,
        )

    # 기본값: openai
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(model=model or "gpt-4o", temperature=temperature)


def _auto_provider() -> str:
    """DB 설정 → Gemini 키 → 기본값 순으로 감지"""
    try:
        from eval_engine.services.crud import get_llm_provider
        return get_llm_provider()
    except Exception:
        pass
    return "gemini" if GEMINI_API_KEY else "openai"


def gemini_text(prompt: str, system: str = "", temperature: float = 0.1,
                max_tokens: int = 30000) -> str:
    """
    단순 텍스트 호출. JSON 파싱 등은 호출자가 처리.
    """
    llm = get_llm("gemini", temperature=temperature)
    messages = []
    if system:
        messages.append(("system", system))
    messages.append(("human", prompt))

    response = llm.invoke(messages)
    return response.content if hasattr(response, "content") else str(response)
