"""
Quick smoke test for Provider completion and embedding.

Usage:
    uv run python examples/test_provider.py
"""

import asyncio

from craftsman.provider import Provider


async def test_completion(provider: Provider):
    print("=== completion (streaming) ===")
    messages = [{"role": "user", "content": "Say hello in one sentence."}]
    async for chunk in provider.completion(messages):
        print(chunk, end="", flush=True)
    print()


async def test_embedding(provider: Provider):
    print("=== embedding ===")
    response = await provider.embedding("hello world")
    vector = response.data[0]["embedding"]
    print(f"dims: {len(vector)}, first 5 values: {vector[:5]}")


async def main():
    provider = Provider()
    await test_completion(provider)
    await test_embedding(provider)


if __name__ == "__main__":
    asyncio.run(main())
