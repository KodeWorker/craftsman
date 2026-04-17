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


async def main():
    provider = Provider()
    await test_completion(provider)


if __name__ == "__main__":
    asyncio.run(main())
