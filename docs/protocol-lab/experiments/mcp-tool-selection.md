# MCP Tool Catalog 与 Context Selector 实验

## 问题

当 MCP Server 暴露 100 个工具时，是全部放入提示词，还是先检索候选？

本实验选择第二种：Catalog 保存完整元数据，Selector 只把相关工具 schema
送入后续 Agent loop。

## 最小选择代码

    selection = host.select_tools(
        "搜索项目中所有 Mini-MCP 相关代码",
        budget=ContextBudget(
            soft_limit=100,
            hard_limit=200,
            output_reserve=20,
        ),
    )

    print(
        [entry.canonical_tool_name for entry in selection.selected]
    )
    print(selection.reasons)

预期结果：

    ["filesystem.grep_code"]

在更宽松的描述或预算下，也可以选择 read_file；delete_file 不应因为存在于
同一个 Server 就自动进入上下文。

## 当前算法

1. 对任务和工具名、描述、tags 做轻量 lexical overlap；
2. 只保留有重叠的候选；
3. 把候选映射成已有 ContextItem；
4. 复用 select_items() 的 priority 和 token budget；
5. 返回 selected、dropped 和 reason。

## 局限

- 中英文 alias bridge 只是教学辅助；
- 没有 embedding retrieval；
- 没有 schema compression；
- 没有线上 cache 命中率实验；
- selection reason 不是模型解释，而是可审计的规则结果。

## 八卦：tool list 也有 prompt cache 脾气

工具目录看起来像普通配置，但它实际上会影响模型输入前缀。工具顺序不稳定，
哪怕工具集合没有变化，也可能让上游 prompt cache 失效。于是 deterministic order、
catalog TTL、stable prefix 和 dynamic tail 并不是“性能优化小技巧”，而是 Host
接口设计的一部分。

