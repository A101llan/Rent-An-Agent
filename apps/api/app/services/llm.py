import httpx
import logging

from app.config import settings

logger = logging.getLogger(__name__)

async def is_ollama_available() -> bool:
    """Check if the Ollama service is running."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(settings.ollama_base_url)
            return resp.status_code == 200
    except Exception:
        return False

async def call_gemini(system_prompt: str, user_message: str, history: list = None) -> dict | None:
    """Call Google Gemini REST API as a cloud fallback."""
    if not settings.gemini_api_key:
        return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={settings.gemini_api_key}"
        contents = []
        if history:
            for item in history:
                role = "user" if item.get("role") == "user" else "model"
                contents.append({"role": role, "parts": [{"text": item.get("content", "")}]})
        
        # System prompt + current message
        user_parts = []
        if system_prompt:
            user_parts.append({"text": f"System Instructions: {system_prompt}"})
        user_parts.append({"text": user_message})
        contents.append({"role": "user", "parts": user_parts})

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"contents": contents})
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return {"output": text, "provider": "gemini", "usage": {"input_tokens": 100, "output_tokens": len(text.split())}}
    except Exception as e:
        logger.warning(f"Gemini fallback failed: {e}")
    return None

async def call_openai(system_prompt: str, user_message: str, history: list = None) -> dict | None:
    """Call OpenAI API as a cloud fallback."""
    if not settings.openai_api_key:
        return None
    try:
        url = "https://api.openai.com/v1/chat/completions"
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": "gpt-4o-mini", "messages": messages}
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                return {"output": text, "provider": "openai", "usage": data.get("usage", {})}
    except Exception as e:
        logger.warning(f"OpenAI fallback failed: {e}")
    return None


async def call_ollama(
    system_prompt: str,
    user_message: str,
    context_answers: dict = None,
    history: list = None,
) -> dict | None:
    """Call local Ollama /api/chat. Returns None on any failure so cascade continues."""
    try:
        messages = []
        system_parts = []
        if system_prompt:
            system_parts.append(system_prompt)
        if context_answers:
            ctx = "Here is context about the user environment:\n"
            for key, value in context_answers.items():
                label = key.replace("_", " ").title()
                ctx += f"- {label}: {value}\n"
            system_parts.append(ctx)
        if system_parts:
            messages.append({"role": "system", "content": "\n\n".join(system_parts).strip()})
        if history:
            for item in history:
                role = item.get("role", "user")
                if role not in ("user", "assistant", "system"):
                    role = "user"
                messages.append({"role": role, "content": item.get("content", "")})
        messages.append({"role": "user", "content": user_message})

        url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": settings.ollama_model,
            "messages": messages,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.warning(f"Ollama chat failed: HTTP {resp.status_code}")
                return None
            data = resp.json()
            text = (data.get("message") or {}).get("content", "")
            if not text:
                return None
            usage = {
                "input_tokens": data.get("prompt_eval_count") or 0,
                "output_tokens": data.get("eval_count") or 0,
            }
            return {"output": text, "usage": usage}
    except Exception as e:
        logger.warning(f"Ollama call failed: {e}")
        return None

async def call_llm(system_prompt: str, user_message: str, context_answers: dict = None, history: list = None) -> dict:
    """Unified entry point cascading across Ollama -> Gemini -> OpenAI -> Smart Fallback."""
    # Build prompt context
    context_str = ""
    if context_answers:
        context_str = "Here is context about the user environment:\n"
        for key, value in context_answers.items():
            label = key.replace("_", " ").title()
            context_str += f"- {label}: {value}\n"
        context_str += "\n"

    full_system_prompt = f"{system_prompt}\n\n{context_str}".strip()

    # 1. Try local Ollama if running
    if await is_ollama_available():
        res = await call_ollama(system_prompt, user_message, context_answers, history)
        if res and res.get("output") and not res.get("output").startswith("I encountered an error"):
            res["provider"] = "ollama"
            return res

    # 2. Try Gemini (Free Tier)
    gemini_res = await call_gemini(full_system_prompt, user_message, history)
    if gemini_res:
        return gemini_res

    # 3. Try OpenAI
    openai_res = await call_openai(full_system_prompt, user_message, history)
    if openai_res:
        return openai_res

    # 4. Fallback intelligent response generator
    agent_name_hint = "assistant"
    if "Support" in system_prompt:
        agent_name_hint = "Support Agent"
    elif "Triage" in system_prompt or "Bug" in system_prompt:
        agent_name_hint = "GitHub Triage Agent"

    reply = f"Hello! I am your {agent_name_hint}. I processed your request: '{user_message}'."
    if context_answers:
        reply += f" I see you configured: {', '.join([f'{k}={v}' for k,v in context_answers.items()])}."

    return {
        "output": reply,
        "provider": "mock_fallback",
        "usage": {"input_tokens": 10, "output_tokens": 20}
    }

async def stream_llm(system_prompt: str, user_message: str, context_answers: dict = None, history: list = None):
    """Async generator yielding chunks for WebSocket real-time streaming."""
    res = await call_llm(system_prompt, user_message, context_answers, history)
    text = res.get("output", "")
    words = text.split(" ")
    for i in range(0, len(words), 2):
        chunk = " ".join(words[i:i+2]) + " "
        yield chunk
        import asyncio
        await asyncio.sleep(0.04)

