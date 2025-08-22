"""Unit tests for the Confluence FastMCP server."""

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client import FastMCPTransport
from starlette.requests import Request

from src.mcp_atlassian.confluence import ConfluenceFetcher
from src.mcp_atlassian.confluence.config import ConfluenceConfig
from src.mcp_atlassian.models.confluence.page import ConfluencePage
from src.mcp_atlassian.servers.context import MainAppContext
from src.mcp_atlassian.servers.main import AtlassianMCP
from src.mcp_atlassian.utils.oauth import OAuthConfig

logger = logging.getLogger(__name__)


@pytest.fixture
def mock_confluence_fetcher():
    """Create a mocked ConfluenceFetcher instance for testing."""
    mock_fetcher = MagicMock(spec=ConfluenceFetcher)

    # Mock page for various methods
    mock_page = MagicMock(spec=ConfluencePage)
    mock_page.to_simplified_dict.return_value = {
        "id": "123456",
        "title": "Test Page Mock Title",
        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/123456/Test+Page",
        "content": {
            "value": "This is a test page content in Markdown",
            "format": "markdown",
        },
    }
    mock_page.content = "This is a test page content in Markdown"

    # Mock root page for get_space_root_pages
    mock_root_page = MagicMock(spec=ConfluencePage)
    mock_root_page.to_simplified_dict.return_value = {
        "id": "root123",
        "title": "Welcome to Test Space",
        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/root123/Welcome+to+Test+Space",
        "content": {
            "value": "# Welcome\nThis is a root page with no parent.",
            "format": "markdown",
        },
        "space": {"key": "TEST", "name": "Test Space"},
        "ancestors": [],  # No ancestors = root page
    }
    mock_root_page.content = "# Welcome\nThis is a root page with no parent."

    # Set up mock responses for each method
    mock_fetcher.search.return_value = [mock_page]
    mock_fetcher.get_page_content.return_value = mock_page
    mock_fetcher.get_page_children.return_value = [mock_page]
    mock_fetcher.get_page_descendants.return_value = [mock_page]
    mock_fetcher.get_page_siblings.return_value = [mock_page]
    mock_fetcher.get_space_root_pages.return_value = [mock_root_page]
    mock_fetcher.get_page_breadcrumbs.return_value = [mock_root_page, mock_page]
    mock_fetcher.create_page.return_value = mock_page
    mock_fetcher.update_page.return_value = mock_page
    mock_fetcher.delete_page.return_value = True

    # Mock get_space_pages_flat method
    mock_flat_pages = []
    for i in range(5):  # Create 5 mock pages for flat collection
        mock_flat_page = MagicMock(spec=ConfluencePage)
        mock_flat_page.to_simplified_dict.return_value = {
            "id": f"flat{i}",
            "title": f"Flat Page {i}",
            "url": f"https://example.atlassian.net/wiki/spaces/TEST/pages/flat{i}/Flat+Page+{i}",
            "content": {
                "value": f"This is flat page {i} content in Markdown",
                "format": "markdown",
            },
            "space": {"key": "TEST", "name": "Test Space"},
        }
        mock_flat_page.content = f"This is flat page {i} content in Markdown"
        mock_flat_pages.append(mock_flat_page)
    mock_fetcher.get_space_pages_flat.return_value = mock_flat_pages

    # Mock get_page_by_path method
    mock_path_page = MagicMock(spec=ConfluencePage)
    mock_path_page.to_simplified_dict.return_value = {
        "id": "path123",
        "title": "Documentation Guidelines",
        "url": "https://example.atlassian.net/wiki/spaces/TEST/pages/path123/Documentation+Guidelines",
        "content": {
            "value": "# Documentation Guidelines\nThis page contains our documentation standards.",
            "format": "markdown",
        },
        "space": {"key": "TEST", "name": "Test Space"},
    }
    mock_path_page.content = (
        "# Documentation Guidelines\nThis page contains our documentation standards."
    )
    mock_fetcher.get_page_by_path.return_value = mock_path_page

    # Mock comment
    mock_comment = MagicMock()
    mock_comment.to_simplified_dict.return_value = {
        "id": "789",
        "author": "Test User",
        "created": "2023-08-01T12:00:00.000Z",
        "body": "This is a test comment",
    }
    mock_fetcher.get_page_comments.return_value = [mock_comment]

    # Mock label
    mock_label = MagicMock()
    mock_label.to_simplified_dict.return_value = {"id": "lbl1", "name": "test-label"}
    mock_fetcher.get_page_labels.return_value = [mock_label]
    mock_fetcher.add_page_label.return_value = [mock_label]

    # Mock add_comment method
    mock_comment = MagicMock()
    mock_comment.to_simplified_dict.return_value = {
        "id": "987",
        "author": "Test User",
        "created": "2023-08-01T13:00:00.000Z",
        "body": "This is a test comment added via API",
    }
    mock_fetcher.add_comment.return_value = mock_comment

    # Mock search_user method
    mock_user_search_result = MagicMock()
    mock_user_search_result.to_simplified_dict.return_value = {
        "entity_type": "user",
        "title": "First Last",
        "score": 0.0,
        "user": {
            "account_id": "a031248587011jasoidf9832jd8j1",
            "display_name": "First Last",
            "email": "first.last@foo.com",
            "profile_picture": "/wiki/aa-avatar/a031248587011jasoidf9832jd8j1",
            "is_active": True,
        },
        "url": "/people/a031248587011jasoidf9832jd8j1",
        "last_modified": "2025-06-02T13:35:59.680Z",
        "excerpt": "",
    }
    mock_fetcher.search_user.return_value = [mock_user_search_result]

    return mock_fetcher


@pytest.fixture
def mock_base_confluence_config():
    """Create a mock base ConfluenceConfig for MainAppContext using OAuth for multi-user scenario."""
    mock_oauth_config = OAuthConfig(
        client_id="server_client_id",
        client_secret="server_client_secret",
        redirect_uri="http://localhost",
        scope="read:confluence",
        cloud_id="mock_cloud_id",
    )
    return ConfluenceConfig(
        url="https://mock.atlassian.net/wiki",
        auth_type="oauth",
        oauth_config=mock_oauth_config,
    )


@pytest.fixture
def mock_private_server_bearer_config():
    """Create a mock ConfluenceConfig for a private server with generic bearer token."""
    return ConfluenceConfig(
        url="http://private-confluence.local",
        auth_type="bearer_token",
        bearer_token="mock-private-bearer-token",
        ssl_verify=False,  # Often private servers use self-signed certs
    )


