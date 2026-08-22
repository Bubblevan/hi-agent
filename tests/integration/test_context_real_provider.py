import os

import pytest
from dotenv import load_dotenv

from context.compiler import compile_context
from context.formatter import format_openai_messages
from context.models import ContextBudget, ContextItem
from context.payload import build_openai_payload
from context.structure import structure_messages
from context.trace import build_context_trace
from core.llm_client import MyLLMClient


load_dotenv()

pytestmark = pytest.mark.real_llm

MAX_OUTPUT_TOKENS = 256

def require_real_llm_config() -> dict[str, str]:
    """只有显式启用且配置完整时，才允许运行真实 Provider 测试。"""

    if os.getenv("RUN_REAL_LLM_TESTS") != "1":
        pytest.skip(
            "set RUN_REAL_LLM_TESTS=1 to run the real provider test"
        )

    api_key = (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL_ID")

    missing = []

    if not api_key:
        missing.append("LLM_API_KEY or OPENAI_API_KEY")
    if not base_url:
        missing.append("LLM_BASE_URL")
    if not model:
        missing.append("LLM_MODEL_ID")

    if missing:
        pytest.skip(
            "missing real provider configuration: "
            + ", ".join(missing)
        )

    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }


def make_real_provider_context_items() -> list[ContextItem]:
    return [
        ContextItem(
            item_id="system",
            kind="system",
            content=(
                "Return only the verification code contained in the "
                "selected evidence. Do not explain your answer."
            ),
            source="hardcoded",
            priority=100,
            required=True,
            token_count=10,
        ),
        ContextItem(
            item_id="task",
            kind="task",
            content="What is the verification code?",
            source="user",
            priority=100,
            required=True,
            token_count=10,
        ),
        ContextItem(
            item_id="correct-evidence",
            kind="retrieval",
            content="The verification code is HI_AGENT_CONTEXT_OK.",
            source="rag",
            priority=80,
            required=False,
            token_count=10,
        ),
        ContextItem(
            item_id="dropped-evidence",
            kind="retrieval",
            content="The verification code is WRONG_DROPPED_CODE.",
            source="stale-rag",
            priority=1,
            required=False,
            token_count=60,
        ),
    ]


def test_real_openai_compatible_provider_accepts_context_payload():
    config = require_real_llm_config()

    items = make_real_provider_context_items()
    budget = ContextBudget(
        soft_limit=60,
        hard_limit=512,
        output_reserve=MAX_OUTPUT_TOKENS,
    )

    # ContextItem → CompiledContext
    compiled = compile_context(items, budget)

    # CompiledContext → ContextTrace
    trace = build_context_trace(compiled)

    # CompiledContext → ContextMessage
    context_messages = structure_messages(compiled)

    # ContextMessage → FormattedMessage
    formatted_messages = format_openai_messages(context_messages)

    # FormattedMessage → Provider payload
    payload = build_openai_payload(formatted_messages)

    # 调用真实 OpenAI-compatible Provider。
    client = MyLLMClient(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config["base_url"],
        provider="openai",
    )

    response = client.invoke(
        payload,
        temperature=0,
        max_tokens=32,
    )
    # raw_response = client._client.chat.completions.create(
    #     model=client.model,
    #     messages=payload,
    #     temperature=0,
    #     max_tokens=32,
    #     stream=False,
    # )

    # choice = raw_response.choices[0]
    # message = choice.message

    # content = message.content
    # reasoning_content = getattr(
    #     message,
    #     "reasoning_content",
    #     None,
    # )
    # refusal = getattr(
    #     message,
    #     "refusal",
    #     None,
    # )

    # print("model:", raw_response.model)
    # print("finish_reason:", choice.finish_reason)
    # print("content:", repr(content))
    # print(
    #     "reasoning_content length:",
    #     len(reasoning_content or ""),
    # )
    # print("refusal:", repr(refusal))
    # print("usage:", raw_response.usage)

    # response = content or ""

    # 编译结果正确。
    assert trace.selected_item_ids == [
        "system",
        "task",
        "correct-evidence",
    ]
    assert trace.dropped_item_ids == [
        "dropped-evidence",
    ]

    # Provider 边界正确。
    assert all(
        set(message) == {"role", "content"}
        for message in payload
    )
    assert all(
        "WRONG_DROPPED_CODE" not in message["content"]
        for message in payload
    )

    # 真实 Provider 能消费 payload，并使用被选中的证据。
    assert isinstance(response, str)
    assert response.strip()
    assert "HI_AGENT_CONTEXT_OK" in response
    assert "WRONG_DROPPED_CODE" not in response
    assert not response.startswith("LLM调用失败:")