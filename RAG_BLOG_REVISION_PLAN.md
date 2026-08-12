# RAG 博客修订方案

目标文章：`2026-07-22-agent-rag.md`

## 先修正文章中的状态表达

当前文章前 1～6 节是概览，7～8 节再次介绍 Loader 和 Splitter，重复较多。建议保留一段短概览，然后直接进入实现记录。下列内容还需要按仓库状态改写：

- 第 47 行所写的 `MappingProxyType` 在本次修改前并未实现；现在已经补上，但只能保证 metadata 顶层不可修改，嵌套的 list/dict 仍然可变。
- 第 75、169 行描述的旧 token 估算会重复计算纯中文连续文本，也会严重低估无空格英文、长标识符和代码。不能再写成“偏差可控”，因为目前没有与目标模型 tokenizer 的误差统计。
- 第 79 行把代码块保护归因于代码块前后空行，原实现也没有围栏状态机。现在能识别反引号和波浪线围栏；超出预算的代码块仍会降级硬切，这一点应明确写出。
- 第 80 行的 `INSERT OR IGNORE` 无法清理文档更新后遗留的旧 chunk。Index manifest 和旧版本清理尚未实现，应该放进“下一步”，不能写成已有能力。
- 第 84～88 行描述的 ContextBuilder、提示词约束和生成后引用验证，目前对应文件仍是空壳。建议改成设计目标，或等实现并测试后再写为完成状态。
- 第 173 行之后的 Index、Retriever、Fusion、Reranker 和 Evaluation 都还是提纲。保留提纲没有问题，但需统一使用“准备实现”或“尚未实现”。

## 推荐的新文章结构

### 1. 从一个错误计数开始

用真实输入开篇，不先讲 RAG 的价值。可以直接放本次复现结果：

```text
sample                         old  new
你好世界                          5    4
hello world                       2    4
你好world                         3    4
hello_world_without_spaces        1    7
def foo(x): return x + 1           6   11
```

紧接着解释：旧公式是 `CJK 字符数 + len(text.split())`。`你好世界` 已经按 4 个 CJK 字符计数，`split()` 又把整串文本算作 1 个词；`hello_world_without_spaces` 则只得到 1。这里不要声称新值等于某个真实模型的 token 数，新算法只是无依赖、偏保守的预算估计。

### 2. 这次实际完成到哪里

建议加入状态表，把代码现状和规划分开：

| 模块 | 当前状态 | 本次验证 |
| --- | --- | --- |
| 领域模型 | 已实现 | metadata 顶层不可修改测试 |
| Text/Markdown/MarkItDown Loader | 已实现基础路径 | 租户上下文、编码、异常 frontmatter 测试 |
| Recursive/Markdown Splitter | 已实现 baseline | token 预算、偏移、围栏、超长段落测试 |
| Index/Retriever | 文件或提纲阶段 | 尚未验证 |
| Context Builder/Generator/Evaluation | 设计阶段 | 尚未验证 |

### 3. 为什么先定义 Document 和 Chunk

先展示精简后的字段，再解释每个字段由谁产生：

```python
@dataclass(frozen=True)
class Document:
    document_id: str
    user_id: str
    namespace: str
    source: str
    text: str
    checksum: str
    metadata: Mapping[str, Any]
```

随后展示 `Document.build()` 中 checksum 和 document_id 的生成式，以及 `_freeze_mapping()`。需要补一句：`frozen=True` 只禁止字段重新赋值，普通 dict 的内容仍可修改，因此本次改成了 `MappingProxyType(dict(metadata))`。这仍是浅层冻结。

### 4. Loader 为什么必须接收租户上下文

把旧接口和新接口并排展示：

```python
# 旧接口会偷偷写入 default
def load(self, path: str | Path) -> Document: ...

# 当前接口要求调用方明确传入隔离边界
def load(
    self,
    path: str | Path,
    *,
    user_id: str,
    namespace: str,
) -> Document: ...
```

