"""Evidence acquisition before generation, independent of the LLM provider."""
import asyncio
from urllib.parse import urlsplit

from models import credential


def endpoint(config):
    name = config["url_env"]
    url = credential(name)
    target = urlsplit(url)
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        raise ValueError(f"Expected HTTPS URL without embedded credentials in {name}")
    return url


def headers(config):
    name = config.get("token_env")
    return {"Authorization": "Bearer " + credential(name)} if name else {}


def passages(items, limit):
    if not isinstance(items, list):
        raise ValueError("Search results must be a list")
    return [{"id": str(item["id"])[:200], "text": item["text"][:8000]}
            for item in items[:limit]]


def retrieve(config, question, root):
    mode = config["mode"]
    limit = config.get("top_k", 3)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("top_k must be an integer between 1 and 20")
    if mode == "none":
        return [], []
    if mode == "direct-file":
        files = [(root / name).resolve() for name in config["files"]]
        if not files or any(path.suffix.lower() not in {".txt", ".md", ".pdf"}
                            for path in files):
            raise ValueError("direct-file requires .txt, .md or .pdf files")
        if sum(path.stat().st_size for path in files) > 5 * 1024 * 1024:
            raise ValueError("Total direct-file size exceeds the MVP limit of 5 MiB")
        return files, []
    if mode == "fixture-search":
        import json
        items = json.loads((root / config["path"]).read_text(encoding="utf-8"))
        return [], passages(items.get(question, []), limit)
    if mode == "external-search":
        import httpx

        response = httpx.post(endpoint(config), headers=headers(config), timeout=30,
                              json={"query": question, "top_k": limit})
        response.raise_for_status()
        return [], passages(response.json()["results"], limit)
    raise ValueError(f"Unknown retrieval mode: {mode}")


async def remote_tool(config, question):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    arguments = dict(config.get("arguments", {}))
    arguments[config.get("question_arg", "query")] = question
    async with asyncio.timeout(45):
        async with streamablehttp_client(
            endpoint(config), headers=headers(config), timeout=30, sse_read_timeout=30,
        ) as streams:
            async with ClientSession(*streams[:2]) as session:
                await session.initialize()
                result = await session.call_tool(config["tool"], arguments=arguments)
    if result.isError:
        raise RuntimeError("Configured MCP tool returned an error")
    text = "\n".join(block.text for block in result.content if block.type == "text")
    if not text.strip():
        raise ValueError("Configured MCP tool must return text content")
    return text[:16000]


def mcp_evidence(config, question, root):
    mode = config["mode"]
    if mode == "none":
        return []
    if mode == "fixture":
        text = ((root / config["path"]).read_text(encoding="utf-8-sig")
                if "path" in config else config["text"])
    elif mode == "remote":
        text = asyncio.run(remote_tool(config, question))
    else:
        raise ValueError(f"Unknown MCP mode: {mode}")
    return [{"id": config["tool"], "text": text[:16000]}]
