import os

import litellm

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger

logger = CraftsmanLogger().get_logger(__name__)


class Provider:
    def __init__(self, model: str = None, embedding_model: str = None):
        self.config = get_config()
        self.debug = self.config["provider"].get("debug", False)
        self.model = model or self.config["provider"]["model"]
        self.think = (
            self.config["provider"].get("think", {}).get("enabled", False)
        )
        self.budget = (
            self.config["provider"].get("think", {}).get("budget", None)
        )

        self.auth = Auth()
        self.cert = self.auth.get_password("LLM_SSL_CRT")
        self.verify = True if self.cert else False
        os.environ["SSL_CERT_FILE"] = self.cert
        api_key = self.auth.get_password("LLM_API_KEY")
        self.api_key = api_key if api_key else "dummy_api_key"
        self.api_base = self.auth.get_password("LLM_BASE_URL")

        self.max_tokens = self.config["provider"].get("max_tokens", 4096)
        litellm.register_model(
            {
                self.model: {
                    "max_tokens": self.max_tokens,
                    "input_cost_per_token": self.config["provider"].get(
                        "input_cost_per_token", 0.00000
                    ),
                    "output_cost_per_token": self.config["provider"].get(
                        "output_cost_per_token", 0.00000
                    ),
                    "litellm_provider": "openai",
                    "mode": "chat",
                },
            }
        )

    async def completion(self, messages: list):

        response = await litellm.acompletion(
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base,
            messages=messages,
            ssl_verify=self.verify,
            stream=True,
            stream_options={"include_usage": True},
        )

        usage = None
        async for kind, text in self.model_response_parser(response):
            if kind == "__usage__":
                usage = text
                continue
            if kind == "reasoning" and not self.debug:
                continue
            yield (kind, text)

        yield (
            "meta",
            {
                "model": self.model,
                "ctx_total": self.max_tokens,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0)
                or 0,
                "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            },
        )

    async def model_response_parser(
        self,
        response: str,
        think_tag: str = "reasoning_content",
        think_start_tag: str = "<think>",
        think_end_tag: str = "</think>",
    ):
        in_think = False
        async for chunk in response:
            if getattr(chunk, "usage", None):
                yield ("__usage__", chunk.usage)
            delta = chunk.choices[0].delta
            if getattr(delta, think_tag, None):
                yield ("reasoning", getattr(delta, think_tag))
                continue
            if not delta.content:
                continue
            content = delta.content
            while content:
                if in_think:
                    end = content.find(think_end_tag)
                    if end == -1:
                        yield ("reasoning", content)
                        break
                    yield ("reasoning", content[:end])
                    content = content[end + len(think_end_tag) :]
                    in_think = False
                else:
                    start = content.find(think_start_tag)
                    if start == -1:
                        yield ("content", content)
                        break
                    if start > 0:
                        yield ("content", content[:start])
                    content = content[start + len(think_start_tag) :]
                    in_think = True
