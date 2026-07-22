# 博客大纲：给 Hi-Agent 的 Memory 装上"拒答"——一个 eval harness 的薄版本收尾

> 三源整合：Hi-Agent 代码 / Hello-Agents Ch8 / ChatGPT Memory 诊断

---

## 0. 摘要（一句话）

今天没有加新功能。把 Memory 检索的最后一块拼图——"不知道就说不知道"——从 eval 后处理搬进了 `MemoryManager` 本身，顺便搭了一个可复用的 eval harness。

---

## 1. 动机：Memory 不是"搜到什么返回什么"

**来源**：temp.txt 的 P0 诊断 + 实际 eval 数据

- **旧行为**：`retrieve_memories()` 永远返回 top-k，哪怕 k 条全不相关
- **问题**：Agent 拿到不相关的记忆后会强行编造回答（幻觉），而不是说"我不知道"
- **认知类比**（Hello-Agents 8.1.1）：人类面对陌生问题不会强行回忆——"想不起来"也是记忆系统的正常输出

用 eval 数据说话：
```
abstention_recall = 0.0  ← 所有不该回答的查询都返回了结果
```

---

## 2. 改动一：Manager 层支持 min_relevance_score

**来源**：代码块 `manager.py:136-204`

### 2.1 签名变更

```python
def retrieve_memories(
    self, query: str, limit: int = 5,
    memory_types=None, min_importance=0.0, session_id=None,
    min_relevance_score: float | None = None,  # ← 新增
    **kwargs
) -> List[MemoryItem]:
```

### 2.2 融合后写回分数

```python
all_results = self._fuse_search_results(all_results)  # RRF 融合

for result in all_results:
    result.item.metadata["relevance_score"] = result.score  # ← 分数不再丢失
```

**为什么之前丢了**：之前 `_fuse_search_results` 算完 RRF 后直接 `return [item for item in results[:limit]]`，融合分数没写回 `MemoryItem`。eval 只能用后处理补救。

### 2.3 拒答逻辑

```python
if min_relevance_score is not None:
    all_results = [
        result for result in all_results
        if result.score >= min_relevance_score
    ]
```

空列表 = "我不知道"——这才是正确的 Memory 行为。

---

## 3. 改动二：Eval Harness 支持阈值 + Debug

**来源**：代码块 `memory_eval.py:208-368`

### 3.1 CLI 新增参数

```bash
python -m evals.memory_eval \
  --fixture tests/fixtures/memory_cases.jsonl \
  --min-relevance-score 0.35 \
  --debug
```

### 3.2 threshold sweep 输出

| threshold | recall@5 | abstention_recall | mrr |
|-----------|----------|-------------------|-----|
| none | 0.9375 | 0.0000 | 0.775 |
| 0.30 | 0.8958 | 0.2609 | 0.765 |
| **0.35** | **0.8542** | **0.3043** | **0.737** |

`abstention_recall` 从 0 → 0.30，说明拒答机制真的生效了。

---

## 4. 认知模型回顾：Memory 的完整生命周期

**来源**：Hello-Agents 8.1.1 + 8.2.1

```
编码(Encoding) → 存储(Storage) → 检索(Retrieval) → 整合(Consolidation) → 遗忘(Forgetting)
                                                      ↑
                                              这次补的是检索层的"拒答"分支
```

Hello-Agents 的四层架构（本次博客对照）：

| Hello-Agents | Hi-Agent 当前状态 |
|-------------|-----------------|
| 基础设施层：MemoryManager / MemoryItem / MemoryConfig / BaseMemory | ✅ 已有 |
| 记忆类型层：Working / Episodic / Semantic / Perceptual | ✅ 四类铺开，Perceptual 建议冻结 |
| 存储后端层：Qdrant / Neo4j / SQLite | ⚠️ Neo4j 未落地 |
| 嵌入服务层：DashScope / Local / TFIDF | ✅ 已切 MaaS (qwen3.7-text-embedding) |

---

## 5. 已知缺口（来源：temp.txt 完整诊断）

### P0：进 RAG 前必须修

| # | 问题 | 状态 |
|---|------|------|
| 1 | 检索相关性丢失 → 只按 importance 排序 | ✅ 本次修复（RRF + relevance_score 写回） |
| 2 | user_id 隔离不彻底 | ❌ 下一步 |
| 3 | consolidate 只是复制，不是巩固 | ❌ |
| 4 | forget 接口没进 BaseMemory 契约 | ❌ |

### P1：Memory v0.1 应完成

| # | 问题 |
|---|------|
| 5 | 嵌入接口没区分 query/document |
| 6 | 语义记忆≠知识图谱（Neo4j 先砍掉） |
| 7 | 情景记忆缺时间范围查询、session 还原 |
| 8 | 感知记忆建议冻结 |

---

## 6. 前沿方向速览（来源：temp.txt 第四部分）

| 论文 | 会议 | 一句话 | 对 Hi-Agent 的启示 |
|------|------|--------|-------------------|
| **LoCoMo** | ACL 2024 | 超长多会话对话基准，含时间推理/知识更新/拒答 | 下一版 eval 的数据类型参考 |
| **HippoRAG** | NeurIPS 2024 | LLM+KG+PageRank 做跨文档多跳检索 | 等有多跳失败案例再加图 |
| **A-MEM** | NeurIPS 2025 | Zettelkasten 式记忆：链接/版本/取代 | SemanticMemory 加 `derived_from`/`supersedes` |
| **RMM** | ACL 2025 | 反思式记忆管理：写入前+检索后双层反思 | consolidate 不只是复制，检索失败要反馈 |
| **Workflow Memory** | ICML 2025 | 从轨迹抽取可复用 workflow | 第五类记忆优先做 Procedural |
| **MEM1 / MemAgent** | ICLR 2026 | RL 学习记忆策略 | 先别看，当前把外部 Memory 状态做干净 |

---

## 7. 下一步路线图（来源：temp.txt 五 Commit）

```
Commit 1 ✅ test: pytest 迁移（已完成，32 passed）
Commit 2 ⬜ fix: tenant isolation
Commit 3 ✅ fix: 检索相关性（本次博客）
Commit 4 ⬜ feat: deterministic consolidation
Commit 5 ⬜ feat: sparse RAG vertical slice (FTS/BM25 baseline)
```

---

## 8. 收尾

本次改动的本质不是"加了一个参数"——是把"没有就是没有"从 wishful thinking 变成了可测试、可度量的系统行为。

```python
# 之前：永远返回 top-5
results = manager.retrieve_memories("北京旅行酒店")  # → 5条不相关记忆

# 现在：低于阈值就空
results = manager.retrieve_memories("北京旅行酒店", min_relevance_score=0.35)  # → []
```

`abstention_recall` 从 0.0 变成 0.30（16维 FakeEmbedder 下）。真实 qwen3.7-text-embedding (1024维) 预期能达 0.6+。

---

**标签**：`hi-agent` `memory` `eval` `abstention` `retrieval`

**关联**：Hello-Agents Ch8 / temp.txt Memory 诊断 / S5 训练营独立评估