@pytest.fixture
def test_confluence_mcp(mock_confluence_fetcher, mock_base_confluence_config):
    """Create a test FastMCP instance with standard configuration."""

    # Import and register tool functions (as they are in confluence.py)
    from src.mcp_atlassian.servers.confluence import (
        add_comment,
        add_label,
        create_page,
        delete_page,
        get_comments,
        get_labels,
        get_page,
        get_page_breadcrumbs,
        get_page_by_path,
        get_page_children,
        get_page_descendants,
        get_page_siblings,
        get_space_pages_flat,
        get_space_root_pages,
        search,
        search_user,
        update_page,
    )

    @asynccontextmanager
    async def test_lifespan(app: FastMCP) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(
                full_confluence_config=mock_base_confluence_config, read_only=False
            )
        finally:
            pass

    test_mcp = AtlassianMCP(
        "TestConfluence",
        description="Test Confluence MCP Server",
        lifespan=test_lifespan,
    )

    # Create and configure the sub-MCP for Confluence tools
    confluence_sub_mcp = FastMCP(name="TestConfluenceSubMCP")
    confluence_sub_mcp.tool()(search)
    confluence_sub_mcp.tool()(get_page)
    confluence_sub_mcp.tool()(get_page_breadcrumbs)
    confluence_sub_mcp.tool()(get_page_by_path)
    confluence_sub_mcp.tool()(get_page_children)
    confluence_sub_mcp.tool()(get_page_descendants)
    confluence_sub_mcp.tool()(get_page_siblings)
    confluence_sub_mcp.tool()(get_space_pages_flat)
    confluence_sub_mcp.tool()(get_space_root_pages)
    confluence_sub_mcp.tool()(get_comments)
    confluence_sub_mcp.tool()(add_comment)
    confluence_sub_mcp.tool()(get_labels)
    confluence_sub_mcp.tool()(add_label)
    confluence_sub_mcp.tool()(create_page)
    confluence_sub_mcp.tool()(update_page)
    confluence_sub_mcp.tool()(delete_page)
    confluence_sub_mcp.tool()(search_user)

    test_mcp.mount("confluence", confluence_sub_mcp)

    return test_mcp


@pytest.fixture
def no_fetcher_test_confluence_mcp(mock_base_confluence_config):
    """Create a test FastMCP instance that simulates missing Confluence fetcher."""

    # Import and register tool functions (as they are in confluence.py)
    from src.mcp_atlassian.servers.confluence import (
        add_comment,
        add_label,
        create_page,
        delete_page,
        get_comments,
        get_labels,
        get_page,
        get_page_breadcrumbs,
        get_page_by_path,
        get_page_children,
        get_page_descendants,
        get_page_siblings,
        get_space_pages_flat,
        get_space_root_pages,
        search,
        search_user,
        update_page,
    )

    @asynccontextmanager
    async def no_fetcher_test_lifespan(
        app: FastMCP,
    ) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(
                full_confluence_config=mock_base_confluence_config, read_only=False
            )
        finally:
            pass

    test_mcp = AtlassianMCP(
        "NoFetcherTestConfluence",
        description="No Fetcher Test Confluence MCP Server",
        lifespan=no_fetcher_test_lifespan,
    )

    # Create and configure the sub-MCP for Confluence tools
    confluence_sub_mcp = FastMCP(name="NoFetcherTestConfluenceSubMCP")
    confluence_sub_mcp.tool()(search)
    confluence_sub_mcp.tool()(get_page)
    confluence_sub_mcp.tool()(get_page_breadcrumbs)
    confluence_sub_mcp.tool()(get_page_by_path)
    confluence_sub_mcp.tool()(get_page_children)
    confluence_sub_mcp.tool()(get_page_descendants)
    confluence_sub_mcp.tool()(get_page_siblings)
    confluence_sub_mcp.tool()(get_space_pages_flat)
    confluence_sub_mcp.tool()(get_space_root_pages)
    confluence_sub_mcp.tool()(get_comments)
    confluence_sub_mcp.tool()(add_comment)
    confluence_sub_mcp.tool()(get_labels)
    confluence_sub_mcp.tool()(add_label)
    confluence_sub_mcp.tool()(create_page)
    confluence_sub_mcp.tool()(update_page)
    confluence_sub_mcp.tool()(delete_page)
    confluence_sub_mcp.tool()(search_user)

    test_mcp.mount("confluence", confluence_sub_mcp)

    return test_mcp


