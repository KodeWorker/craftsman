import os

import litellm

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger


class Provider:
    def __init__(self, model: str = None):
        self.config = get_config()
        self.logger = CraftsmanLogger().get_logger(__name__)
        self.debug = self.config["provider"].get("debug", False)
        self.model = model or self.config["provider"]["model"]

        self.cert = Auth.get_password("LLM_SSL_CRT")
        self.verify = bool(self.cert)
        if self.cert:
            os.environ["SSL_CERT_FILE"] = self.cert
        api_key = Auth.get_password("LLM_API_KEY")
        self.api_key = api_key if api_key else "dummy_api_key"
        self.api_base = Auth.get_password("LLM_BASE_URL")

        self.max_tokens = self.config["provider"].get("max_tokens", 4096)
        self.input_cost_per_token = self.config["provider"].get(
            "input_cost_per_token", 0.0
        )
        self.output_cost_per_token = self.config["provider"].get(
            "output_cost_per_token", 0.0
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

        cost = (
            self.cost(
                getattr(usage, "prompt_tokens", 0),
                getattr(usage, "completion_tokens", 0) or 0,
            )
            if usage
            else 0.0
        )

        completion_details = getattr(usage, "completion_tokens_details", None)
        reasoning_tokens = getattr(completion_details, "reasoning_tokens", 0)
        ctx_used = getattr(usage, "total_tokens", 0) - reasoning_tokens
        yield (
            "meta",
            {
                "model": self.model,
                "ctx_total": self.max_tokens,
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0)
                or 0,
                "ctx_used": ctx_used,
                "reasoning_tokens": reasoning_tokens,
                "cost": cost,
            },
        )

        self.logger.info("Model response completed.")

    async def model_response_parser(
        self,
        response: litellm.ACompletionResponse,
        think_tag: str = "reasoning_content",
        think_start_tag: str = "<think>",
        think_end_tag: str = "</think>",
    ):
        in_think = False
        async for chunk in response:
            if getattr(chunk, "usage", None):
                yield ("__usage__", chunk.usage)

            if not chunk.choices:
                continue

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

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens * self.input_cost_per_token
            + completion_tokens * self.output_cost_per_token
        )
