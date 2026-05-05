from unittest.mock import AsyncMock, MagicMock, patch

from craftsman.tools.web_tools import web_fetch_url, web_search

SEARXNG_RESULTS = {
    "results": [
        {
            "title": "Result 1",
            "url": "https://example.com/1",
            "content": "snippet 1",
        },
        {
            "title": "Result 2",
            "url": "https://example.com/2",
            "content": "snippet 2",
        },
        {
            "title": "Result 3",
            "url": "https://example.com/3",
            "content": "snippet 3",
        },
    ]
}


def _mock_cfg(
    searxng_url="http://localhost:8080", max_results=10, max_chars=8000
):
    return {
        "searxng_url": searxng_url,
        "search": {"max_results": max_results},
        "fetch": {"max_chars": max_chars},
    }


# ── web:search ───────────────────────────────────────────────────────────────


async def test_search_missing_config_returns_error():
    with patch(
        "craftsman.tools.web_tools._web_cfg", return_value={"searxng_url": ""}
    ):
        result = await web_search({"query": "test"})
    assert "error" in result
    assert "searxng_url" in result["error"]


async def test_search_returns_results():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = SEARXNG_RESULTS

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_search({"query": "python"})

    assert "error" not in result
    assert result["count"] == 3
    assert result["results"][0]["title"] == "Result 1"
    assert result["results"][0]["url"] == "https://example.com/1"
    assert result["results"][0]["snippet"] == "snippet 1"


async def test_search_respects_max_results():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = SEARXNG_RESULTS  # 3 results

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_search({"query": "python", "max_results": 2})

    assert result["count"] == 2
    assert len(result["results"]) == 2


async def test_search_unreachable_returns_error():
    import httpx as _httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(
        side_effect=_httpx.ConnectError("Connection refused")
    )

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_search({"query": "test"})

    assert "error" in result
    assert "unreachable" in result["error"]
    assert "localhost:8080" in result["error"]


async def test_search_empty_results():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"results": []}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_search({"query": "xyzzy"})

    assert "error" not in result
    assert result["count"] == 0
    assert result["results"] == []


# ── web:fetch_url ────────────────────────────────────────────────────────────


_SAMPLE_HTML = """
<html><head><title>Test Page</title></head>
<body>
  <nav>Navigation stuff</nav>
  <article>
    <h1>Main Article</h1>
    <p>This is the main content of the page.</p>
  </article>
  <footer>Footer stuff</footer>
</body></html>
"""


async def test_fetch_url_returns_markdown():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = _SAMPLE_HTML

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_fetch_url({"url": "https://example.com"})

    assert "error" not in result
    assert result["url"] == "https://example.com"
    assert "content" in result
    assert "title" in result


async def test_fetch_url_truncates_content():
    long_html = (
        "<html><body><article>"
        + "<p>"
        + ("word " * 5000)
        + "</p>"
        + "</article></body></html>"
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = long_html

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch(
            "craftsman.tools.web_tools._web_cfg",
            return_value=_mock_cfg(max_chars=100),
        ),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_fetch_url({"url": "https://example.com"})

    assert "error" not in result
    assert "TRUNCATED" in result["content"]
    assert len(result["content"]) <= 100 + len("\n[TRUNCATED after 100 chars]")


async def test_fetch_url_http_error_returns_error():
    import httpx as _httpx

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = _httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock()
    )
    mock_client.get = AsyncMock(return_value=mock_resp)

    with (
        patch("craftsman.tools.web_tools._web_cfg", return_value=_mock_cfg()),
        patch(
            "craftsman.tools.web_tools.httpx.AsyncClient",
            return_value=mock_client,
        ),
    ):
        result = await web_fetch_url({"url": "https://example.com/missing"})

    assert "error" in result