@pytest.fixture
def mock_request():
    """Provides a mock Starlette Request object with a state."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    return request


@pytest.fixture
async def client(test_confluence_mcp, mock_confluence_fetcher):
    """Create a FastMCP client with mocked Confluence fetcher and request state."""
    with (
        patch(
            "src.mcp_atlassian.servers.confluence.get_confluence_fetcher",
            AsyncMock(return_value=mock_confluence_fetcher),
        ),
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            MagicMock(spec=Request, state=MagicMock()),
        ),
    ):
        client_instance = Client(transport=FastMCPTransport(test_confluence_mcp))
        async with client_instance as connected_client:
            yield connected_client


@pytest.fixture
async def private_server_bearer_client(
    mock_confluence_fetcher, mock_private_server_bearer_config
):
    """Create a FastMCP client for testing with a mocked private Confluence server and generic bearer token."""

    # Import and register tool functions (as they are in confluence.py)
    from src.mcp_atlassian.servers.confluence import (
        add_comment,
        add_label,
        create_page,
        delete_page,
        get_comments,
        get_labels,
        get_page,
        get_page_breadcrumbs,
        get_page_by_path,
        get_page_children,
        get_page_descendants,
        get_page_siblings,
        get_space_pages_flat,
        get_space_root_pages,
        search,
        search_user,
        update_page,
    )

    @asynccontextmanager
    async def private_bearer_test_lifespan(
        app: FastMCP,
    ) -> AsyncGenerator[MainAppContext, None]:
        try:
            yield MainAppContext(
                full_confluence_config=mock_private_server_bearer_config,
                read_only=False,
            )
        finally:
            pass

    test_mcp = AtlassianMCP(
        "PrivateBearerTestConfluence",
        description="Private Bearer Test Confluence MCP Server",
        lifespan=private_bearer_test_lifespan,
    )

    # Create and configure the sub-MCP for Confluence tools
    confluence_sub_mcp = FastMCP(name="PrivateBearerTestConfluenceSubMCP")
    confluence_sub_mcp.tool()(search)
    confluence_sub_mcp.tool()(get_page)
    confluence_sub_mcp.tool()(get_page_breadcrumbs)
    confluence_sub_mcp.tool()(get_page_by_path)
    confluence_sub_mcp.tool()(get_page_children)
    confluence_sub_mcp.tool()(get_page_descendants)
    confluence_sub_mcp.tool()(get_page_siblings)
    confluence_sub_mcp.tool()(get_space_pages_flat)
    confluence_sub_mcp.tool()(get_space_root_pages)
    confluence_sub_mcp.tool()(get_comments)
    confluence_sub_mcp.tool()(add_comment)
    confluence_sub_mcp.tool()(get_labels)
    confluence_sub_mcp.tool()(add_label)
    confluence_sub_mcp.tool()(create_page)
    confluence_sub_mcp.tool()(update_page)
    confluence_sub_mcp.tool()(delete_page)
    confluence_sub_mcp.tool()(search_user)

    test_mcp.mount("confluence", confluence_sub_mcp)

    with (
        patch(
            "src.mcp_atlassian.servers.confluence.get_confluence_fetcher",
            AsyncMock(return_value=mock_confluence_fetcher),
        ),
        patch(
            "src.mcp_atlassian.servers.dependencies.get_http_request",
            # Mock the request to have the bearer token in its state
            MagicMock(
                spec=Request,
                state=MagicMock(
                    user_atlassian_token=mock_private_server_bearer_config.bearer_token,
                    user_atlassian_auth_type="bearer_token",
                    user_atlassian_cloud_id=None,
                ),
            ),
        ),
    ):
        client_instance = Client(transport=FastMCPTransport(test_mcp))
        async with client_instance as connected_client:
            yield connected_client


@pytest.mark.anyio
async def test_search_with_private_bearer_token(
    private_server_bearer_client, mock_confluence_fetcher
):
    """Test the search tool with a user-provided generic bearer token."""
    response = await private_server_bearer_client.call_tool(
        "confluence_search", {"query": "test private search"}
    )

    mock_confluence_fetcher.search.assert_called_once()
    args, kwargs = mock_confluence_fetcher.search.call_args
    assert 'siteSearch ~ "test private search"' in args[0]
    assert kwargs.get("limit") == 10
    assert kwargs.get("spaces_filter") is None

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert len(result_data) > 0
    assert result_data[0]["title"] == "Test Page Mock Title"


@pytest.fixture
async def no_fetcher_client_fixture(no_fetcher_test_confluence_mcp, mock_request):
    """Create a client that simulates missing Confluence fetcher configuration."""
    client_for_no_fetcher_test = Client(
        transport=FastMCPTransport(no_fetcher_test_confluence_mcp)
    )
    async with client_for_no_fetcher_test as connected_client_for_no_fetcher:
        yield connected_client_for_no_fetcher


@pytest.mark.anyio
async def test_search(client, mock_confluence_fetcher):
    """Test the search tool with basic query."""
    response = await client.call_tool("confluence_search", {"query": "test search"})

    mock_confluence_fetcher.search.assert_called_once()
    args, kwargs = mock_confluence_fetcher.search.call_args
    assert 'siteSearch ~ "test search"' in args[0]
    assert kwargs.get("limit") == 10
    assert kwargs.get("spaces_filter") is None

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert len(result_data) > 0
    assert result_data[0]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_page(client, mock_confluence_fetcher):
    """Test the get_page tool with default parameters."""
    response = await client.call_tool("confluence_get_page", {"page_id": "123456"})

    mock_confluence_fetcher.get_page_content.assert_called_once_with(
        "123456", convert_to_markdown=True
    )

    result_data = json.loads(response[0].text)
    assert "metadata" in result_data
    assert result_data["metadata"]["title"] == "Test Page Mock Title"
    assert "content" in result_data["metadata"]
    assert "value" in result_data["metadata"]["content"]
    assert "This is a test page content" in result_data["metadata"]["content"]["value"]


@pytest.mark.anyio
async def test_get_page_no_metadata(client, mock_confluence_fetcher):
    """Test get_page with metadata disabled."""
    response = await client.call_tool(
        "confluence_get_page", {"page_id": "123456", "include_metadata": False}
    )

    mock_confluence_fetcher.get_page_content.assert_called_once_with(
        "123456", convert_to_markdown=True
    )

    result_data = json.loads(response[0].text)
    assert "metadata" not in result_data
    assert "content" in result_data
    assert "This is a test page content" in result_data["content"]["value"]


@pytest.mark.anyio
async def test_get_page_no_markdown(client, mock_confluence_fetcher):
    """Test get_page with HTML content format."""
    mock_page_html = MagicMock(spec=ConfluencePage)
    mock_page_html.to_simplified_dict.return_value = {
        "id": "123456",
        "title": "Test Page HTML",
        "url": "https://example.com/html",
        "content": "<p>HTML Content</p>",
        "content_format": "storage",
    }
    mock_page_html.content = "<p>HTML Content</p>"
    mock_page_html.content_format = "storage"

    mock_confluence_fetcher.get_page_content.return_value = mock_page_html

    response = await client.call_tool(
        "confluence_get_page", {"page_id": "123456", "convert_to_markdown": False}
    )

    mock_confluence_fetcher.get_page_content.assert_called_once_with(
        "123456", convert_to_markdown=False
    )

    result_data = json.loads(response[0].text)
    assert "metadata" in result_data
    assert result_data["metadata"]["title"] == "Test Page HTML"
    assert result_data["metadata"]["content"] == "<p>HTML Content</p>"
    assert result_data["metadata"]["content_format"] == "storage"


@pytest.mark.anyio
async def test_get_page_children(client, mock_confluence_fetcher):
    """Test the get_page_children tool."""
    response = await client.call_tool(
        "confluence_get_page_children", {"parent_id": "123456"}
    )

    mock_confluence_fetcher.get_page_children.assert_called_once()
    call_kwargs = mock_confluence_fetcher.get_page_children.call_args.kwargs
    assert call_kwargs["page_id"] == "123456"
    assert call_kwargs.get("start") == 0
    assert call_kwargs.get("limit") == 25
    assert call_kwargs.get("expand") == "version"

    result_data = json.loads(response[0].text)
    assert "parent_id" in result_data
    assert "results" in result_data
    assert len(result_data["results"]) > 0
    assert result_data["results"][0]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_comments(client, mock_confluence_fetcher):
    """Test retrieving page comments."""
    response = await client.call_tool("confluence_get_comments", {"page_id": "123456"})

    mock_confluence_fetcher.get_page_comments.assert_called_once_with("123456")

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert len(result_data) > 0
    assert result_data[0]["author"] == "Test User"


@pytest.mark.anyio
async def test_add_comment(client, mock_confluence_fetcher):
    """Test adding a comment to a Confluence page."""
    response = await client.call_tool(
        "confluence_add_comment",
        {"page_id": "123456", "content": "Test comment content"},
    )

    mock_confluence_fetcher.add_comment.assert_called_once_with(
        page_id="123456", content="Test comment content"
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert result_data["success"] is True
    assert "comment" in result_data
    assert result_data["comment"]["id"] == "987"
    assert result_data["comment"]["author"] == "Test User"
    assert result_data["comment"]["body"] == "This is a test comment added via API"
    assert result_data["comment"]["created"] == "2023-08-01T13:00:00.000Z"


@pytest.mark.anyio
async def test_get_labels(client, mock_confluence_fetcher):
    """Test retrieving page labels."""
    response = await client.call_tool("confluence_get_labels", {"page_id": "123456"})
    mock_confluence_fetcher.get_page_labels.assert_called_once_with("123456")
    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert result_data[0]["name"] == "test-label"


@pytest.mark.anyio
async def test_add_label(client, mock_confluence_fetcher):
    """Test adding a label to a page."""
    response = await client.call_tool(
        "confluence_add_label", {"page_id": "123456", "name": "new-label"}
    )
    mock_confluence_fetcher.add_page_label.assert_called_once_with(
        "123456", "new-label"
    )
    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert result_data[0]["name"] == "test-label"


@pytest.mark.anyio
async def test_search_user(client, mock_confluence_fetcher):
    """Test the search_user tool with CQL query."""
    response = await client.call_tool(
        "confluence_search_user", {"query": 'user.fullname ~ "First Last"', "limit": 10}
    )

    mock_confluence_fetcher.search_user.assert_called_once_with(
        'user.fullname ~ "First Last"', limit=10
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, list)
    assert len(result_data) == 1
    assert result_data[0]["entity_type"] == "user"
    assert result_data[0]["title"] == "First Last"
    assert result_data[0]["user"]["account_id"] == "a031248587011jasoidf9832jd8j1"
    assert result_data[0]["user"]["display_name"] == "First Last"


@pytest.mark.anyio
async def test_create_page_with_numeric_parent_id(client, mock_confluence_fetcher):
    """Test creating a page with numeric parent_id (integer) - should convert to string."""
    response = await client.call_tool(
        "confluence_create_page",
        {
            "space_key": "TEST",
            "title": "Test Page",
            "content": "Test content",
            "parent_id": 123456789,  # Numeric ID as integer
        },
    )

    # Verify the parent_id was converted to string when calling the underlying method
    mock_confluence_fetcher.create_page.assert_called_once()
    call_kwargs = mock_confluence_fetcher.create_page.call_args.kwargs
    assert call_kwargs["parent_id"] == "123456789"  # Should be string
    assert call_kwargs["space_key"] == "TEST"
    assert call_kwargs["title"] == "Test Page"

    result_data = json.loads(response[0].text)
    assert result_data["message"] == "Page created successfully"
    assert result_data["page"]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_create_page_with_string_parent_id(client, mock_confluence_fetcher):
    """Test creating a page with string parent_id - should remain unchanged."""
    response = await client.call_tool(
        "confluence_create_page",
        {
            "space_key": "TEST",
            "title": "Test Page",
            "content": "Test content",
            "parent_id": "123456789",  # String ID
        },
    )

    mock_confluence_fetcher.create_page.assert_called_once()
    call_kwargs = mock_confluence_fetcher.create_page.call_args.kwargs
    assert call_kwargs["parent_id"] == "123456789"  # Should remain string
    assert call_kwargs["space_key"] == "TEST"
    assert call_kwargs["title"] == "Test Page"

    result_data = json.loads(response[0].text)
    assert result_data["message"] == "Page created successfully"
    assert result_data["page"]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_update_page_with_numeric_parent_id(client, mock_confluence_fetcher):
    """Test updating a page with numeric parent_id (integer) - should convert to string."""
    response = await client.call_tool(
        "confluence_update_page",
        {
            "page_id": "999999",
            "title": "Updated Page",
            "content": "Updated content",
            "parent_id": 123456789,  # Numeric ID as integer
        },
    )

    mock_confluence_fetcher.update_page.assert_called_once()
    call_kwargs = mock_confluence_fetcher.update_page.call_args.kwargs
    assert call_kwargs["parent_id"] == "123456789"  # Should be string
    assert call_kwargs["page_id"] == "999999"
    assert call_kwargs["title"] == "Updated Page"

    result_data = json.loads(response[0].text)
    assert result_data["message"] == "Page updated successfully"
    assert result_data["page"]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_space_root_pages_basic(client, mock_confluence_fetcher):
    """Test get_space_root_pages with basic parameters."""
    response = await client.call_tool(
        "confluence_get_space_root_pages", {"space_key": "TEST"}
    )

    mock_confluence_fetcher.get_space_root_pages.assert_called_once_with(
        space_key="TEST",
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "space_key" in result_data
    assert result_data["space_key"] == "TEST"
    assert "count" in result_data
    assert "results" in result_data
    assert isinstance(result_data["results"], list)
    assert len(result_data["results"]) == 1
    assert result_data["results"][0]["title"] == "Welcome to Test Space"
    assert result_data["results"][0]["id"] == "root123"


@pytest.mark.anyio
async def test_get_space_root_pages_custom_parameters(client, mock_confluence_fetcher):
    """Test get_space_root_pages with custom limit, start, and content options."""
    response = await client.call_tool(
        "confluence_get_space_root_pages",
        {
            "space_key": "CUSTOM",
            "limit": 25,
            "start": 10,
            "convert_to_markdown": False,
            "include_content": False,
        },
    )

    mock_confluence_fetcher.get_space_root_pages.assert_called_once_with(
        space_key="CUSTOM",
        start=10,
        limit=25,
        expand="version",
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "CUSTOM"
    assert "results" in result_data
    assert isinstance(result_data["results"], list)


@pytest.mark.anyio
async def test_get_space_root_pages_empty_results(client, mock_confluence_fetcher):
    """Test get_space_root_pages when no root pages found."""
    # Mock empty response
    mock_confluence_fetcher.get_space_root_pages.return_value = []

    response = await client.call_tool(
        "confluence_get_space_root_pages", {"space_key": "EMPTY"}
    )

    mock_confluence_fetcher.get_space_root_pages.assert_called_once_with(
        space_key="EMPTY",
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "EMPTY"
    assert result_data["count"] == 0
    assert result_data["results"] == []


@pytest.mark.anyio
async def test_get_space_root_pages_limit_validation(client, mock_confluence_fetcher):
    """Test get_space_root_pages with various limit values."""
    # Test minimum limit
    response = await client.call_tool(
        "confluence_get_space_root_pages", {"space_key": "TEST", "limit": 1}
    )
    mock_confluence_fetcher.get_space_root_pages.assert_called_with(
        space_key="TEST",
        start=0,
        limit=1,
        expand="version",
        convert_to_markdown=True,
    )

    # Test maximum limit
    mock_confluence_fetcher.get_space_root_pages.reset_mock()
    response = await client.call_tool(
        "confluence_get_space_root_pages", {"space_key": "TEST", "limit": 200}
    )
    mock_confluence_fetcher.get_space_root_pages.assert_called_with(
        space_key="TEST",
        start=0,
        limit=200,
        expand="version",
        convert_to_markdown=True,
    )


@pytest.mark.anyio
async def test_get_space_root_pages_pagination(client, mock_confluence_fetcher):
    """Test get_space_root_pages with pagination parameters."""
    response = await client.call_tool(
        "confluence_get_space_root_pages",
        {"space_key": "TEST", "start": 25, "limit": 10},
    )

    mock_confluence_fetcher.get_space_root_pages.assert_called_once_with(
        space_key="TEST",
        start=25,
        limit=10,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert "results" in result_data


@pytest.mark.anyio
async def test_get_space_root_pages_content_options(client, mock_confluence_fetcher):
    """Test get_space_root_pages with different content processing options."""
    # Test with markdown conversion disabled and content excluded
    response = await client.call_tool(
        "confluence_get_space_root_pages",
        {
            "space_key": "TEST",
            "convert_to_markdown": False,
            "include_content": False,
        },
    )

    mock_confluence_fetcher.get_space_root_pages.assert_called_once_with(
        space_key="TEST",
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert "results" in result_data


@pytest.mark.anyio
async def test_get_space_root_pages_error_handling(client, mock_confluence_fetcher):
    """Test get_space_root_pages error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_space_root_pages.side_effect = Exception(
        "Space not found"
    )

    response = await client.call_tool(
        "confluence_get_space_root_pages", {"space_key": "NONEXISTENT"}
    )

    # Should still return a valid response structure with empty results
    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "NONEXISTENT"
    assert result_data["count"] == 0
    assert result_data["results"] == []


