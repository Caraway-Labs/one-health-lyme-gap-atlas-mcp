"""Thin MCP registration for county identity resolution."""

import json

from mcp.server.mcpserver.tools.base import Tool
from mcp_types import CallToolResult, TextContent, ToolAnnotations

from atlas_lyme_mcp.application.geographies import GeographyResolver
from atlas_lyme_mcp.tools.contracts import StrictMetadata
from atlas_lyme_mcp.tools.geography_contracts import (
    GeographyArguments,
    GeographyRequest,
    GeographyResults,
    geography_input_schema,
)


def geography_tool(resolver: GeographyResolver) -> Tool:
    async def atlas_resolve_geographies(geographies: list[GeographyRequest]) -> CallToolResult:
        """Resolve 1-4 US county identities by exact five-digit FIPS or county plus state
        (name/postal abbreviation). Case/whitespace and County suffix normalization only;
        county equivalents require their full names. Preserve order and individual outcomes.
        Identity does not establish Atlas observations, evidence adequacy or comparability.
        Reference is the existing CDC/ATSDR SVI 2022 county source, not current legal boundaries.
        """
        result = await resolver.resolve(GeographyArguments(geographies=geographies))
        value = result.model_dump(exclude_none=True)
        # Nullable fields remain explicit; original input excludes absent representation fields.
        value["reference"] = result.reference.model_dump() if result.reference else None
        for entry, item in zip(value["results"], result.results, strict=True):
            entry["geography"] = item.geography.model_dump() if item.geography else None
            entry["reason"] = item.reason
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(value))], structured_content=value
        )

    tool = Tool.from_function(
        atlas_resolve_geographies,
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True
        ),
    )
    tool.fn_metadata = StrictMetadata(
        tool_name=tool.name,
        arg_model=GeographyArguments,
        output_schema=GeographyResults.model_json_schema(),
    )
    tool.parameters = geography_input_schema()
    return tool
