import pytest

from state_bench.agents.base import BaseAgent
from state_bench.agents.loader import load_root_agent_class, load_root_client_class
from state_bench.client import BaseLLMClient


def test_loads_state_bench_subclass_from_root_agents_by_path(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "my_agent.py").write_text(
        "from state_bench.agents.base import BaseAgent\n"
        "class MyMemoryAgent(BaseAgent):\n"
        "    def retrieve_learnings(self, query, top_k=3):\n"
        "        return [query][:top_k]\n"
    )

    def fail_import(name, *args, **kwargs):
        if name == "agents" or name.startswith("agents."):
            raise AssertionError("root agent loader must not import the agents package by name")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    cls = load_root_agent_class("MyMemoryAgent", root=tmp_path)

    assert cls.__name__ == "MyMemoryAgent"
    assert issubclass(cls, BaseAgent)


def test_rejects_non_state_bench_subclass(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "bad_agent.py").write_text("class MyMemoryAgent:\n    pass\n")

    with pytest.raises(TypeError, match="BaseAgent"):
        load_root_agent_class("MyMemoryAgent", root=tmp_path)


def test_missing_root_agent_class_raises_clear_error(tmp_path):
    (tmp_path / "agents").mkdir()

    with pytest.raises(ValueError, match="not found"):
        load_root_agent_class("MissingAgent", root=tmp_path)


def test_rejects_duplicate_root_agent_class_names(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    for name in ("a.py", "b.py"):
        (agents_dir / name).write_text(
            "from state_bench.agents.base import BaseAgent\nclass MyAgent(BaseAgent):\n    pass\n"
        )

    with pytest.raises(ValueError, match="multiple root agents"):
        load_root_agent_class("MyAgent", root=tmp_path)


def test_missing_root_agents_directory_raises_clear_error(tmp_path):
    with pytest.raises(ValueError, match="No root-level agents directory"):
        load_root_agent_class("MissingAgent", root=tmp_path)


def test_loads_client_subclass_from_root_clients_by_path(tmp_path, monkeypatch):
    clients_dir = tmp_path / "clients"
    clients_dir.mkdir()
    (clients_dir / "my_client.py").write_text(
        "from state_bench.client import BaseLLMClient\nclass MyLLMClient(BaseLLMClient):\n    pass\n"
    )

    def fail_import(name, *args, **kwargs):
        if name == "clients" or name.startswith("clients."):
            raise AssertionError("root client loader must not import the clients package by name")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)

    cls = load_root_client_class("MyLLMClient", root=tmp_path)

    assert cls.__name__ == "MyLLMClient"
    assert issubclass(cls, BaseLLMClient)


def test_rejects_non_base_llm_client_subclass(tmp_path):
    clients_dir = tmp_path / "clients"
    clients_dir.mkdir()
    (clients_dir / "bad_client.py").write_text("class MyLLMClient:\n    pass\n")

    with pytest.raises(TypeError, match="BaseLLMClient"):
        load_root_client_class("MyLLMClient", root=tmp_path)


def test_rejects_duplicate_root_client_class_names(tmp_path):
    clients_dir = tmp_path / "clients"
    clients_dir.mkdir()
    for name in ("a.py", "b.py"):
        (clients_dir / name).write_text(
            "from state_bench.client import BaseLLMClient\nclass MyClient(BaseLLMClient):\n    pass\n"
        )

    with pytest.raises(ValueError, match="multiple root clients"):
        load_root_client_class("MyClient", root=tmp_path)


def test_missing_root_client_class_raises_clear_error(tmp_path):
    (tmp_path / "clients").mkdir()

    with pytest.raises(ValueError, match="not found"):
        load_root_client_class("MissingClient", root=tmp_path)


def test_missing_root_clients_directory_raises_clear_error(tmp_path):
    with pytest.raises(ValueError, match="No root-level clients directory"):
        load_root_client_class("MissingClient", root=tmp_path)


def test_client_loader_reports_import_errors(tmp_path):
    clients_dir = tmp_path / "clients"
    clients_dir.mkdir()
    (clients_dir / "broken.py").write_text("raise RuntimeError('boom')\n")

    with pytest.raises(ValueError, match="Import errors: .*RuntimeError: boom"):
        load_root_client_class("MissingClient", root=tmp_path)
