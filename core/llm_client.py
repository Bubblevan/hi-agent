import os
from typing import List, Dict, Any, Optional, Iterator
from openai import OpenAI

class MyLLMClient:
    """
    支持Openai、Modelscope、本地Ollama/VLLM
    """
    def __init__(
            self,
            model: Optional[str] = None,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            provider: Optional[str] = "auto",
    ):
        # 解析提供商
        self.provider = self._detect_provider(provider, api_key, base_url)

        # 根据提供商，智能获取凭证
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
            # 通用模式：直接用传参或环境变量
            self.api_key = api_key or os.getenv("LLM_API_KEY")
            self.base_url = base_url or os.getenv("LLM_BASE_URL")
            self.model = model or os.getenv("LLM_MODEL_ID") or "gpt-3.5-turbo"

        # 初始化 OpenAI 客户端
        if not self.api_key:
            raise ValueError(f"未找到{self.provider}的APIKEY！")
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=60
        )
        print(f"LLM引擎启动成功")

    def _detect_provider(self, provider, api_key, base_url) -> str:
        """我们自己的侦探逻辑，识别服务商"""
        if provider and provider != "auto":
            return provider
            
        # 1. 检查特定环境变量（最高优先级）
        if os.getenv("MODELSCOPE_API_KEY"):
            return "modelscope"
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
            
        # 2. 检查 URL 特征
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
                
        # 3. 默认
        return "generic"
    
    def invoke(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        同步调用大模型（非流式）
        messages = [
            {"role": "system", "content": "你是一个专业助手"},
            {"role": "user", "content": "你好"}
        ]
        """
        try:
            response = self._client.chat.completions.create(
                model = self.model,
                messages=messages,
                temperature=kwargs.get('temperature', 0.7),
                max_tokens=kwargs.get('max_tokens'),
                stream=False
            )
            # print(response)
            # 默认只生成一条，所以取第一条回复的文本内容
            return response.choices[0].message.content
        except Exception as e:
            return f"LLM调用失败: {str(e)}"
        
    def stream_invoke(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                model = self.model,
                messages=messages,
                temperature=kwargs.get('temperature', 0.7),
                max_tokens=kwargs.get('max_tokens'),
                stream=True
            )
            for chunk in stream:
                # delta 表示当前分片的增量内容，非空则通过yield返回
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            yield f"流式调用失败: {str(e)}"