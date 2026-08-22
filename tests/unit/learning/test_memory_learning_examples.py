from memory.base import BaseMemory, MemoryConfig, MemoryItem
from memory.embedding import FakeEmbedder
from memory.manager import MemoryManager
from memory.storage.document import SQLiteDocumentStore
from memory.types.episodic import EpisodicMemory
from memory.types.perceptual import PerceptualMemory
from memory.types.semantic import SemanticMemory


def test_memory_item_and_abstract_base_contract():
    item = MemoryItem(
        content="Python learner",
        memory_type="semantic",
        importance=0.9,
        metadata={"source": "learning"},
    )

    assert item.to_dict()["content"] == "Python learner"
    assert "[semantic] Python learner" in item.get_summary()

    try:
        BaseMemory(MemoryConfig())
    except TypeError:
        pass
    else:
        raise AssertionError("BaseMemory should remain abstract")


def test_working_memory_manager_add_retrieve_and_forget(tmp_path):
    manager = MemoryManager(
        config=MemoryConfig(
            database_path=str(tmp_path / "working.db"),
            working_memory_capacity=3,
            qdrant_url=None,
        ),
        user_id="learner",
        enable_working=True,
        enable_episodic=False,
        enable_semantic=False,
    )

    manager.add_memory("Python developer", memory_type="working", importance=0.9)
    manager.add_memory("Frontend developer", memory_type="working", importance=0.4)

    results = manager.retrieve_memories("Python", limit=3)
    report = manager.forget_memories(strategy="importance_based", threshold=0.8)

    assert results[0].content == "Python developer"
    assert report.deleted_count == 1


def test_sqlite_document_store_round_trip(tmp_path):
    store = SQLiteDocumentStore(str(tmp_path / "documents.db"))

    assert store.insert("id-1", "remember this", "episodic", importance=0.8)
    assert store.get_by_id("id-1")["content"] == "remember this"
    assert store.query(memory_type="episodic", min_importance=0.8)[0]["id"] == "id-1"
    assert store.clear() == 1


def test_episodic_semantic_and_perceptual_examples_share_memory_contract(tmp_path):
    embedder = FakeEmbedder()
    config = MemoryConfig(database_path=str(tmp_path / "typed.db"), qdrant_url=None)

    episodic = EpisodicMemory(config, embedder)
    semantic = SemanticMemory(config, embedder)
    perceptual = PerceptualMemory(config, embedder)

    episodic_item = MemoryItem(content="finished a project", memory_type="episodic")
    semantic_item = MemoryItem(content="Python is readable", memory_type="semantic")
    perceptual_item = MemoryItem(content="a screenshot of Python code", memory_type="perceptual")

    assert episodic.add(episodic_item) == episodic_item.id
    assert semantic.add(semantic_item) == semantic_item.id
    assert perceptual.add(perceptual_item, modality="image") == perceptual_item.id
    assert episodic.retrieve("project")
    assert semantic.retrieve("Python")
    assert perceptual.retrieve("Python", modality="image")
