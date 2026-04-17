import os

from litellm import acompletion

from craftsman.auth import Auth
from craftsman.configure import get_config
from craftsman.logger import CraftsmanLogger

logger = CraftsmanLogger().get_logger(__name__)


class Provider:
    def __init__(self, model: str = None, embedding_model: str = None):
        self.config = get_config()
        self.model = model or self.config["provider"]["model"]
        self.embedding_model = (
            embedding_model or self.config["provider"]["embedding_model"]
        )
        self.auth = Auth()

        self.cert = self.auth.get_password("LLM_SSL_CRT")
        self.verify = True if self.cert else False
        os.environ["SSL_CERT_FILE"] = self.cert

        api_key = self.auth.get_password("LLM_API_KEY")
        self.api_key = api_key if api_key else "dummy_api_key"

    async def completion(self, messages: list):

        response = await acompletion(
            model=self.model,
            api_key=self.api_key,
            api_base=self.auth.get_password("LLM_BASE_URL"),
            messages=messages,
            ssl_verify=self.verify,
            stream=True,
        )
        async for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                yield content