@pytest.mark.anyio
async def test_update_page_with_string_parent_id(client, mock_confluence_fetcher):
    """Test updating a page with string parent_id - should remain unchanged."""
    response = await client.call_tool(
        "confluence_update_page",
        {
            "page_id": "999999",
            "title": "Updated Page",
            "content": "Updated content",
            "parent_id": "123456789",  # String ID
        },
    )

    mock_confluence_fetcher.update_page.assert_called_once()
    call_kwargs = mock_confluence_fetcher.update_page.call_args.kwargs
    assert call_kwargs["parent_id"] == "123456789"  # Should remain string
    assert call_kwargs["page_id"] == "999999"
    assert call_kwargs["title"] == "Updated Page"

    result_data = json.loads(response[0].text)
    assert result_data["message"] == "Page updated successfully"
    assert result_data["page"]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_page_siblings_basic(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with basic parameters."""
    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "123456"}
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=False,
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "page_id" in result_data
    assert result_data["page_id"] == "123456"
    assert "include_self" in result_data
    assert result_data["include_self"] is False
    assert "count" in result_data
    assert "results" in result_data
    assert isinstance(result_data["results"], list)
    assert len(result_data["results"]) == 1
    assert result_data["results"][0]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_page_siblings_include_self(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with include_self=True."""
    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "123456", "include_self": True}
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=True,
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["include_self"] is True
    assert "results" in result_data
    assert isinstance(result_data["results"], list)


