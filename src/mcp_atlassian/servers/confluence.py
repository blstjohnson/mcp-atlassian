"""Confluence FastMCP server instance and tool definitions."""

import json
import logging
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import BeforeValidator, Field

from mcp_atlassian.exceptions import MCPAtlassianAuthenticationError
from mcp_atlassian.servers.dependencies import get_confluence_fetcher
from mcp_atlassian.utils.decorators import (
    check_write_access,
)

logger = logging.getLogger(__name__)

confluence_mcp = FastMCP(
    name="Confluence MCP Service",
    description="Provides tools for interacting with Atlassian Confluence.",
)


@confluence_mcp.tool(tags={"confluence", "read"})
async def search(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Search query - can be either a simple text (e.g. 'project documentation') or a CQL query string. "
                "Simple queries use 'siteSearch' by default, to mimic the WebUI search, with an automatic fallback "
                "to 'text' search if not supported. Examples of CQL:\n"
                "- Basic search: 'type=page AND space=DEV'\n"
                "- Personal space search: 'space=\"~username\"' (note: personal space keys starting with ~ must be quoted)\n"
                "- Search by title: 'title~\"Meeting Notes\"'\n"
                "- Use siteSearch: 'siteSearch ~ \"important concept\"'\n"
                "- Use text search: 'text ~ \"important concept\"'\n"
                "- Recent content: 'created >= \"2023-01-01\"'\n"
                "- Content with specific label: 'label=documentation'\n"
                "- Recently modified content: 'lastModified > startOfMonth(\"-1M\")'\n"
                "- Content modified this year: 'creator = currentUser() AND lastModified > startOfYear()'\n"
                "- Content you contributed to recently: 'contributor = currentUser() AND lastModified > startOfWeek()'\n"
                "- Content watched by user: 'watcher = \"user@domain.com\" AND type = page'\n"
                '- Exact phrase in content: \'text ~ "\\"Urgent Review Required\\"" AND label = "pending-approval"\'\n'
                '- Title wildcards: \'title ~ "Minutes*" AND (space = "HR" OR space = "Marketing")\'\n'
                'Note: Special identifiers need proper quoting in CQL: personal space keys (e.g., "~username"), '
                "reserved words, numeric IDs, and identifiers with special characters."
            )
        ),
    ],
    limit: Annotated[
        int,
        Field(
            description="Maximum number of results (1-50)",
            default=10,
            ge=1,
            le=50,
        ),
    ] = 10,
    spaces_filter: Annotated[
        str | None,
        Field(
            description=(
                "(Optional) Comma-separated list of space keys to filter results by. "
                "Overrides the environment variable CONFLUENCE_SPACES_FILTER if provided. "
                "Use empty string to disable filtering."
            ),
            default=None,
        ),
    ] = None,
) -> str:
    """Search Confluence content using simple terms or CQL.

    Args:
        ctx: The FastMCP context.
        query: Search query - can be simple text or a CQL query string.
        limit: Maximum number of results (1-50).
        spaces_filter: Comma-separated list of space keys to filter by.

    Returns:
        JSON string representing a list of simplified Confluence page objects.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    # Check if the query is a simple search term or already a CQL query
    if query and not any(
        x in query for x in ["=", "~", ">", "<", " AND ", " OR ", "currentUser()"]
    ):
        original_query = query
        try:
            query = f'siteSearch ~ "{original_query}"'
            logger.info(
                f"Converting simple search term to CQL using siteSearch: {query}"
            )
            pages = confluence_fetcher.search(
                query, limit=limit, spaces_filter=spaces_filter
            )
        except Exception as e:
            logger.warning(f"siteSearch failed ('{e}'), falling back to text search.")
            query = f'text ~ "{original_query}"'
            logger.info(f"Falling back to text search with CQL: {query}")
            pages = confluence_fetcher.search(
                query, limit=limit, spaces_filter=spaces_filter
            )
    else:
        pages = confluence_fetcher.search(
            query, limit=limit, spaces_filter=spaces_filter
        )
    search_results = [page.to_simplified_dict() for page in pages]
    return json.dumps(search_results, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page(
    ctx: Context,
    page_id: Annotated[
        str | None,
        Field(
            description=(
                "Confluence page ID (numeric ID, can be found in the page URL). "
                "For example, in the URL 'https://example.atlassian.net/wiki/spaces/TEAM/pages/123456789/Page+Title', "
                "the page ID is '123456789'. "
                "Provide this OR both 'title' and 'space_key'. If page_id is provided, title and space_key will be ignored."
            ),
            default=None,
        ),
    ] = None,
    title: Annotated[
        str | None,
        Field(
            description=(
                "The exact title of the Confluence page. Use this with 'space_key' if 'page_id' is not known."
            ),
            default=None,
        ),
    ] = None,
    space_key: Annotated[
        str | None,
        Field(
            description=(
                "The key of the Confluence space where the page resides (e.g., 'DEV', 'TEAM'). Required if using 'title'."
            ),
            default=None,
        ),
    ] = None,
    include_metadata: Annotated[
        bool,
        Field(
            description="Whether to include page metadata such as creation date, last update, version, and labels.",
            default=True,
        ),
    ] = True,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description=(
                "Whether to convert page to markdown (true) or keep it in raw HTML format (false). "
                "Raw HTML can reveal macros (like dates) not visible in markdown, but CAUTION: "
                "using HTML significantly increases token usage in AI responses."
            ),
            default=True,
        ),
    ] = True,
) -> str:
    """Get content of a specific Confluence page by its ID, or by its title and space key.

    Args:
        ctx: The FastMCP context.
        page_id: Confluence page ID. If provided, 'title' and 'space_key' are ignored.
        title: The exact title of the page. Must be used with 'space_key'.
        space_key: The key of the space. Must be used with 'title'.
        include_metadata: Whether to include page metadata.
        convert_to_markdown: Convert content to markdown (true) or keep raw HTML (false).

    Returns:
        JSON string representing the page content and/or metadata, or an error if not found or parameters are invalid.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    page_object = None

    if page_id:
        if title or space_key:
            logger.warning(
                "page_id was provided; title and space_key parameters will be ignored."
            )
        try:
            page_object = confluence_fetcher.get_page_content(
                page_id, convert_to_markdown=convert_to_markdown
            )
        except Exception as e:
            logger.error(f"Error fetching page by ID '{page_id}': {e}")
            return json.dumps(
                {"error": f"Failed to retrieve page by ID '{page_id}': {e}"},
                indent=2,
                ensure_ascii=False,
            )
    elif title and space_key:
        page_object = confluence_fetcher.get_page_by_title(
            space_key, title, convert_to_markdown=convert_to_markdown
        )
        if not page_object:
            return json.dumps(
                {
                    "error": f"Page with title '{title}' not found in space '{space_key}'."
                },
                indent=2,
                ensure_ascii=False,
            )
    else:
        raise ValueError(
            "Either 'page_id' OR both 'title' and 'space_key' must be provided."
        )

    if not page_object:
        return json.dumps(
            {"error": "Page not found with the provided identifiers."},
            indent=2,
            ensure_ascii=False,
        )

    if include_metadata:
        result = {"metadata": page_object.to_simplified_dict()}
    else:
        result = {"content": {"value": page_object.content}}

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_children(
    ctx: Context,
    parent_id: Annotated[
        str,
        Field(
            description="The ID of the parent page whose children you want to retrieve"
        ),
    ],
    expand: Annotated[
        str,
        Field(
            description="Fields to expand in the response (e.g., 'version', 'body.storage')",
            default="version",
        ),
    ] = "version",
    limit: Annotated[
        int,
        Field(
            description="Maximum number of child pages to return (1-50)",
            default=25,
            ge=1,
            le=50,
        ),
    ] = 25,
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include the page content in the response",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert page content to markdown (true) or keep it in raw HTML format (false). Only relevant if include_content is true.",
            default=True,
        ),
    ] = True,
    start: Annotated[
        int,
        Field(description="Starting index for pagination (0-based)", default=0, ge=0),
    ] = 0,
) -> str:
    """Get child pages of a specific Confluence page.

    Args:
        ctx: The FastMCP context.
        parent_id: The ID of the parent page.
        expand: Fields to expand.
        limit: Maximum number of child pages.
        include_content: Whether to include page content.
        convert_to_markdown: Convert content to markdown if include_content is true.
        start: Starting index for pagination.

    Returns:
        JSON string representing a list of child page objects.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    if include_content and "body" not in expand:
        expand = f"{expand},body.storage" if expand else "body.storage"

    try:
        pages = confluence_fetcher.get_page_children(
            page_id=parent_id,
            start=start,
            limit=limit,
            expand=expand,
            convert_to_markdown=convert_to_markdown,
        )
        child_pages = [page.to_simplified_dict() for page in pages]
        result = {
            "parent_id": parent_id,
            "count": len(child_pages),
            "limit_requested": limit,
            "start_requested": start,
            "results": child_pages,
        }
    except Exception as e:
        logger.error(
            f"Error getting/processing children for page ID {parent_id}: {e}",
            exc_info=True,
        )
        result = {"error": f"Failed to get child pages: {e}"}

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_comments(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(
            description=(
                "Confluence page ID (numeric ID, can be parsed from URL, "
                "e.g. from 'https://example.atlassian.net/wiki/spaces/TEAM/pages/123456789/Page+Title' "
                "-> '123456789')"
            )
        ),
    ],
) -> str:
    """Get comments for a specific Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: Confluence page ID.

    Returns:
        JSON string representing a list of comment objects.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    comments = confluence_fetcher.get_page_comments(page_id)
    formatted_comments = [comment.to_simplified_dict() for comment in comments]
    return json.dumps(formatted_comments, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_labels(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(
            description=(
                "Confluence page ID (numeric ID, can be parsed from URL, "
                "e.g. from 'https://example.atlassian.net/wiki/spaces/TEAM/pages/123456789/Page+Title' "
                "-> '123456789')"
            )
        ),
    ],
) -> str:
    """Get labels for a specific Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: Confluence page ID.

    Returns:
        JSON string representing a list of label objects.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    labels = confluence_fetcher.get_page_labels(page_id)
    formatted_labels = [label.to_simplified_dict() for label in labels]
    return json.dumps(formatted_labels, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "write"})
@check_write_access
async def add_label(
    ctx: Context,
    page_id: Annotated[str, Field(description="The ID of the page to update")],
    name: Annotated[str, Field(description="The name of the label")],
) -> str:
    """Add label to an existing Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to update.
        name: The name of the label.

    Returns:
        JSON string representing the updated list of label objects for the page.

    Raises:
        ValueError: If in read-only mode or Confluence client is unavailable.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    labels = confluence_fetcher.add_page_label(page_id, name)
    formatted_labels = [label.to_simplified_dict() for label in labels]
    return json.dumps(formatted_labels, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "write"})
