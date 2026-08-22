import pytest

from context.models import (
    ContextBudget,
    ContextItem,
    CompiledContext,
    ContextMessage,
    FormattedMessage,
)

def test_context_budget_rejects_output_reserve_equal_to_hard_limit():
    with pytest.raises(ValueError):
        ContextBudget(
            soft_limit=50,
            hard_limit=100,
            output_reserve=100,
        )
def test_valid_context_item_can_be_created():
    item = ContextItem(
        item_id="task:current",
        kind="task",
        content="实现 Context Contract",
        source="user",
        priority=100,
        required=True,
        token_count=12,
        metadata={"turn_id": "turn-1"},
    )

    assert item.item_id == "task:current"
    assert item.kind == "task"
    assert item.content == "实现 Context Contract"
    assert item.source == "user"
    assert item.priority == 100
    assert item.required is True
    assert item.token_count == 12
    assert item.metadata == {"turn_id": "turn-1"}


@pytest.mark.parametrize("content", ["", " ", "\n\t"])
def test_context_item_rejects_blank_content(content):
    with pytest.raises((TypeError, ValueError)):
        ContextItem(
            item_id="task:current",
            kind="task",
            content=content,
            source="user",
            priority=100,
            required=True,
            token_count=0,
            metadata={},
        )


def test_context_item_rejects_negative_token_count():
    with pytest.raises((TypeError, ValueError)):
        ContextItem(
            item_id="task:current",
            kind="task",
            content="有效内容",
            source="user",
            priority=100,
            required=True,
            token_count=-1,
            metadata={},
        )


@pytest.mark.parametrize("required", ["true", "false"])
def test_context_item_requires_strict_boolean(required):
    with pytest.raises((TypeError, ValueError)):
        ContextItem(
            item_id="task:current",
            kind="task",
            content="有效内容",
            source="user",
            priority=100,
            required=required,
            token_count=1,
            metadata={},
        )


@pytest.mark.parametrize(
    "values",
    [
        {"soft_limit": 0, "hard_limit": 100, "output_reserve": 10},
        {"soft_limit": 50, "hard_limit": 0, "output_reserve": 0},
        {"soft_limit": 101, "hard_limit": 100, "output_reserve": 10},
        {"soft_limit": 50, "hard_limit": 100, "output_reserve": -1},
        {"soft_limit": 50, "hard_limit": 100, "output_reserve": 101},
    ],
)
def test_context_budget_rejects_invalid_ranges(values):
    with pytest.raises((TypeError, ValueError)):
        ContextBudget(**values)

class TestFormattedMessageValidation:
    """FormattedMessage 数据模型验证测试"""

    def test_formatted_message_rejects_unsupported_role(self):
        """FormattedMessage 拒绝非法的 role"""
        with pytest.raises(ValueError, match="role"):
            FormattedMessage(
                role="tool",
                content="Tool result",
                item_id="tool-1",
                source="tool",
            )

    def test_formatted_message_accepts_valid_roles(self):
        """FormattedMessage 接受合法的 role"""
        for role in ("system", "user", "assistant"):
            msg = FormattedMessage(
                role=role,
                content="Content",
                item_id="id-1",
                source="source",
            )
            assert msg.role == role