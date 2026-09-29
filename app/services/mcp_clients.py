"""Thin HTTP-MCP client layer for the three artifact-generation sibling
services (Presenton, mcp-ms-office-documents, the report-PDF server) — see
docker-compose.yml. All three are reached over `streamable_http`, not stdio;
nothing MCP-related spawns a subprocess inside this backend's own container.

Deliberately narrow: `get_allowed_tool` only ever hands back one of a small,
explicit allowlist per server, never the full raw tool surface a service
exposes (e.g. mcp-ms-office-documents also has email/XML tools this app never
calls) — see the plan's security notes on why that allowlist matters when
tool arguments are ultimately LLM-influenced content.
"""

from __future__ import annotations

from functools import lru_cache

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from app.config import get_settings

# server_name -> the only tool names this app is ever allowed to invoke on it.
_ALLOWED_TOOLS: dict[str, frozenset[str]] = {
    # Confirmed live: Presenton's real MCP surface is
    # {upload_files, start_standard_presentation, list_templates,
    # upload_template_assets, start_template_generation, get_job_status,
    # start_smart_presentation} — not the guessed create_presentation_from_json.
    "presenton": frozenset({"start_standard_presentation", "get_job_status"}),
    # Confirmed live: the advertised tool name really is
    # create_word_from_markdown (the original guess) — "create_word_document"
    # in the earlier validation error was the tool's internal Python
    # function name, not its MCP name. Its argument is markdown_content,
    # confirmed by that same validation error.
    "office_docs": frozenset({"create_word_from_markdown"}),
    # Confirmed against cyanheads/docgen-mcp-server's own README — unlike the
    # other two servers, this tool name/shape is verified, not a guess.
    "pdf": frozenset({"docgen_render_pdf"}),
}


@lru_cache(maxsize=1)
def _client() -> MultiServerMCPClient:
    settings = get_settings()
    return MultiServerMCPClient(
        {
            "presenton": {
                "transport": "streamable_http",
                "url": f"{settings.presenton_url}/mcp",
                "headers": (
                    {"Authorization": f"Bearer {settings.presenton_api_key}"}
                    if settings.presenton_api_key
                    else None
                ),
            },
            "office_docs": {
                "transport": "streamable_http",
                "url": f"{settings.mcp_office_docs_url}/mcp",
                "headers": (
                    {"x-api-key": settings.mcp_office_docs_api_key}
                    if settings.mcp_office_docs_api_key
                    else None
                ),
            },
            "pdf": {
                "transport": "streamable_http",
                "url": f"{settings.mcp_pdf_url}/mcp",
            },
        }
    )


class MCPToolNotAllowedError(RuntimeError):
    pass


async def get_allowed_tool(server_name: str, tool_name: str) -> BaseTool:
    """Fetches `tool_name` from `server_name`, scoped to that server only —
    never loads/exposes any other tool the server happens to offer."""
    if tool_name not in _ALLOWED_TOOLS.get(server_name, frozenset()):
        raise MCPToolNotAllowedError(
            f"'{tool_name}' is not on the allowlist for MCP server '{server_name}'."
        )
    tools = await _client().get_tools(server_name=server_name)
    for candidate in tools:
        if candidate.name == tool_name:
            return candidate
    raise MCPToolNotAllowedError(
        f"MCP server '{server_name}' did not advertise expected tool '{tool_name}' "
        f"(available: {[t.name for t in tools]}) — the server's tool surface may "
        "have changed; update _ALLOWED_TOOLS/the driver in app.services.artifact_generation."
    )