这里重点记录问题：`Document` 是 frozen 对象，Loader 先写 `default` 再让上层覆盖并不可行；重建对象又会让字段归属变模糊。本次让 Loader 在构造 Document 时一次写对。

再加入两个小坑：

1. `_try_read_text_with_encoding()` 返回实际成功的编码，metadata 不再永远写 `utf-8`。
2. frontmatter 解析失败时保留全文，不能一边吞掉 YAML 异常，一边仍删除 frontmatter 区域。

### 5. TokenCounter 如何把长度单位统一起来

先给协议，再给近似实现的核心：

```python
class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class SplitterParams:
    chunk_size: int = 800
    chunk_overlap: int = 120
    token_counter: TokenCounter = field(
        default=DEFAULT_TOKEN_COUNTER
    )
```

解释旧 Splitter 的另一个问题：递归阶段使用 `len(split)` 判断字符数，合并阶段使用估算 token 数，同一个 `chunk_size` 实际代表两个单位。现在递归、硬切、合并和 overlap 都调用同一个 counter。

需要明确限制：近似 counter 不绑定模型。准备接入具体 embedding/LLM 时，应为所用 tokenizer 实现 `TokenCounter`，并增加“估算值与真实值差异”的语料测试。不要在尚未测量前写准确率。

### 6. 为什么位置偏移会错

用旧过程说明问题：`text.split(separator)` 丢掉分隔符，之后靠 `char_cursor += len(split)` 推算位置；最后一个 chunk 还把已经走到文末的 cursor 当成起点。建议放一个不变量：

```python
assert document.text[chunk.start_char:chunk.end_char] == chunk.content
```

然后展示 `_Span(start, end)`。递归过程始终传递原文偏移，最终 content 直接从原文切片得到。这个代码块比只解释 `start_char/end_char` 更容易复现。

### 7. Markdown 标题和代码围栏如何解析

建议放两个容易误判的输入：

````markdown
# 正常标题

```python
# 这是 Python 注释，不是 Markdown 标题
```

~~~text
## 这也不是标题
~~~
````

随后展示两个正则和围栏状态：

```python
_ATX_HEADING_RE = re.compile(
    r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$"
)
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
```

说明当前实现会保护正常大小的围栏代码块；如果单个代码块超过 `chunk_size`，为了兑现硬预算仍会切分。后续可以在 metadata 中增加 `split_reason="oversized_code_block"`，目前尚未实现。

### 8. 用测试说明当前结论

保留本次实际命令和输出：

```powershell
D:\Anaconda\python.exe -m pytest -q --basetemp .pytest-final
```

```text
........................................ [100%]
40 passed, 2 warnings
```

两条 warning 来自 Memory 模块使用的 Pydantic v1 风格配置，与本次 RAG 修改无关。测试章节可挑四个断言讲清楚：纯中文不重复计数、chunk 不超预算、原文偏移一致、代码围栏中的 `#` 不被当成标题。

### 9. 当前限制与下一步

文章此时只列可操作项：

- 给目标 embedding 模型增加精确 tokenizer counter，并建立误差样本集。
- 明确 Markdown chunk 的标题正文策略，以及跨标题合并规则。
- 给超长代码块和表格记录 `split_reason`。
- 实现 Index manifest、原子更新和旧 chunk 清理。
- Index 完成后再写 BM25/Dense/Hybrid 的实测章节。

## 编辑建议

- 删除或大幅压缩现有 1～6 节，避免 Loader/Splitter 在 4～5 节和 7～8 节各讲一遍。
- 把“根治、牢牢锁死、宝贵、巨大的、至关重要、智能”等无法由测试证明的词换成具体行为。
- 每节采用“现象 → 原因 → 修改 → 测试 → 限制”的顺序。
- 代码块优先截取可运行的最小片段；完整实现通过仓库文件链接承接。
- 文章 frontmatter 的 `updated` 应在正式改稿时更新，`summary` 和 `topics` 仍需补齐。
