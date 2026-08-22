import os
from typing import Any, Dict, Iterator, List, Optional

from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

from .llm_result import LLMResult


class MyLLMClient:
    """Small OpenAI-compatible client used by the learning examples."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        provider: Optional[str] = "auto",
    ):
        # Load the nearest project .env without overriding explicit settings.
        load_dotenv(find_dotenv(), override=False)

        self.provider = self._detect_provider(provider, api_key, base_url)

        if self.provider == "openai":
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            self.base_url = base_url or "https://api.openai.com/v1"
            self.model = model or os.getenv("LLM_MODEL_ID") or "gpt-5.5"
        elif self.provider == "modelscope":
            self.api_key = api_key or os.getenv("MODELSCOPE_API_KEY")
            self.base_url = base_url or "https://api-inference.modelscope.cn/v1/"
            self.model = model or os.getenv("LLM_MODEL_ID") or "Qwen/Qwen2.5-7B-Instruct"
        elif self.provider == "vllm":
            self.api_key = api_key or "vllm"
            self.base_url = base_url or "http://localhost:8000/v1"
            self.model = model or os.getenv("LLM_MODEL_ID") or "Qwen/Qwen1.5-0.5B-Chat"
        else:
            self.api_key = api_key or os.getenv("LLM_API_KEY")
            self.base_url = base_url or os.getenv("LLM_BASE_URL")
            self.model = model or os.getenv("LLM_MODEL_ID") or "gpt-3.5-turbo"

        if not self.api_key:
            raise ValueError(f"未找到{self.provider}的APIKEY！")

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60,
        )
        print("LLM引擎启动成功")

    def _detect_provider(
        self,
        provider: Optional[str],
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> str:
        if provider and provider != "auto":
            return provider

        if os.getenv("MODELSCOPE_API_KEY"):
            return "modelscope"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"

        actual_url = base_url or os.getenv("LLM_BASE_URL") or ""
        if "api-inference.modelscope.cn" in actual_url:
            return "modelscope"
        if "openai.com" in actual_url:
            return "openai"
        if "localhost" in actual_url or "127.0.0.1" in actual_url:
            if "11434" in actual_url:
                return "ollama"
            if "8000" in actual_url:
                return "vllm"

        return "generic"

    def _request_kwargs(
        self,
        messages: List[Dict[str, str]],
        stream: bool,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens"),
            "stream": stream,
        }
        if kwargs.get("extra_body") is not None:
            request_kwargs["extra_body"] = kwargs["extra_body"]
        return request_kwargs

    def invoke(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """Return only answer text for compatibility with existing agents."""

        return self.invoke_with_metadata(messages, **kwargs).content

    def invoke_with_metadata(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> LLMResult:
        """Invoke the provider and preserve metadata needed by evaluations."""

        try:
            response = self._client.chat.completions.create(
                **self._request_kwargs(messages, stream=False, kwargs=kwargs),
            )
            choice = response.choices[0]
            message = choice.message
            usage = getattr(response, "usage", None)
            completion_details = getattr(
                usage,
                "completion_tokens_details",
                None,
            )
            prompt_details = getattr(usage, "prompt_tokens_details", None)

            return LLMResult(
                content=getattr(message, "content", None) or "",
                model=getattr(response, "model", None) or self.model,
                finish_reason=getattr(choice, "finish_reason", None),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                reasoning_tokens=getattr(
                    completion_details,
                    "reasoning_tokens",
                    None,
                ),
                cached_tokens=getattr(prompt_details, "cached_tokens", None),
            )
        except Exception as error:
            return LLMResult(
                content=f"LLM调用失败: {error}",
                model=self.model,
                error=str(error),
            )

    def stream_invoke(
        self,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                **self._request_kwargs(messages, stream=True, kwargs=kwargs),
            )
            for chunk in stream:
                content = getattr(chunk.choices[0].delta, "content", None)
                if content:
                    yield content
        except Exception as error:
            yield f"流式调用失败: {error}"
