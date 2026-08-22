# -*- coding: utf-8 -*-
"""上下文追踪模块单元测试。

测试 ContextTrace V1 的核心行为：
- 记录 selected_item_ids 并按顺序
- 记录 dropped_item_ids 并按顺序
- 记录 token 统计
- 记录 stage = "compiler"
- 确定性输出
"""

from context.models import CompiledContext, ContextItem, ContextTrace
from context.trace import build_context_trace


def make_compiled_context() -> CompiledContext:
    """创建一个测试用的 CompiledContext"""
    selected = [
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
            content="Complete the current task.",
            source="user",
            priority=90,
            required=True,
            token_count=20,
        ),
    ]
    dropped = [
        ContextItem(
            item_id="old_conversation",
            kind="conversation",
            content="An older conversation turn.",
            source="history",
            priority=10,
            required=False,
            token_count=30,
        ),
        ContextItem(
            item_id="retrieval_1",
            kind="retrieval",
            content="An unselected retrieval result.",
            source="rag",
            priority=5,
            required=False,
            token_count=20,
        ),
    ]

    return CompiledContext(
        selected_items=selected,
        dropped_items=dropped,
        total_input_tokens=30,
        available_input_tokens=80,
    )


class TestTraceBasic:
    """基本追踪测试"""

    def test_trace_records_selected_item_ids_in_order(self):
        """selected_item_ids 按 selected_items 顺序记录"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        assert trace.selected_item_ids == ["system", "task"]

    def test_trace_records_dropped_item_ids_in_order(self):
        """dropped_item_ids 按 dropped_items 顺序记录"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        assert trace.dropped_item_ids == [
            "old_conversation",
            "retrieval_1",
        ]

    def test_trace_records_total_input_tokens(self):
        """total_input_tokens 正确复制"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        assert trace.total_input_tokens == 30

    def test_trace_records_available_input_tokens(self):
        """available_input_tokens 正确复制"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        assert trace.available_input_tokens == 80

    def test_trace_records_compiler_stage(self):
        """stage 固定为 'compiler'"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        assert trace.stage == "compiler"

    def test_trace_is_deterministic(self):
        """相同 CompiledContext 产生相同的 Trace"""
        compiled = make_compiled_context()

        first = build_context_trace(compiled)
        second = build_context_trace(compiled)

        assert first == second

    def test_trace_does_not_include_content(self):
        """Trace 不保存 item content"""
        compiled = make_compiled_context()
        trace = build_context_trace(compiled)

        # 断言这些字段存在且不包含 content
        assert hasattr(trace, "selected_item_ids")
        assert hasattr(trace, "dropped_item_ids")

        # 所有元素都是 ID 字符串（不是 ContextItem）
        assert all(isinstance(x, str) for x in trace.selected_item_ids)
        assert all(isinstance(x, str) for x in trace.dropped_item_ids)