# -*- coding: utf-8 -*-
"""Context Pipeline 集成测试（使用 Fake Provider）。

验证完整的上下文工程链路：
compile_context → structure_messages → format_openai_messages → build_openai_payload → Provider

使用 Fake Provider 模拟 LLM 调用，确保：
1. 整个数据流正确串联
2. 选择/丢弃逻辑正确传递到 Payload
3. item_id/source 不会泄露到 Provider
4. Trace 记录正确
5. 输出确定性
"""

from context.compiler import compile_context
from context.formatter import format_openai_messages
from context.models import ContextBudget, ContextItem
from context.payload import build_openai_payload
from context.structure import structure_messages
from context.trace import build_context_trace


class FakeProvider:
    """模拟 LLM Provider，记录收到的 payload 并返回固定答案。"""

    def __init__(self, answer: str = "fixed answer") -> None:
        self.answer = answer
        self.received_payloads: list[list[dict[str, str]]] = []

    def invoke(self, payload: list[dict[str, str]]) -> str:
        """模拟 LLM 调用。

        Args:
            payload: OpenAI-compatible 消息字典列表。

        Returns:
            固定的模拟回答。
        """
        self.received_payloads.append(payload)
        return self.answer


def make_context_items() -> list[ContextItem]:
    """创建测试用的 ContextItem 列表。

    预算设计：
    - hard_limit=80, output_reserve=20 → available_input=60
    - soft_limit=50
    - required: system (10) + task (20) = 30
    - optional_budget = min(50, 60) - 30 = 20

    - selected-evidence (15) → 可以进入（15 <= 20）
    - stale-evidence (30) → 被丢弃（30 > 20）
    """
    return [
        ContextItem(
            item_id="system",
            kind="system",
            content="Follow the system rules.",
            source="hardcoded",
            priority=100,
            required=True,
            token_count=10,
        ),
        ContextItem(
            item_id="task",
            kind="task",
            content="Answer the current question.",
            source="user",
            priority=100,
            required=True,
            token_count=20,
        ),
        ContextItem(
            item_id="selected-evidence",
            kind="retrieval",
            content="The selected evidence.",
            source="rag",
            priority=80,
            required=False,
            token_count=15,
        ),
        ContextItem(
            item_id="stale-evidence",
            kind="retrieval",
            content="This stale evidence must be dropped.",
            source="rag",
            priority=1,
            required=False,
            token_count=30,
        ),
    ]


def run_context_pipeline(provider: FakeProvider) -> dict:
    """运行完整的上下文工程流水线。

    Args:
        provider: FakeProvider 实例。

    Returns:
        包含 compiled、trace、payload、response 的字典。
    """
    items = make_context_items()
    budget = ContextBudget(
        soft_limit=50,
        hard_limit=80,
        output_reserve=20,
    )

    # 1. 编译上下文
    compiled = compile_context(items, budget)

    # 2. 构建 Trace（旁路观测）
    trace = build_context_trace(compiled)

    # 3. 转换为内部消息
    context_messages = structure_messages(compiled)

    # 4. 格式化为 OpenAI-compatible 格式（带追踪字段）
    formatted_messages = format_openai_messages(context_messages)

    # 5. 投影为纯 Provider payload
    payload = build_openai_payload(formatted_messages)

    # 6. 调用 Provider
    response = provider.invoke(payload)

    return {
        "compiled": compiled,
        "trace": trace,
        "payload": payload,
        "response": response,
    }


class TestContextFakeProvider:
    """Context Pipeline + Fake Provider 集成测试"""

    def test_complete_context_chain_reaches_fake_provider(self):
        """完整流水线能够到达 Fake Provider 并返回答案"""
        provider = FakeProvider()

        result = run_context_pipeline(provider)

        # 1. 返回固定答案
        assert result["response"] == "fixed answer"

        # 2. Provider 收到的 payload 就是构建的 payload
        assert provider.received_payloads == [result["payload"]]

        # 3. 验证 payload 内容
        assert result["payload"] == [
            {"role": "system", "content": "Follow the system rules."},
            {"role": "user", "content": "Answer the current question."},
            {"role": "user", "content": "The selected evidence."},
        ]

    def test_dropped_item_does_not_reach_provider(self):
        """被丢弃的 item 不会出现在 Provider payload 中"""
        result = run_context_pipeline(FakeProvider())

        payload_contents = [msg["content"] for msg in result["payload"]]

        assert "The selected evidence." in payload_contents
        assert "This stale evidence must be dropped." not in payload_contents

    def test_provider_payload_contains_only_public_fields(self):
        """Provider payload 只包含 role 和 content，不包含追踪字段"""
        result = run_context_pipeline(FakeProvider())

        for message in result["payload"]:
            assert set(message) == {"role", "content"}

    def test_trace_keeps_internal_selection_information(self):
        """Trace 保留内部选择信息（ID、token 统计）"""
        result = run_context_pipeline(FakeProvider())
        trace = result["trace"]

        # 验证选中的 item ID（保持顺序）
        assert trace.selected_item_ids == [
            "system",
            "task",
            "selected-evidence",
        ]

        # 验证被丢弃的 item ID（保持顺序）
        assert trace.dropped_item_ids == [
            "stale-evidence",
        ]

        # 验证 token 统计
        # required: 10 + 20 = 30, selected-evidence: 15, total = 45
        assert trace.total_input_tokens == 45

        # available_input = hard_limit - output_reserve = 80 - 20 = 60
        assert trace.available_input_tokens == 60

    def test_same_input_produces_same_payload_and_response(self):
        """相同输入产生相同输出（确定性）"""
        first = run_context_pipeline(FakeProvider())
        second = run_context_pipeline(FakeProvider())

        assert first["payload"] == second["payload"]
        assert first["response"] == second["response"]
        assert first["trace"] == second["trace"]