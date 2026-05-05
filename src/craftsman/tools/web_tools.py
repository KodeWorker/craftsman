import html2text
import httpx
from readability import Document

from craftsman.configure import get_config


def _web_cfg() -> dict:
    return get_config().get("web", {})


async def web_search(args: dict) -> dict:
    cfg = _web_cfg()
    searxng_url = cfg.get("searxng_url", "").strip()
    if not searxng_url:
        return {"error": "searxng_url not configured in craftsman.yaml"}
    query = args["query"]
    max_results = int(
        args.get("max_results", cfg.get("search", {}).get("max_results", 10))
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{searxng_url.rstrip('/')}/search",
                params={"q": query, "format": "json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        return {"error": f"searxng unreachable at {searxng_url}"}
    except Exception as e:
        return {"error": str(e)}
    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in data.get("results", [])[:max_results]
    ]
    return {"results": results, "count": len(results)}


async def web_fetch_url(args: dict) -> dict:
    cfg = _web_cfg()
    url = args["url"]
    max_chars = int(
        args.get("max_chars", cfg.get("fetch", {}).get("max_chars", 8000))
    )
    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True
        ) as client:
            resp = await client.get(
                url, headers={"User-Agent": "craftsman/1.0"}
            )
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        return {"error": str(e)}
    try:
        doc = Document(html)
        title = doc.title()
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        markdown = h.handle(doc.summary())
    except Exception as e:
        return {"error": f"parse error: {e}"}
    if len(markdown) > max_chars:
        markdown = (
            markdown[:max_chars] + f"\n[TRUNCATED after {max_chars} chars]"
        )
    return {"title": title, "url": url, "content": markdown}
