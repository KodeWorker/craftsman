import types
from pathlib import Path

import pytest

from craftsman.memory.structure import StructureDB


@pytest.fixture
def in_memory_db():
    db = StructureDB(path=Path(":memory:"))
    yield db
    db.close()


@pytest.fixture
def session_id(in_memory_db):
    return in_memory_db.create_session()


@pytest.fixture
def make_chunk():
    def _make(
        content=None,
        reasoning_content=None,
        usage=None,
        tool_calls=None,
        finish_reason=None,
    ):
        delta = types.SimpleNamespace(
            content=content,
            reasoning_content=reasoning_content,
            tool_calls=tool_calls,
        )
        choice = types.SimpleNamespace(
            delta=delta, finish_reason=finish_reason
        )
        return types.SimpleNamespace(choices=[choice], usage=usage)

    return _make


@pytest.fixture
def make_tool_call_delta():
    def _make(index=0, id=None, name=None, arguments=""):
        fn = types.SimpleNamespace(name=name, arguments=arguments)
        return types.SimpleNamespace(index=index, id=id, function=fn)

    return _make


@pytest.fixture
def make_usage():
    def _make(prompt=10, completion=5, total=15, reasoning=0):
        details = types.SimpleNamespace(reasoning_tokens=reasoning)
        return types.SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            completion_tokens_details=details,
        )

    return _make
