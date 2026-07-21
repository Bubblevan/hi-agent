from tools.builtin.memory_tool import MemoryTool


def test_memory_tool_add_search_and_stats_use_working_memory(patch_fake_embedder):
    tool = MemoryTool(user_id="user_a", enable_working=True)

    add_result = tool.execute(
        "add",
        content="I write Python services",
        memory_type="working",
        importance=0.6,
    )
    search_result = tool.execute("search", query="Python", limit=3)
    stats_result = tool.execute("stats")

    assert "ID:" in add_result
    assert "I write Python services" in search_result
    assert "working" in stats_result


def test_memory_tool_rejects_empty_add_and_search(patch_fake_embedder):
    tool = MemoryTool(user_id="user_a", enable_working=True)

    assert tool.execute("add", content="").startswith("错误")
    assert tool.execute("search", query="").startswith("错误")
    assert tool.manager.memory_types["working"]._items == []


def test_memory_tool_injects_user_and_session_metadata(patch_fake_embedder):
    tool = MemoryTool(user_id="user_a", enable_working=True)

    tool.execute("add", content="Remember my Python preference")

    item = tool.manager.memory_types["working"]._items[0]
    assert item.metadata["user_id"] == "user_a"
    assert item.metadata["session_id"] == tool.current_session_id
