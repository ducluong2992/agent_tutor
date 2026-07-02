import asyncio
from backend.services.llm_service import LLMService

async def test_llm():
    llm = LLMService()
    print("Provider:", llm.api_provider)
    res = await llm.generate_response("System prompt", "User prompt")
    print("Response length:", len(res))
    usage = getattr(llm, "last_token_usage", None)
    print("Token Usage:", usage)

if __name__ == "__main__":
    asyncio.run(test_llm())
