from unittest.mock import MagicMock

import pytest


@pytest.fixture
def provider(mocker):
    mocker.patch(
        "craftsman.provider.get_config",
        return_value={
            "provider": {
                "model": "test/model",
                "debug": False,
                "ctx_size": 4096,
                "input_cost_per_token": 0.001,
                "output_cost_per_token": 0.002,
            }
        },
    )
    mock_auth = mocker.patch("craftsman.provider.Auth")
    mock_auth.get_password.return_value = None
    mocker.patch(
        "craftsman.provider.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()
    from craftsman.provider import Provider

    return Provider()


@pytest.fixture
def provider_debug(mocker):
    mocker.patch(
        "craftsman.provider.get_config",
        return_value={
            "provider": {
                "model": "test/model",
                "debug": True,
                "ctx_size": 4096,
                "input_cost_per_token": 0.0,
                "output_cost_per_token": 0.0,
            }
        },
    )
    mock_auth = mocker.patch("craftsman.provider.Auth")
    mock_auth.get_password.return_value = None
    mocker.patch(
        "craftsman.provider.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()
    from craftsman.provider import Provider

    return Provider()


# --- model_response_parser ---


async def _collect(gen):
    results = []
    async for item in gen:
        results.append(item)
    return results


async def _stream(*chunks):
    for chunk in chunks:
        yield chunk


async def test_parser_plain_content(provider, make_chunk):
    chunk = make_chunk(content="hello")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert results == [("content", "hello")]


async def test_parser_usage_chunk(provider, make_chunk, make_usage):
    usage = make_usage()
    chunk = make_chunk(usage=usage)
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert any(k == "__usage__" for k, _ in results)


async def test_parser_native_reasoning_content(provider, make_chunk):
    chunk = make_chunk(reasoning_content="think hard")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert ("reasoning", "think hard") in results
    assert not any(k == "content" for k, _ in results)


async def test_parser_inline_think_tags(provider, make_chunk):
    chunk = make_chunk(content="<think>reason</think>answer")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert ("reasoning", "reason") in results
    assert ("content", "answer") in results


async def test_parser_think_split_across_chunks(provider, make_chunk):
    c1 = make_chunk(content="<think>rea")
    c2 = make_chunk(content="son</think>ans")
    results = await _collect(provider.model_response_parser(_stream(c1, c2)))
    reasoning = "".join(t for k, t in results if k == "reasoning")
    content = "".join(t for k, t in results if k == "content")
    assert reasoning == "reason"
    assert content == "ans"


async def test_parser_content_before_think(provider, make_chunk):
    chunk = make_chunk(content="pre<think>think</think>")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert ("content", "pre") in results
    assert ("reasoning", "think") in results


async def test_parser_none_content_skipped(provider, make_chunk):
    chunk = make_chunk(content=None)
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert not any(k == "content" for k, _ in results)


async def test_parser_empty_stream(provider):
    async def empty():
        return
        yield  # make it an async generator

    results = await _collect(provider.model_response_parser(empty()))
    assert results == []


# --- cost ---


def test_cost_calculation(provider):
    assert abs(provider.cost(100, 50) - 0.2) < 1e-9


def test_cost_zero_tokens(provider):
    assert provider.cost(0, 0) == 0.0


# --- completion ---


async def test_completion_yields_content_and_meta(
    provider, mocker, make_chunk, make_usage
):
    usage = make_usage(prompt=5, completion=3, total=8, reasoning=0)
    c1 = make_chunk(content="hello")
    c2 = make_chunk(usage=usage)

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield c1
            yield c2

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(
        provider.completion([{"role": "user", "content": "hi"}])
    )
    kinds = [k for k, _ in results]
    assert "content" in kinds
    assert "meta" in kinds


async def test_completion_suppresses_reasoning_when_debug_false(
    provider, mocker, make_chunk
):
    c1 = make_chunk(content="<think>hidden</think>visible")

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield c1

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(provider.completion([]))
    assert not any(k == "reasoning" for k, _ in results)
    assert any(k == "content" for k, _ in results)


async def test_completion_yields_reasoning_when_debug_true(
    provider_debug, mocker, make_chunk
):
    c1 = make_chunk(content="<think>visible</think>answer")

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield c1

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(provider_debug.completion([]))
    assert any(k == "reasoning" for k, _ in results)


async def test_completion_meta_cost(mocker, make_chunk, make_usage):
    mocker.patch(
        "craftsman.provider.get_config",
        return_value={
            "provider": {
                "model": "test/model",
                "debug": False,
                "ctx_size": 4096,
                "input_cost_per_token": 0.001,
                "output_cost_per_token": 0.002,
            }
        },
    )
    mock_auth = mocker.patch("craftsman.provider.Auth")
    mock_auth.get_password.return_value = None
    mocker.patch(
        "craftsman.provider.CraftsmanLogger"
    ).return_value.get_logger.return_value = MagicMock()

    from craftsman.provider import Provider

    p = Provider()

    usage = make_usage(prompt=100, completion=50, total=150, reasoning=0)
    chunk = make_chunk(usage=usage)

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield chunk

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(p.completion([]))
    meta = next(v for k, v in results if k == "meta")
    assert abs(meta["cost"] - 0.2) < 1e-9


async def test_completion_meta_ctx_used_excludes_reasoning_tokens(
    provider, mocker, make_chunk, make_usage
):
    usage = make_usage(prompt=10, completion=10, total=20, reasoning=5)
    chunk = make_chunk(usage=usage)

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield chunk

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(provider.completion([]))
    meta = next(v for k, v in results if k == "meta")
    assert meta["ctx_used"] == 15


async def test_completion_passes_messages_to_litellm(
    provider, mocker, make_chunk
):
    chunk = make_chunk(content="hi")
    called_with = {}

    async def fake_acompletion(**kwargs):
        called_with.update(kwargs)

        async def _stream():
            yield chunk

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    messages = [{"role": "user", "content": "test"}]
    await _collect(provider.completion(messages))
    assert called_with["messages"] == messages


# --- tool_call parsing ---


async def test_parser_tool_call_single_chunk(
    provider, make_chunk, make_tool_call_delta
):
    tc = make_tool_call_delta(
        index=0,
        id="call_abc",
        name="bash:grep",
        arguments='{"pattern":"error"}',
    )
    chunk = make_chunk(tool_calls=[tc], finish_reason="tool_calls")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert results == [
        (
            "tool_call",
            {
                "id": "call_abc",
                "name": "bash:grep",
                "arguments_raw": '{"pattern":"error"}',
            },
        )
    ]


async def test_parser_tool_call_fragments_across_chunks(
    provider, make_chunk, make_tool_call_delta
):
    tc1 = make_tool_call_delta(
        index=0, id="call_xyz", name="bash:g", arguments=""
    )
    tc2 = make_tool_call_delta(index=0, id=None, name="rep", arguments='{"pa')
    tc3 = make_tool_call_delta(
        index=0, id=None, name=None, arguments='ttern":"x"}'
    )
    c1 = make_chunk(tool_calls=[tc1])
    c2 = make_chunk(tool_calls=[tc2])
    c3 = make_chunk(tool_calls=[tc3], finish_reason="tool_calls")
    results = await _collect(
        provider.model_response_parser(_stream(c1, c2, c3))
    )
    assert results == [
        (
            "tool_call",
            {
                "id": "call_xyz",
                "name": "bash:grep",
                "arguments_raw": '{"pattern":"x"}',
            },
        )
    ]


async def test_parser_tool_call_multiple_tools(
    provider, make_chunk, make_tool_call_delta
):
    tc0 = make_tool_call_delta(
        index=0, id="call_1", name="bash:ls", arguments='{"path":"/"}'
    )
    tc1 = make_tool_call_delta(
        index=1, id="call_2", name="bash:grep", arguments='{"pattern":"x"}'
    )
    chunk = make_chunk(tool_calls=[tc0, tc1], finish_reason="tool_calls")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    tool_calls = [v for k, v in results if k == "tool_call"]
    assert len(tool_calls) == 2
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[1]["id"] == "call_2"


async def test_parser_tool_call_no_content_emitted(
    provider, make_chunk, make_tool_call_delta
):
    tc = make_tool_call_delta(
        index=0, id="call_abc", name="bash:ls", arguments="{}"
    )
    chunk = make_chunk(tool_calls=[tc], finish_reason="tool_calls")
    results = await _collect(provider.model_response_parser(_stream(chunk)))
    assert not any(k == "content" for k, _ in results)


async def test_completion_passes_tools_to_litellm(
    provider, mocker, make_chunk
):
    chunk = make_chunk(content="ok")
    called_with = {}

    async def fake_acompletion(**kwargs):
        called_with.update(kwargs)

        async def _stream():
            yield chunk

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    tools = [{"name": "bash:grep", "parameters": {}}]
    await _collect(provider.completion([], tools=tools))
    assert called_with.get("tools") == tools
    assert called_with.get("tool_choice") == "auto"


async def test_completion_no_tools_omits_tools_kwarg(
    provider, mocker, make_chunk
):
    chunk = make_chunk(content="ok")
    called_with = {}

    async def fake_acompletion(**kwargs):
        called_with.update(kwargs)

        async def _stream():
            yield chunk

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    await _collect(provider.completion([]))
    assert "tools" not in called_with
    assert "tool_choice" not in called_with


async def test_completion_yields_tool_call_from_stream(
    provider, mocker, make_chunk, make_tool_call_delta
):
    tc = make_tool_call_delta(
        index=0, id="call_1", name="bash:ls", arguments='{"path":"/"}'
    )
    c1 = make_chunk(tool_calls=[tc], finish_reason="tool_calls")

    async def fake_acompletion(**kwargs):
        async def _stream():
            yield c1

        return _stream()

    mocker.patch("craftsman.provider.litellm").acompletion = fake_acompletion

    results = await _collect(provider.completion([]))
    tool_calls = [v for k, v in results if k == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0] == {
        "id": "call_1",
        "name": "bash:ls",
        "arguments_raw": '{"path":"/"}',
    }
