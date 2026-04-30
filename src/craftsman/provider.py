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
        self.logger.debug("Resetting provider state...")
        self.cert = Auth.get_password("LLM_SSL_CRT")
        self.verify = bool(self.cert)
        if self.cert:
            os.environ["SSL_CERT_FILE"] = self.cert
        self.api_key = None
        self.api_base = None

        self.ctx_size = self.config["provider"].get("ctx_size", 4096)
        self.input_cost_per_token = self.config["provider"].get(
            "input_cost_per_token", 0.0
        )
        self.output_cost_per_token = self.config["provider"].get(
            "output_cost_per_token", 0.0
        )

    def reset(self, api_base: str = None, api_key: str = None):
        self.logger.debug("Resetting provider state...")
        self.api_key = api_key if api_key else "dummy_api_key"
        self.api_base = api_base if api_base else "http://localhost:8000"

    async def completion(
        self,
        messages: list,
        ctx_size: int = None,
        cancel_event=None,
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
    ):
        kwargs = dict(
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base,
            messages=messages,
            ssl_verify=self.verify,
            stream=True,
            stream_options={"include_usage": True},
            max_tokens=ctx_size,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        response = await litellm.acompletion(**kwargs)

        usage = None
        async for kind, text in self.model_response_parser(
            response, cancel_event
        ):
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
                "ctx_total": self.ctx_size,
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
        response: litellm.utils.CustomStreamWrapper,
        cancel_event=None,
        think_tag: str = "reasoning_content",
        think_start_tag: str = "<think>",
        think_end_tag: str = "</think>",
    ):
        in_think = False
        pending_tool_calls: dict[int, dict] = {}

        async for chunk in response:
            if cancel_event and cancel_event.is_set():
                await response.aclose()
                return
            if getattr(chunk, "usage", None):
                yield ("__usage__", chunk.usage)

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = getattr(choice, "finish_reason", None)

            tc_deltas = getattr(delta, "tool_calls", None)
            if tc_deltas:
                for tc in tc_deltas:
                    idx = tc.index
                    if idx not in pending_tool_calls:
                        pending_tool_calls[idx] = {
                            "id": "",
                            "name": "",
                            "arguments": "",
                        }
                    if getattr(tc, "id", None):
                        pending_tool_calls[idx]["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn:
                        if getattr(fn, "name", None):
                            # most providers send name in one chunk; += handles
                            # the rare case where it arrives in fragments
                            pending_tool_calls[idx]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            pending_tool_calls[idx][
                                "arguments"
                            ] += fn.arguments

            if finish_reason == "tool_calls":
                for idx in sorted(pending_tool_calls):
                    tc = pending_tool_calls[idx]
                    yield (
                        "tool_call",
                        {
                            "id": tc["id"],
                            "name": tc["name"],
                            "arguments_raw": tc["arguments"],
                        },
                    )
                pending_tool_calls.clear()
                continue

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
