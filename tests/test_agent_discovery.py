import pytest

from state_bench.agents.loader import load_root_agent_class
from state_bench.agents.state_bench import StateBenchAgent


def test_loads_state_bench_subclass_from_root_agents_by_path(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "my_agent.py").write_text(
        "from state_bench.agents.state_bench import StateBenchAgent\n"
        "class MyMemoryAgent(StateBenchAgent):\n"
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
    assert issubclass(cls, StateBenchAgent)


def test_rejects_non_state_bench_subclass(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "bad_agent.py").write_text("class MyMemoryAgent:\n    pass\n")

    with pytest.raises(TypeError, match="StateBenchAgent"):
        load_root_agent_class("MyMemoryAgent", root=tmp_path)


def test_missing_root_agent_class_raises_clear_error(tmp_path):
    (tmp_path / "agents").mkdir()

    with pytest.raises(ValueError, match="not found"):
        load_root_agent_class("MissingAgent", root=tmp_path)