@pytest.mark.anyio
async def test_get_page_siblings_pagination(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with pagination parameters."""
    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "123456", "start": 10, "limit": 25}
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=False,
        start=10,
        limit=25,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["start_requested"] == 10
    assert result_data["limit_requested"] == 25
    assert "results" in result_data


@pytest.mark.anyio
async def test_get_page_siblings_with_content(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with content inclusion."""
    response = await client.call_tool(
        "confluence_get_page_siblings",
        {"page_id": "123456", "include_content": True, "convert_to_markdown": False},
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=False,
        start=0,
        limit=50,
        expand="version,body.storage",
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert "results" in result_data
    assert isinstance(result_data["results"], list)


@pytest.mark.anyio
async def test_get_page_siblings_limit_validation(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with various limit values."""
    # Test minimum limit
    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "123456", "limit": 1}
    )
    mock_confluence_fetcher.get_page_siblings.assert_called_with(
        page_id="123456",
        include_self=False,
        start=0,
        limit=1,
        expand="version",
        convert_to_markdown=True,
    )

    # Test maximum limit
    mock_confluence_fetcher.get_page_siblings.reset_mock()
    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "123456", "limit": 200}
    )
    mock_confluence_fetcher.get_page_siblings.assert_called_with(
        page_id="123456",
        include_self=False,
        start=0,
        limit=200,
        expand="version",
        convert_to_markdown=True,
    )


@pytest.mark.anyio
async def test_get_page_siblings_custom_expand(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with custom expand parameter."""
    response = await client.call_tool(
        "confluence_get_page_siblings",
        {"page_id": "123456", "expand": "version,space,ancestors"},
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=False,
        start=0,
        limit=50,
        expand="version,space,ancestors",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert "results" in result_data


@pytest.mark.anyio
async def test_get_page_siblings_empty_results(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool when no siblings found."""
    # Mock empty response
    mock_confluence_fetcher.get_page_siblings.return_value = []

    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "onlychild"}
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="onlychild",
        include_self=False,
        start=0,
        limit=50,
        expand="version",
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "onlychild"
    assert result_data["count"] == 0
    assert result_data["results"] == []


@pytest.mark.anyio
async def test_get_page_siblings_error_handling(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_page_siblings.side_effect = Exception("Page not found")

    response = await client.call_tool(
        "confluence_get_page_siblings", {"page_id": "nonexistent"}
    )

    # Should still return a valid response structure with empty results and error
    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "nonexistent"
    assert result_data["count"] == 0
    assert result_data["results"] == []
    assert "error" in result_data
    assert "Failed to get page siblings" in result_data["error"]


@pytest.mark.anyio
async def test_get_page_siblings_all_parameters(client, mock_confluence_fetcher):
    """Test the get_page_siblings tool with all parameters."""
    response = await client.call_tool(
        "confluence_get_page_siblings",
        {
            "page_id": "123456",
            "include_self": True,
            "start": 5,
            "limit": 15,
            "expand": "version,body.storage,space",
            "include_content": True,
            "convert_to_markdown": False,
        },
    )

    mock_confluence_fetcher.get_page_siblings.assert_called_once_with(
        page_id="123456",
        include_self=True,
        start=5,
        limit=15,
        expand="version,body.storage,space",
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["include_self"] is True
    assert result_data["start_requested"] == 5
    assert result_data["limit_requested"] == 15
    assert "results" in result_data


@pytest.mark.anyio
async def test_get_page_breadcrumbs_basic(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool with basic parameters."""
    response = await client.call_tool(
        "confluence_get_page_breadcrumbs", {"page_id": "123456"}
    )

    mock_confluence_fetcher.get_page_breadcrumbs.assert_called_once_with(
        page_id="123456", include_content=False
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "page_id" in result_data
    assert result_data["page_id"] == "123456"
    assert "breadcrumb_count" in result_data
    assert result_data["breadcrumb_count"] == 2
    assert "include_content" in result_data
    assert result_data["include_content"] is False
    assert "convert_to_markdown" in result_data
    assert result_data["convert_to_markdown"] is True
    assert "breadcrumbs" in result_data
    assert isinstance(result_data["breadcrumbs"], list)
    assert len(result_data["breadcrumbs"]) == 2


@pytest.mark.anyio
async def test_get_page_breadcrumbs_with_content(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool with content included."""
    response = await client.call_tool(
        "confluence_get_page_breadcrumbs",
        {"page_id": "123456", "include_content": True, "convert_to_markdown": False},
    )

    mock_confluence_fetcher.get_page_breadcrumbs.assert_called_once_with(
        page_id="123456", include_content=True
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is False
    assert "breadcrumbs" in result_data
    assert isinstance(result_data["breadcrumbs"], list)


@pytest.mark.anyio
async def test_get_page_breadcrumbs_root_page(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool for root page (single breadcrumb)."""
    # Mock a single page (root page)
    mock_root_page = MagicMock(spec=ConfluencePage)
    mock_root_page.to_simplified_dict.return_value = {
        "id": "root123",
        "title": "Root Page",
        "space": {"key": "TEST", "name": "Test Space"},
    }
    mock_confluence_fetcher.get_page_breadcrumbs.return_value = [mock_root_page]

    response = await client.call_tool(
        "confluence_get_page_breadcrumbs", {"page_id": "root123"}
    )

    mock_confluence_fetcher.get_page_breadcrumbs.assert_called_once_with(
        page_id="root123", include_content=False
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "root123"
    assert result_data["breadcrumb_count"] == 1
    assert len(result_data["breadcrumbs"]) == 1
    assert result_data["breadcrumbs"][0]["title"] == "Root Page"


@pytest.mark.anyio
async def test_get_page_breadcrumbs_deep_hierarchy(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool for deeply nested page."""
    # Mock a 4-level hierarchy
    mock_pages = []
    for i, title in enumerate(["Root", "Level 1", "Level 2", "Current Page"]):
        mock_page = MagicMock(spec=ConfluencePage)
        mock_page.to_simplified_dict.return_value = {
            "id": f"page{i}",
            "title": title,
            "space": {"key": "TEST"},
        }
        mock_pages.append(mock_page)

    mock_confluence_fetcher.get_page_breadcrumbs.return_value = mock_pages

    response = await client.call_tool(
        "confluence_get_page_breadcrumbs", {"page_id": "page3"}
    )

    mock_confluence_fetcher.get_page_breadcrumbs.assert_called_once_with(
        page_id="page3", include_content=False
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "page3"
    assert result_data["breadcrumb_count"] == 4
    assert len(result_data["breadcrumbs"]) == 4
    # Verify breadcrumb order
    expected_titles = ["Root", "Level 1", "Level 2", "Current Page"]
    actual_titles = [page["title"] for page in result_data["breadcrumbs"]]
    assert actual_titles == expected_titles


@pytest.mark.anyio
async def test_get_page_breadcrumbs_error_handling(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_page_breadcrumbs.side_effect = Exception(
        "Page not found"
    )

    response = await client.call_tool(
        "confluence_get_page_breadcrumbs", {"page_id": "nonexistent"}
    )

    # Should still return a valid response structure with empty results and error
    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "nonexistent"
    assert result_data["breadcrumb_count"] == 0
    assert result_data["breadcrumbs"] == []
    assert "error" in result_data
    assert "Failed to get page breadcrumbs" in result_data["error"]


@pytest.mark.anyio
async def test_get_page_breadcrumbs_empty_results(client, mock_confluence_fetcher):
    """Test the get_page_breadcrumbs tool when no breadcrumbs found."""
    # Mock empty response
    mock_confluence_fetcher.get_page_breadcrumbs.return_value = []

    response = await client.call_tool(
        "confluence_get_page_breadcrumbs", {"page_id": "orphan"}
    )

    mock_confluence_fetcher.get_page_breadcrumbs.assert_called_once_with(
        page_id="orphan", include_content=False
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "orphan"
    assert result_data["breadcrumb_count"] == 0
    assert result_data["breadcrumbs"] == []


@pytest.mark.anyio
async def test_get_page_descendants_basic(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with basic parameters."""
    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456"}
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=None,
        limit=200,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "page_id" in result_data
    assert result_data["page_id"] == "123456"
    assert "max_depth" in result_data
    assert result_data["max_depth"] is None
    assert "limit" in result_data
    assert result_data["limit"] == 200
    assert "include_content" in result_data
    assert result_data["include_content"] is False
    assert "count" in result_data
    assert "descendants" in result_data
    assert isinstance(result_data["descendants"], list)
    assert len(result_data["descendants"]) == 1
    assert result_data["descendants"][0]["title"] == "Test Page Mock Title"


@pytest.mark.anyio
async def test_get_page_descendants_with_depth_limit(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with depth limit."""
    response = await client.call_tool(
        "confluence_get_page_descendants",
        {"page_id": "123456", "max_depth": 2, "limit": 50},
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=2,
        limit=50,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["max_depth"] == 2
    assert result_data["limit"] == 50
    assert "descendants" in result_data
    assert isinstance(result_data["descendants"], list)


@pytest.mark.anyio
async def test_get_page_descendants_with_content(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with content inclusion."""
    response = await client.call_tool(
        "confluence_get_page_descendants",
        {"page_id": "123456", "include_content": True, "limit": 100},
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=None,
        limit=100,
        include_content=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["include_content"] is True
    assert result_data["limit"] == 100
    assert "descendants" in result_data
    assert isinstance(result_data["descendants"], list)


@pytest.mark.anyio
async def test_get_page_descendants_limit_validation(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with various limit values."""
    # Test minimum limit
    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456", "limit": 1}
    )
    mock_confluence_fetcher.get_page_descendants.assert_called_with(
        page_id="123456",
        max_depth=None,
        limit=1,
        include_content=False,
    )

    # Test maximum limit
    mock_confluence_fetcher.get_page_descendants.reset_mock()
    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456", "limit": 500}
    )
    mock_confluence_fetcher.get_page_descendants.assert_called_with(
        page_id="123456",
        max_depth=None,
        limit=500,
        include_content=False,
    )


@pytest.mark.anyio
async def test_get_page_descendants_multi_level_hierarchy(
    client, mock_confluence_fetcher
):
    """Test the get_page_descendants tool with multi-level hierarchy."""
    # Mock a multi-level hierarchy response
    mock_child1 = MagicMock(spec=ConfluencePage)
    mock_child1.to_simplified_dict.return_value = {
        "id": "child1",
        "title": "Child Page 1",
        "url": "https://example.com/child1",
        "content": {"value": "Child 1 content", "format": "markdown"},
    }

    mock_grandchild = MagicMock(spec=ConfluencePage)
    mock_grandchild.to_simplified_dict.return_value = {
        "id": "grandchild1",
        "title": "Grandchild Page 1",
        "url": "https://example.com/grandchild1",
        "content": {"value": "Grandchild content", "format": "markdown"},
    }

    mock_confluence_fetcher.get_page_descendants.return_value = [
        mock_child1,
        mock_grandchild,
    ]

    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456", "max_depth": 3}
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=3,
        limit=200,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["max_depth"] == 3
    assert result_data["count"] == 2
    assert len(result_data["descendants"]) == 2

    # Check that both child and grandchild are present
    titles = [page["title"] for page in result_data["descendants"]]
    assert "Child Page 1" in titles
    assert "Grandchild Page 1" in titles


@pytest.mark.anyio
async def test_get_page_descendants_empty_results(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool when no descendants found."""
    # Mock empty response
    mock_confluence_fetcher.get_page_descendants.return_value = []

    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "leafpage"}
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="leafpage",
        max_depth=None,
        limit=200,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "leafpage"
    assert result_data["count"] == 0
    assert result_data["descendants"] == []


@pytest.mark.anyio
async def test_get_page_descendants_error_handling(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_page_descendants.side_effect = Exception(
        "Page not found"
    )

    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "nonexistent"}
    )

    # Should still return a valid response structure with empty results and error
    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "nonexistent"
    assert result_data["count"] == 0
    assert result_data["descendants"] == []
    assert "error" in result_data
    assert "Failed to get page descendants" in result_data["error"]


@pytest.mark.anyio
async def test_get_page_descendants_all_parameters(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with all parameters."""
    response = await client.call_tool(
        "confluence_get_page_descendants",
        {
            "page_id": "123456",
            "max_depth": 5,
            "limit": 150,
            "include_content": True,
        },
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=5,
        limit=150,
        include_content=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["max_depth"] == 5
    assert result_data["limit"] == 150
    assert result_data["include_content"] is True
    assert "descendants" in result_data


@pytest.mark.anyio
async def test_get_page_descendants_depth_zero(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with depth zero (should return empty)."""
    # Mock empty response for depth 0
    mock_confluence_fetcher.get_page_descendants.return_value = []

    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456", "max_depth": 0}
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=0,
        limit=200,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["max_depth"] == 0
    assert result_data["count"] == 0
    assert result_data["descendants"] == []


@pytest.mark.anyio
async def test_get_page_descendants_large_hierarchy(client, mock_confluence_fetcher):
    """Test the get_page_descendants tool with a large hierarchy that hits the limit."""
    # Mock a large number of descendants
    mock_descendants = []
    for i in range(250):  # More than default limit of 200
        mock_page = MagicMock(spec=ConfluencePage)
        mock_page.to_simplified_dict.return_value = {
            "id": f"page{i}",
            "title": f"Page {i}",
            "url": f"https://example.com/page{i}",
            "content": {"value": f"Content for page {i}", "format": "markdown"},
        }
        mock_descendants.append(mock_page)

    # Mock should return only up to the limit
    mock_confluence_fetcher.get_page_descendants.return_value = mock_descendants[:200]

    response = await client.call_tool(
        "confluence_get_page_descendants", {"page_id": "123456", "limit": 200}
    )

    mock_confluence_fetcher.get_page_descendants.assert_called_once_with(
        page_id="123456",
        max_depth=None,
        limit=200,
        include_content=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["page_id"] == "123456"
    assert result_data["limit"] == 200
    assert result_data["count"] == 200
    assert len(result_data["descendants"]) == 200


@pytest.mark.anyio
async def test_get_page_by_path_basic(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with a basic single-level path."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {"space_key": "TEST", "path": "Documentation Guidelines"},
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="TEST",
        path="Documentation Guidelines",
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "space_key" in result_data
    assert result_data["space_key"] == "TEST"
    assert "path" in result_data
    assert result_data["path"] == "Documentation Guidelines"
    assert "page" in result_data
    assert result_data["page"]["title"] == "Documentation Guidelines"
    assert result_data["page"]["id"] == "path123"


@pytest.mark.anyio
async def test_get_page_by_path_multi_level(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with a multi-level path."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {"space_key": "DEV", "path": "Project/Docs/Setup Guide"},
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="DEV",
        path="Project/Docs/Setup Guide",
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "DEV"
    assert result_data["path"] == "Project/Docs/Setup Guide"
    assert "page" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_backslash_separator(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with backslash path separator."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {"space_key": "WIN", "path": "Docs\\Windows\\Installation"},
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="WIN",
        path="Docs\\Windows\\Installation",
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "WIN"
    assert result_data["path"] == "Docs\\Windows\\Installation"
    assert "page" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_with_content(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with content inclusion."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {
            "space_key": "TEST",
            "path": "API/Documentation",
            "include_content": True,
            "convert_to_markdown": False,
        },
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="TEST",
        path="API/Documentation",
        include_content=True,
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is False
    assert "page" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_not_found(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool when page is not found."""
    # Mock returning None for page not found
    mock_confluence_fetcher.get_page_by_path.return_value = None

    response = await client.call_tool(
        "confluence_get_page_by_path", {"space_key": "TEST", "path": "Nonexistent/Page"}
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="TEST",
        path="Nonexistent/Page",
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["path"] == "Nonexistent/Page"
    assert result_data["found"] is False
    assert "error" in result_data
    assert "not found" in result_data["error"].lower()


@pytest.mark.anyio
async def test_get_page_by_path_empty_path(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with empty path."""
    # Mock returning None for empty/invalid path
    mock_confluence_fetcher.get_page_by_path.return_value = None

    response = await client.call_tool(
        "confluence_get_page_by_path", {"space_key": "TEST", "path": ""}
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="TEST", path="", include_content=False, convert_to_markdown=True
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["path"] == ""
    assert result_data["found"] is False
    assert "error" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_with_leading_trailing_slashes(
    client, mock_confluence_fetcher
):
    """Test the get_page_by_path tool with leading and trailing slashes."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {"space_key": "TEST", "path": "/Project/Documentation/"},
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="TEST",
        path="/Project/Documentation/",
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["path"] == "/Project/Documentation/"
    assert "page" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_error_handling(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_page_by_path.side_effect = Exception("Space not found")

    response = await client.call_tool(
        "confluence_get_page_by_path", {"space_key": "INVALID", "path": "Some/Path"}
    )

    # Should still return a valid response structure with error
    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "INVALID"
    assert result_data["path"] == "Some/Path"
    assert result_data["found"] is False
    assert "error" in result_data
    assert "error" in result_data
    assert "Failed to find page by path" in result_data["error"]


@pytest.mark.anyio
async def test_get_page_by_path_all_parameters(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with all parameters specified."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {
            "space_key": "FULL",
            "path": "Complete/Example/Path",
            "include_content": True,
            "convert_to_markdown": False,
        },
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="FULL",
        path="Complete/Example/Path",
        include_content=True,
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "FULL"
    assert result_data["path"] == "Complete/Example/Path"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is False
    assert "page" in result_data


@pytest.mark.anyio
async def test_get_page_by_path_markdown_conversion(client, mock_confluence_fetcher):
    """Test the get_page_by_path tool with markdown conversion enabled."""
    response = await client.call_tool(
        "confluence_get_page_by_path",
        {
            "space_key": "MD",
            "path": "Markdown/Example",
            "include_content": True,
            "convert_to_markdown": True,
        },
    )

    mock_confluence_fetcher.get_page_by_path.assert_called_once_with(
        space_key="MD",
        path="Markdown/Example",
        include_content=True,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "MD"
    assert result_data["path"] == "Markdown/Example"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is True
    assert "page" in result_data
    assert result_data["page"]["title"] == "Documentation Guidelines"


@pytest.mark.anyio
async def test_get_space_pages_flat_basic(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with basic parameters."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "TEST"}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="TEST",
        limit=1000,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert isinstance(result_data, dict)
    assert "space_key" in result_data
    assert result_data["space_key"] == "TEST"
    assert "total_pages" in result_data
    assert result_data["total_pages"] == 5
    assert "limit_requested" in result_data
    assert result_data["limit_requested"] == 1000
    assert "pages" in result_data
    assert isinstance(result_data["pages"], list)
    assert len(result_data["pages"]) == 5
    assert result_data["pages"][0]["title"] == "Flat Page 0"
    assert result_data["pages"][0]["id"] == "flat0"


@pytest.mark.anyio
async def test_get_space_pages_flat_custom_limit(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with custom limit."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "TEST", "limit": 500}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="TEST",
        limit=500,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["limit_requested"] == 500
    assert "pages" in result_data
    assert isinstance(result_data["pages"], list)


@pytest.mark.anyio
async def test_get_space_pages_flat_with_content(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with content inclusion."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat",
        {
            "space_key": "TEST",
            "include_content": True,
            "convert_to_markdown": False,
        },
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="TEST",
        limit=1000,
        include_content=True,
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TEST"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is False
    assert "pages" in result_data
    assert isinstance(result_data["pages"], list)


@pytest.mark.anyio
async def test_get_space_pages_flat_limit_validation(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with various limit values."""
    # Test minimum limit
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "TEST", "limit": 1}
    )
    mock_confluence_fetcher.get_space_pages_flat.assert_called_with(
        space_key="TEST",
        limit=1,
        include_content=False,
        convert_to_markdown=True,
    )

    # Test maximum limit
    mock_confluence_fetcher.get_space_pages_flat.reset_mock()
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "TEST", "limit": 5000}
    )
    mock_confluence_fetcher.get_space_pages_flat.assert_called_with(
        space_key="TEST",
        limit=5000,
        include_content=False,
        convert_to_markdown=True,
    )


@pytest.mark.anyio
async def test_get_space_pages_flat_empty_results(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool when no pages found."""
    # Mock empty response
    mock_confluence_fetcher.get_space_pages_flat.return_value = []

    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "EMPTY"}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="EMPTY",
        limit=1000,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "EMPTY"
    assert result_data["total_pages"] == 0
    assert result_data["pages"] == []


@pytest.mark.anyio
async def test_get_space_pages_flat_large_collection(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with a large collection and summary."""
    # Mock a large collection that would trigger summary
    mock_large_pages = []
    for i in range(150):  # Large collection for summary test
        mock_page = MagicMock(spec=ConfluencePage)
        mock_page.to_simplified_dict.return_value = {
            "id": f"large{i}",
            "title": f"Large Page {i}",
            "url": f"https://example.atlassian.net/wiki/spaces/LARGE/pages/large{i}/Large+Page+{i}",
            "content": {
                "value": f"This is large page {i} content in Markdown",
                "format": "markdown",
            },
            "space": {"key": "LARGE", "name": "Large Space"},
        }
        mock_large_pages.append(mock_page)

    mock_confluence_fetcher.get_space_pages_flat.return_value = mock_large_pages

    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "LARGE", "limit": 200}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="LARGE",
        limit=200,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "LARGE"
    assert result_data["total_pages"] == 150
    assert result_data["limit_requested"] == 200
    assert len(result_data["pages"]) == 150
    # Should include summary for large result sets
    assert "summary" in result_data
    assert result_data["summary"]["total_pages"] == 150


@pytest.mark.anyio
async def test_get_space_pages_flat_all_parameters(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool with all parameters."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat",
        {
            "space_key": "FULL",
            "limit": 250,
            "include_content": True,
            "convert_to_markdown": False,
        },
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="FULL",
        limit=250,
        include_content=True,
        convert_to_markdown=False,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "FULL"
    assert result_data["limit_requested"] == 250
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is False
    assert "pages" in result_data


@pytest.mark.anyio
async def test_get_space_pages_flat_error_handling(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool error handling."""
    # Mock an exception being raised
    mock_confluence_fetcher.get_space_pages_flat.side_effect = Exception(
        "Space not found"
    )

    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "NONEXISTENT"}
    )

    # Should still return a valid response structure with empty results and error
    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "NONEXISTENT"
    assert result_data["total_pages"] == 0
    assert result_data["pages"] == []
    assert "error" in result_data
    assert "Failed to get pages from space" in result_data["error"]


@pytest.mark.anyio
async def test_get_space_pages_flat_markdown_conversion(
    client, mock_confluence_fetcher
):
    """Test the get_space_pages_flat tool with markdown conversion enabled."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat",
        {
            "space_key": "MD",
            "include_content": True,
            "convert_to_markdown": True,
        },
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="MD",
        limit=1000,
        include_content=True,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "MD"
    assert result_data["include_content"] is True
    assert result_data["convert_to_markdown"] is True
    assert "pages" in result_data
    assert isinstance(result_data["pages"], list)


@pytest.mark.anyio
async def test_get_space_pages_flat_space_key_validation(
    client, mock_confluence_fetcher
):
    """Test the get_space_pages_flat tool with different space key formats."""
    # Test with uppercase space key
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "TESTSPACE"}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="TESTSPACE",
        limit=1000,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "TESTSPACE"
    assert "pages" in result_data


@pytest.mark.anyio
async def test_get_space_pages_flat_performance_metadata(
    client, mock_confluence_fetcher
):
    """Test the get_space_pages_flat tool includes performance metadata."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "PERF", "limit": 100}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="PERF",
        limit=100,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "PERF"
    assert result_data["limit_requested"] == 100
    assert "total_pages" in result_data
    assert "pages" in result_data
    # Performance metadata should be present
    assert isinstance(result_data["total_pages"], int)
    assert isinstance(result_data["pages"], list)


@pytest.mark.anyio
async def test_get_space_pages_flat_content_structure(client, mock_confluence_fetcher):
    """Test the get_space_pages_flat tool returns correct content structure."""
    response = await client.call_tool(
        "confluence_get_space_pages_flat", {"space_key": "STRUCT"}
    )

    mock_confluence_fetcher.get_space_pages_flat.assert_called_once_with(
        space_key="STRUCT",
        limit=1000,
        include_content=False,
        convert_to_markdown=True,
    )

    result_data = json.loads(response[0].text)
    assert result_data["space_key"] == "STRUCT"

    # Verify the structure of returned pages
    if result_data["pages"]:
        page = result_data["pages"][0]
        assert "id" in page
        assert "title" in page
        assert "url" in page
        assert "space" in page
        assert isinstance(page["space"], dict)
        assert "key" in page["space"]
        assert "name" in page["space"]