@check_write_access
async def create_page(
    ctx: Context,
    space_key: Annotated[
        str,
        Field(
            description="The key of the space to create the page in (usually a short uppercase code like 'DEV', 'TEAM', or 'DOC')"
        ),
    ],
    title: Annotated[str, Field(description="The title of the page")],
    content: Annotated[
        str,
        Field(
            description="The content of the page. Format depends on content_format parameter. Can be Markdown (default), wiki markup, or storage format"
        ),
    ],
    parent_id: Annotated[
        str | None,
        Field(
            description="(Optional) parent page ID. If provided, this page will be created as a child of the specified page",
            default=None,
        ),
        BeforeValidator(lambda x: str(x) if x is not None else None),
    ] = None,
    content_format: Annotated[
        str,
        Field(
            description="(Optional) The format of the content parameter. Options: 'markdown' (default), 'wiki', or 'storage'. Wiki format uses Confluence wiki markup syntax",
            default="markdown",
        ),
    ] = "markdown",
    enable_heading_anchors: Annotated[
        bool,
        Field(
            description="(Optional) Whether to enable automatic heading anchor generation. Only applies when content_format is 'markdown'",
            default=False,
        ),
    ] = False,
) -> str:
    """Create a new Confluence page.

    Args:
        ctx: The FastMCP context.
        space_key: The key of the space.
        title: The title of the page.
        content: The content of the page (format depends on content_format).
        parent_id: Optional parent page ID.
        content_format: The format of the content ('markdown', 'wiki', or 'storage').
        enable_heading_anchors: Whether to enable heading anchors (markdown only).

    Returns:
        JSON string representing the created page object.

    Raises:
        ValueError: If in read-only mode, Confluence client is unavailable, or invalid content_format.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)

    # Validate content_format
    if content_format not in ["markdown", "wiki", "storage"]:
        raise ValueError(
            f"Invalid content_format: {content_format}. Must be 'markdown', 'wiki', or 'storage'"
        )

    # Determine parameters based on content format
    if content_format == "markdown":
        is_markdown = True
        content_representation = None  # Will be converted to storage
    else:
        is_markdown = False
        content_representation = content_format  # Pass 'wiki' or 'storage' directly

    page = confluence_fetcher.create_page(
        space_key=space_key,
        title=title,
        body=content,
        parent_id=parent_id,
        is_markdown=is_markdown,
        enable_heading_anchors=enable_heading_anchors
        if content_format == "markdown"
        else False,
        content_representation=content_representation,
    )
    result = page.to_simplified_dict()
    return json.dumps(
        {"message": "Page created successfully", "page": result},
        indent=2,
        ensure_ascii=False,
    )


@confluence_mcp.tool(tags={"confluence", "write"})
@check_write_access
async def update_page(
    ctx: Context,
    page_id: Annotated[str, Field(description="The ID of the page to update")],
    title: Annotated[str, Field(description="The new title of the page")],
    content: Annotated[
        str,
        Field(
            description="The new content of the page. Format depends on content_format parameter"
        ),
    ],
    is_minor_edit: Annotated[
        bool, Field(description="Whether this is a minor edit", default=False)
    ] = False,
    version_comment: Annotated[
        str | None, Field(description="Optional comment for this version", default=None)
    ] = None,
    parent_id: Annotated[
        str | None,
        Field(description="Optional the new parent page ID", default=None),
        BeforeValidator(lambda x: str(x) if x is not None else None),
    ] = None,
    content_format: Annotated[
        str,
        Field(
            description="(Optional) The format of the content parameter. Options: 'markdown' (default), 'wiki', or 'storage'. Wiki format uses Confluence wiki markup syntax",
            default="markdown",
        ),
    ] = "markdown",
    enable_heading_anchors: Annotated[
        bool,
        Field(
            description="(Optional) Whether to enable automatic heading anchor generation. Only applies when content_format is 'markdown'",
            default=False,
        ),
    ] = False,
) -> str:
    """Update an existing Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to update.
        title: The new title of the page.
        content: The new content of the page (format depends on content_format).
        is_minor_edit: Whether this is a minor edit.
        version_comment: Optional comment for this version.
        parent_id: Optional new parent page ID.
        content_format: The format of the content ('markdown', 'wiki', or 'storage').
        enable_heading_anchors: Whether to enable heading anchors (markdown only).

    Returns:
        JSON string representing the updated page object.

    Raises:
        ValueError: If Confluence client is not configured, available, or invalid content_format.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)

    # Validate content_format
    if content_format not in ["markdown", "wiki", "storage"]:
        raise ValueError(
            f"Invalid content_format: {content_format}. Must be 'markdown', 'wiki', or 'storage'"
        )

    # Determine parameters based on content format
    if content_format == "markdown":
        is_markdown = True
        content_representation = None  # Will be converted to storage
    else:
        is_markdown = False
        content_representation = content_format  # Pass 'wiki' or 'storage' directly

    updated_page = confluence_fetcher.update_page(
        page_id=page_id,
        title=title,
        body=content,
        is_minor_edit=is_minor_edit,
        version_comment=version_comment,
        is_markdown=is_markdown,
        parent_id=parent_id,
        enable_heading_anchors=enable_heading_anchors
        if content_format == "markdown"
        else False,
        content_representation=content_representation,
    )
    page_data = updated_page.to_simplified_dict()
    return json.dumps(
        {"message": "Page updated successfully", "page": page_data},
        indent=2,
        ensure_ascii=False,
    )


@confluence_mcp.tool(tags={"confluence", "write"})
@check_write_access
async def delete_page(
    ctx: Context,
    page_id: Annotated[str, Field(description="The ID of the page to delete")],
) -> str:
    """Delete an existing Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to delete.

    Returns:
        JSON string indicating success or failure.

    Raises:
        ValueError: If Confluence client is not configured or available.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    try:
        result = confluence_fetcher.delete_page(page_id=page_id)
        if result:
            response = {
                "success": True,
                "message": f"Page {page_id} deleted successfully",
            }
        else:
            response = {
                "success": False,
                "message": f"Unable to delete page {page_id}. API request completed but deletion unsuccessful.",
            }
    except Exception as e:
        logger.error(f"Error deleting Confluence page {page_id}: {str(e)}")
        response = {
            "success": False,
            "message": f"Error deleting page {page_id}",
            "error": str(e),
        }

    return json.dumps(response, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "write"})
@check_write_access
async def add_comment(
    ctx: Context,
    page_id: Annotated[
        str, Field(description="The ID of the page to add a comment to")
    ],
    content: Annotated[
        str, Field(description="The comment content in Markdown format")
    ],
) -> str:
    """Add a comment to a Confluence page.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to add a comment to.
        content: The comment content in Markdown format.

    Returns:
        JSON string representing the created comment.

    Raises:
        ValueError: If in read-only mode or Confluence client is unavailable.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    try:
        comment = confluence_fetcher.add_comment(page_id=page_id, content=content)
        if comment:
            comment_data = comment.to_simplified_dict()
            response = {
                "success": True,
                "message": "Comment added successfully",
                "comment": comment_data,
            }
        else:
            response = {
                "success": False,
                "message": f"Unable to add comment to page {page_id}. API request completed but comment creation unsuccessful.",
            }
    except Exception as e:
        logger.error(f"Error adding comment to Confluence page {page_id}: {str(e)}")
        response = {
            "success": False,
            "message": f"Error adding comment to page {page_id}",
            "error": str(e),
        }

    return json.dumps(response, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def search_user(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            description=(
                "Search query - a CQL query string for user search. "
                "Examples of CQL:\n"
                "- Basic user lookup by full name: 'user.fullname ~ \"First Last\"'\n"
                'Note: Special identifiers need proper quoting in CQL: personal space keys (e.g., "~username"), '
                "reserved words, numeric IDs, and identifiers with special characters."
            )
        ),
    ],
    limit: Annotated[
        int,
        Field(
            description="Maximum number of results (1-50)",
            default=10,
            ge=1,
            le=50,
        ),
    ] = 10,
) -> str:
    """Search Confluence users using CQL.

    Args:
        ctx: The FastMCP context.
        query: Search query - a CQL query string for user search.
        limit: Maximum number of results (1-50).

    Returns:
        JSON string representing a list of simplified Confluence user search result objects.
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)

    # If the query doesn't look like CQL, wrap it as a user fullname search
    if query and not any(
        x in query for x in ["=", "~", ">", "<", " AND ", " OR ", "user."]
    ):
        # Simple search term - search by fullname
        query = f'user.fullname ~ "{query}"'
        logger.info(f"Converting simple search term to user CQL: {query}")

    try:
        user_results = confluence_fetcher.search_user(query, limit=limit)
        search_results = [user.to_simplified_dict() for user in user_results]
        return json.dumps(search_results, indent=2, ensure_ascii=False)
    except MCPAtlassianAuthenticationError as e:
        logger.error(f"Authentication error during user search: {e}", exc_info=False)
        return json.dumps(
            {
                "error": "Authentication failed. Please check your credentials.",
                "details": str(e),
            },
            indent=2,
            ensure_ascii=False,
        )


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_space_root_pages(
    ctx: Context,
    space_key: Annotated[
        str,
        Field(
            description="The key of the space to get root pages from (e.g., 'DEV', 'TEAM')"
        ),
    ],
    start: Annotated[
        int,
        Field(
            description="Starting index for pagination (0-based)",
            default=0,
            ge=0,
        ),
    ] = 0,
    limit: Annotated[
        int,
        Field(
            description="Maximum number of pages to return (1-200)",
            default=50,
            ge=1,
            le=200,
        ),
    ] = 50,
    expand: Annotated[
        str,
        Field(
            description="Fields to expand in the response (e.g., 'version', 'body.storage')",
            default="version",
        ),
    ] = "version",
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the response",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert page content to markdown (true) or keep it in raw HTML format (false)",
            default=True,
        ),
    ] = True,
) -> str:
    """Get top-level (root) pages in a Confluence space.

    Root pages are pages that have no parent page - they are the entry points
    for navigation in a space. These pages serve as the starting points for
    exploring the content hierarchy within the space.

    Args:
        ctx: The FastMCP context.
        space_key: The key of the space to get root pages from.
        start: Starting index for pagination.
        limit: Maximum number of pages to return.
        expand: Fields to expand in the response.
        include_content: Whether to include page content.
        convert_to_markdown: Convert content to markdown if include_content is true.

    Returns:
        JSON string representing a list of root page objects.

    Example:
        # Get root pages from a space
        await confluence_get_space_root_pages(ctx, "DEV")

        # Get root pages with content
        await confluence_get_space_root_pages(ctx, "TEAM", include_content=True)

        # Get root pages with pagination
        await confluence_get_space_root_pages(ctx, "DOC", start=10, limit=25)
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)

    # Adjust expand parameter to include content if requested
    if include_content and "body" not in expand:
        expand = f"{expand},body.storage" if expand else "body.storage"

    try:
        pages = confluence_fetcher.get_space_root_pages(
            space_key=space_key,
            start=start,
            limit=limit,
            expand=expand,
            convert_to_markdown=convert_to_markdown,
        )
        root_pages = [page.to_simplified_dict() for page in pages]
        result = {
            "space_key": space_key,
            "count": len(root_pages),
            "limit_requested": limit,
            "start_requested": start,
            "results": root_pages,
        }
    except Exception as e:
        logger.error(
            f"Error getting root pages for space {space_key}: {e}",
            exc_info=True,
        )
        result = {
            "space_key": space_key,
            "count": 0,
            "limit_requested": limit,
            "start_requested": start,
            "results": [],
            "error": f"Failed to get root pages: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_siblings(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(description="The ID of the page to find siblings for"),
    ],
    include_self: Annotated[
        bool,
        Field(
            description="Whether to include the page itself in results",
            default=False,
        ),
    ] = False,
    start: Annotated[
        int,
        Field(
            description="Starting index for pagination (0-based)",
            default=0,
            ge=0,
        ),
    ] = 0,
    limit: Annotated[
        int,
        Field(
            description="Maximum number of pages to return (1-50)",
            default=50,
            ge=1,
            le=200,
        ),
    ] = 50,
    expand: Annotated[
        str,
        Field(
            description="Fields to expand in the response (e.g., 'version', 'body.storage')",
            default="version",
        ),
    ] = "version",
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the response",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert page content to markdown (true) or keep it in raw HTML format (false)",
            default=True,
        ),
    ] = True,
) -> str:
    """Get sibling pages (pages with the same parent) of a specific Confluence page.

    Sibling pages are pages that share the same parent page. For root pages
    (pages with no parent), siblings are other root pages in the same space.
    This tool is useful for horizontal navigation within a page hierarchy.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to find siblings for.
        include_self: Whether to include the page itself in results.
        start: Starting index for pagination.
        limit: Maximum number of pages to return.
        expand: Fields to expand in the response.
        include_content: Whether to include page content.
        convert_to_markdown: Convert content to markdown if include_content is true.

    Returns:
        JSON string representing a list of sibling page objects.

    Example:
        # Get siblings of a page
        await get_page_siblings(ctx, "123456")

        # Get siblings including the page itself
        await get_page_siblings(ctx, "123456", include_self=True)

        # Get siblings with content
        await get_page_siblings(ctx, "123456", include_content=True)
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)

    # Adjust expand parameter to include content if requested
    if include_content and "body" not in expand:
        expand = f"{expand},body.storage" if expand else "body.storage"

    try:
        pages = confluence_fetcher.get_page_siblings(
            page_id=page_id,
            include_self=include_self,
            start=start,
            limit=limit,
            expand=expand,
            convert_to_markdown=convert_to_markdown,
        )
        sibling_pages = [page.to_simplified_dict() for page in pages]
        result = {
            "page_id": page_id,
            "include_self": include_self,
            "count": len(sibling_pages),
            "limit_requested": limit,
            "start_requested": start,
            "results": sibling_pages,
        }
    except Exception as e:
        logger.error(
            f"Error getting siblings for page {page_id}: {e}",
            exc_info=True,
        )
        result = {
            "page_id": page_id,
            "include_self": include_self,
            "count": 0,
            "limit_requested": limit,
            "start_requested": start,
            "results": [],
            "error": f"Failed to get page siblings: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_breadcrumbs(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(description="The ID of the page to get breadcrumbs for"),
    ],
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the results",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert content to markdown format if include_content is true",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Get breadcrumb trail for a specific Confluence page.

    Returns the full navigation path from the space root to the target page,
    providing context for the page's location within the hierarchy. This is
    useful for building navigation breadcrumbs in user interfaces.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to get breadcrumbs for.
        include_content: Whether to include page content in the results (default: False).
        convert_to_markdown: Whether to convert content to markdown format if
                           include_content is true (default: True).

    Returns:
        JSON string representing the breadcrumb trail with metadata and page list.

    Example:
        >>> result = get_page_breadcrumbs(ctx, "123456789")
        >>> # Returns breadcrumb trail from root to current page
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    logger.info(f"Getting breadcrumb trail for page: {page_id}")

    try:
        pages = confluence_fetcher.get_page_breadcrumbs(
            page_id=page_id, include_content=include_content
        )

        # Process pages for content conversion if requested
        if include_content and convert_to_markdown:
            from mcp_atlassian.preprocessing.confluence import (
                preprocess_confluence_page,
            )

            pages = [
                preprocess_confluence_page(page, convert_to_markdown=True)
                for page in pages
            ]

        breadcrumb_pages = [page.to_simplified_dict() for page in pages]
        result = {
            "page_id": page_id,
            "breadcrumb_count": len(breadcrumb_pages),
            "include_content": include_content,
            "convert_to_markdown": convert_to_markdown,
            "breadcrumbs": breadcrumb_pages,
        }
    except Exception as e:
        logger.error(
            f"Error getting breadcrumb trail for page {page_id}: {e}",
            exc_info=True,
        )
        result = {
            "page_id": page_id,
            "breadcrumb_count": 0,
            "include_content": include_content,
            "convert_to_markdown": convert_to_markdown,
            "breadcrumbs": [],
            "error": f"Failed to get page breadcrumbs: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_descendants(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(description="The ID of the page to get descendants for"),
    ],
    max_depth: Annotated[
        int | None,
        Field(
            description="Maximum depth to traverse (None for unlimited). Depth 0 = no descendants, depth 1 = direct children only, etc.",
            default=None,
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            description="Maximum total number of descendants to return (1-500)",
            default=200,
            ge=1,
            le=500,
        ),
    ] = 200,
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the results",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert content to markdown format if include_content is true",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Get all descendant pages (children, grandchildren, etc.) of a specific Confluence page.

    This tool recursively traverses the page tree starting from the specified page,
    collecting all descendant pages in a flat list. It provides depth limiting to
    prevent infinite recursion and supports content inclusion for detailed results.

    Args:
        ctx: The FastMCP context.
        page_id: The ID of the page to get descendants for.
        max_depth: Maximum depth to traverse (None for unlimited).
        limit: Maximum total number of descendants to return.
        include_content: Whether to include page content in the results.
        convert_to_markdown: Whether to convert content to markdown format if
                           include_content is true.

    Returns:
        JSON string representing the descendant tree with metadata and page list.

    Example:
        # Get all descendants (unlimited depth)
        await get_page_descendants(ctx, "123456")

        # Get only direct children (depth 1)
        await get_page_descendants(ctx, "123456", max_depth=1)

        # Get descendants with content included
        await get_page_descendants(ctx, "123456", include_content=True)

        # Get limited descendants with depth control
        await get_page_descendants(ctx, "123456", max_depth=3, limit=50)
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    logger.info(f"Getting descendants for page: {page_id}")

    try:
        pages = confluence_fetcher.get_page_descendants(
            page_id=page_id,
            max_depth=max_depth,
            limit=limit,
            include_content=include_content,
        )

        descendant_pages = [page.to_simplified_dict() for page in pages]
        result = {
            "page_id": page_id,
            "max_depth": max_depth,
            "limit": limit,
            "count": len(descendant_pages),
            "include_content": include_content,
            "descendants": descendant_pages,
        }
    except Exception as e:
        logger.error(
            f"Error getting descendants for page {page_id}: {e}",
            exc_info=True,
        )
        result = {
            "page_id": page_id,
            "max_depth": max_depth,
            "limit": limit,
            "count": 0,
            "include_content": include_content,
            "descendants": [],
            "error": f"Failed to get page descendants: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_by_path(
    ctx: Context,
    space_key: Annotated[
        str,
        Field(
            description="The key of the space containing the page hierarchy (e.g., 'DEV', 'TEAM')"
        ),
    ],
    path: Annotated[
        str,
        Field(
            description=(
                "Hierarchical path to the page using page titles separated by '/' or '\\'. "
                "Examples: 'Documentation/API/REST', 'Meetings/Weekly/2024', 'Project\\Reports\\Monthly'. "
                "Path segments are matched case-insensitively and whitespace is trimmed."
            )
        ),
    ],
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the response",
            default=False,
        ),
    ] = False,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert page content to markdown (true) or keep it in raw HTML format (false). Only relevant if include_content is true.",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Get a Confluence page by navigating through a hierarchical path.

    This tool finds a page by traversing the page hierarchy using a path format like
    "Parent/Child/Grandchild". It starts from the space root pages and follows the
    path segments to locate the target page. This is useful for finding pages when
    you know their hierarchical location but not their exact ID.

    Args:
        ctx: The FastMCP context.
        space_key: The key of the space containing the page hierarchy.
        path: Hierarchical path to the page using page titles.
        include_content: Whether to include page content in the response.
        convert_to_markdown: Whether to convert content to markdown format if
                           include_content is true.

    Returns:
        JSON string representing the found page object, or an error if not found.

    Example:
        # Find a page using hierarchical path
        await get_page_by_path(ctx, "DEV", "Documentation/API/REST")

        # Find page with content included
        await get_page_by_path(ctx, "PROJ", "Meetings/Weekly", include_content=True)

        # Handle different path separators
        await get_page_by_path(ctx, "TEAM", "Project\\Reports\\Monthly")
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    logger.info(f"Finding page by path: {path} in space: {space_key}")

    try:
        page = confluence_fetcher.get_page_by_path(
            space_key=space_key,
            path=path,
            include_content=include_content,
            convert_to_markdown=convert_to_markdown,
        )

        if page:
            # Page found successfully
            page_data = page.to_simplified_dict()
            result = {
                "space_key": space_key,
                "path": path,
                "include_content": include_content,
                "convert_to_markdown": convert_to_markdown,
                "found": True,
                "page": page_data,
            }
        else:
            # Page not found
            result = {
                "space_key": space_key,
                "path": path,
                "include_content": include_content,
                "convert_to_markdown": convert_to_markdown,
                "found": False,
                "error": f"Page not found at path '{path}' in space '{space_key}'",
            }

    except Exception as e:
        logger.error(
            f"Error finding page by path '{path}' in space {space_key}: {e}",
            exc_info=True,
        )
        result = {
            "space_key": space_key,
            "path": path,
            "include_content": include_content,
            "convert_to_markdown": convert_to_markdown,
            "found": False,
            "error": f"Failed to find page by path: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)


@confluence_mcp.tool(tags={"confluence", "read"})
async def get_space_pages_flat(
    ctx: Context,
    space_key: Annotated[
        str,
        Field(
            description="The key of the space to get all pages from (e.g., 'DEV', 'TEAM')"
        ),
    ],
    include_content: Annotated[
        bool,
        Field(
            description="Whether to include page content in the response",
            default=False,
        ),
    ] = False,
    limit: Annotated[
        int,
        Field(
            description="Safety limit for very large spaces (1-5000)",
            default=1000,
            ge=1,
            le=5000,
        ),
    ] = 1000,
    convert_to_markdown: Annotated[
        bool,
        Field(
            description="Whether to convert page content to markdown (true) or keep it in raw HTML format (false). Only relevant if include_content is true.",
            default=True,
        ),
    ] = True,
) -> str:
    """
    Get all pages from a Confluence space without pagination constraints.

    This tool retrieves ALL pages from a space efficiently by using automatic
    pagination to collect pages in batches until all pages are retrieved or the
    limit is reached. This provides a complete overview of a space's content
    without requiring manual pagination handling.

    Args:
        ctx: The FastMCP context.
        space_key: The key of the space to get all pages from.
        include_content: Whether to include page content in the response.
        limit: Safety limit for very large spaces to prevent excessive memory usage.
        convert_to_markdown: Whether to convert content to markdown format if
                           include_content is true.

    Returns:
        JSON string representing all pages in the space with metadata.

    Example:
        # Get all pages in a space (metadata only)
        await get_space_pages_flat(ctx, "DEV")

        # Get all pages with content included
        await get_space_pages_flat(ctx, "TEAM", include_content=True)

        # Get all pages with custom limit
        await get_space_pages_flat(ctx, "PROJ", limit=500)

        # Get all pages with raw HTML content
        await get_space_pages_flat(ctx, "DOC", include_content=True, convert_to_markdown=False)
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    logger.info(f"Getting all pages from space: {space_key}")

    try:
        pages = confluence_fetcher.get_space_pages_flat(
            space_key=space_key,
            include_content=include_content,
            limit=limit,
            convert_to_markdown=convert_to_markdown,
        )

        pages_data = [page.to_simplified_dict() for page in pages]
        result = {
            "space_key": space_key,
            "total_pages": len(pages_data),
            "limit_requested": limit,
            "include_content": include_content,
            "convert_to_markdown": convert_to_markdown,
            "pages": pages_data,
        }

        # Add summary information for large result sets
        if len(pages_data) > 100:
            logger.info(
                f"Large result set: {len(pages_data)} pages from space '{space_key}'"
            )
            result["summary"] = {
                "total_pages": len(pages_data),
                "has_content": sum(1 for page in pages_data if page.get("body")),
                "sample_titles": [
                    page.get("title", "Unknown") for page in pages_data[:5]
                ],
            }

    except Exception as e:
        logger.error(
            f"Error getting all pages from space {space_key}: {e}",
            exc_info=True,
        )
        result = {
            "space_key": space_key,
            "total_pages": 0,
            "limit_requested": limit,
            "include_content": include_content,
            "convert_to_markdown": convert_to_markdown,
            "pages": [],
            "error": f"Failed to get pages from space: {e}",
        }

    return json.dumps(result, indent=2, ensure_ascii=False)
