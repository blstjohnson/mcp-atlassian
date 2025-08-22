"""Unit tests for the PagesMixin class."""

from unittest.mock import MagicMock, patch

import pytest

from mcp_atlassian.confluence.pages import PagesMixin
from mcp_atlassian.models.confluence import ConfluencePage


class TestPagesMixin:
    """Tests for the PagesMixin class."""

    @pytest.fixture
    def pages_mixin(self, confluence_client):
        """Create a PagesMixin instance for testing."""
        # PagesMixin inherits from ConfluenceClient, so we need to create it properly
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceClient.__init__"
        ) as mock_init:
            mock_init.return_value = None
            mixin = PagesMixin()
            # Copy the necessary attributes from our mocked client
            mixin.confluence = confluence_client.confluence
            mixin.config = confluence_client.config
            mixin.preprocessor = confluence_client.preprocessor
            return mixin

    def test_get_page_content(self, pages_mixin):
        """Test getting page content by ID."""
        # Arrange
        page_id = "987654321"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Act
        result = pages_mixin.get_page_content(page_id, convert_to_markdown=True)

        # Assert
        pages_mixin.confluence.get_page_by_id.assert_called_once_with(
            page_id=page_id, expand="body.storage,version,space,children.attachment"
        )

        # Verify result structure
        assert isinstance(result, ConfluencePage)
        assert result.id == "987654321"
        assert result.title == "Example Meeting Notes"

        # Test space information
        assert result.space is not None
        assert result.space.key == "PROJ"

        # Use direct attributes instead of backward compatibility
        assert result.content == "Processed Markdown"
        assert result.id == page_id
        assert result.title == "Example Meeting Notes"
        assert result.space.key == "PROJ"
        assert result.url is not None

        # Test version information
        assert result.version is not None
        assert result.version.number == 1

        # Test attachments
        assert result.attachments is not None
        assert len(result.attachments) == 2
        assert result.attachments[0].id is not None
        assert result.attachments[1].id is not None

    def test_get_page_ancestors(self, pages_mixin):
        """Test getting page ancestors (parent pages)."""
        # Arrange
        page_id = "987654321"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the ancestors API response
        ancestors_data = [
            {
                "id": "123456789",
                "title": "Parent Page",
                "type": "page",
                "status": "current",
                "space": {"key": "PROJ", "name": "Project Space"},
            },
            {
                "id": "111222333",
                "title": "Grandparent Page",
                "type": "page",
                "status": "current",
                "space": {"key": "PROJ", "name": "Project Space"},
            },
        ]
        pages_mixin.confluence.get_page_ancestors.return_value = ancestors_data

        # Act
        result = pages_mixin.get_page_ancestors(page_id)

        # Assert
        pages_mixin.confluence.get_page_ancestors.assert_called_once_with(page_id)

        # Verify result structure
        assert isinstance(result, list)
        assert len(result) == 2

        # Test first ancestor (parent)
        assert isinstance(result[0], ConfluencePage)
        assert result[0].id == "123456789"
        assert result[0].title == "Parent Page"
        assert result[0].space.key == "PROJ"

        # Test second ancestor (grandparent)
        assert isinstance(result[1], ConfluencePage)
        assert result[1].id == "111222333"
        assert result[1].title == "Grandparent Page"

    def test_get_page_ancestors_empty(self, pages_mixin):
        """Test getting ancestors when there are none (top-level page)."""
        # Arrange
        page_id = "987654321"
        pages_mixin.confluence.get_page_ancestors.return_value = []

        # Act
        result = pages_mixin.get_page_ancestors(page_id)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_page_ancestors_error(self, pages_mixin):
        """Test error handling when getting ancestors."""
        # Arrange
        page_id = "987654321"
        pages_mixin.confluence.get_page_ancestors.side_effect = Exception("API Error")

        # Act
        result = pages_mixin.get_page_ancestors(page_id)

        # Assert - should return empty list on error, not raise exception
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_page_content_html(self, pages_mixin):
        """Test getting page content in HTML format."""
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the preprocessor to return HTML
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_content("987654321", convert_to_markdown=False)

        # Assert HTML processing was used
        assert result.content == "<p>Processed HTML</p>"

    def test_get_page_by_title_success(self, pages_mixin):
        """Test getting a page by title when it exists."""
        # Setup
        space_key = "DEMO"
        title = "Example Page"

        # Mock getting the page by title
        pages_mixin.confluence.get_page_by_title.return_value = {
            "id": "987654321",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": "<p>Example content</p>"}},
            "version": {"number": 1},
        }

        # Mock the HTML processing
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Call the method
        result = pages_mixin.get_page_by_title(space_key, title)

        # Verify API calls
        pages_mixin.confluence.get_page_by_title.assert_called_once_with(
            space=space_key, title=title, expand="body.storage,version"
        )

        # Verify result
        assert result.id == "987654321"
        assert result.title == title
        assert result.content == "Processed Markdown"

    def test_get_page_by_title_space_not_found(self, pages_mixin):
        """Test getting a page when the space doesn't exist."""
        # Arrange - API returns None when space doesn't exist
        pages_mixin.confluence.get_page_by_title.return_value = None

        # Act
        result = pages_mixin.get_page_by_title("NONEXISTENT", "Page Title")

        # Assert
        assert result is None
        pages_mixin.confluence.get_page_by_title.assert_called_once_with(
            space="NONEXISTENT", title="Page Title", expand="body.storage,version"
        )

    def test_get_page_by_title_page_not_found(self, pages_mixin):
        """Test getting a page that doesn't exist."""
        # Arrange
        pages_mixin.confluence.get_page_by_title.return_value = None

        # Act
        result = pages_mixin.get_page_by_title("PROJ", "Nonexistent Page")

        # Assert
        assert result is None
        pages_mixin.confluence.get_page_by_title.assert_called_once_with(
            space="PROJ", title="Nonexistent Page", expand="body.storage,version"
        )

    def test_get_page_by_title_error_handling(self, pages_mixin):
        """Test error handling in get_page_by_title."""
        # Arrange
        pages_mixin.confluence.get_page_by_title.side_effect = KeyError("Missing key")

        # Act
        result = pages_mixin.get_page_by_title("PROJ", "Page Title")

        # Assert
        assert result is None

    def test_get_space_pages(self, pages_mixin):
        """Test getting all pages from a space."""
        # Arrange
        space_key = "PROJ"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Act
        results = pages_mixin.get_space_pages(
            space_key, start=0, limit=10, convert_to_markdown=True
        )

        # Assert
        pages_mixin.confluence.get_all_pages_from_space.assert_called_once_with(
            space=space_key, start=0, limit=10, expand="body.storage"
        )

        # Verify results
        assert len(results) == 2  # Mock has 2 pages

        # Verify each result is a ConfluencePage
        for result in results:
            assert isinstance(result, ConfluencePage)
            assert result.content == "Processed Markdown"
            assert result.space is not None
            assert result.space.key == "PROJ"

        # Verify individual pages
        assert results[0].id == "123456789"  # First page ID from mock
        assert results[0].title == "Sample Research Paper Title"

        # Verify the second page
        assert results[1].id == "987654321"  # Second page ID from mock
        assert results[1].title == "Example Meeting Notes"

    def test_create_page_success(self, pages_mixin):
        """Test creating a new page."""
        # Arrange
        space_key = "PROJ"
        title = "New Test Page"
        body = "<p>Test content</p>"
        parent_id = "987654321"

        # Mock get_page_content to return a ConfluencePage
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(
                id="123456789",
                title=title,
                content="Page content",
                space={"key": space_key, "name": "Project"},
            ),
        ):
            # Act - specify is_markdown=False since we're directly providing storage format
            result = pages_mixin.create_page(
                space_key, title, body, parent_id, is_markdown=False
            )

            # Assert
            pages_mixin.confluence.create_page.assert_called_once_with(
                space=space_key,
                title=title,
                body=body,
                parent_id=parent_id,
                representation="storage",
            )

            # Verify result is a ConfluencePage
            assert isinstance(result, ConfluencePage)
            assert result.id == "123456789"
            assert result.title == title
            assert result.content == "Page content"

    def test_create_page_error(self, pages_mixin):
        """Test error handling when creating a page."""
        # Arrange
        pages_mixin.confluence.create_page.side_effect = Exception("API Error")

        # Act/Assert
        with pytest.raises(Exception, match="API Error"):
            pages_mixin.create_page("PROJ", "Test Page", "<p>Content</p>")

    def test_create_page_with_wiki_format(self, pages_mixin):
        """Test creating a new page with wiki markup format."""
        # Arrange
        space_key = "PROJ"
        title = "Wiki Format Test Page"
        wiki_body = "h1. This is a heading\n\n* Item 1\n* Item 2"

        # Mock get_page_content to return a ConfluencePage
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(
                id="wiki123",
                title=title,
                content="Wiki page content",
                space={"key": space_key, "name": "Project"},
            ),
        ):
            # Act - use wiki format
            result = pages_mixin.create_page(
                space_key,
                title,
                wiki_body,
                is_markdown=False,
                content_representation="wiki",
            )

            # Assert
            pages_mixin.confluence.create_page.assert_called_once_with(
                space=space_key,
                title=title,
                body=wiki_body,  # Should be passed as-is
                parent_id=None,
                representation="wiki",  # Should use wiki representation
            )

            # Verify no markdown conversion happened
            pages_mixin.preprocessor.markdown_to_confluence_storage.assert_not_called()

            # Verify result is a ConfluencePage
            assert isinstance(result, ConfluencePage)
            assert result.id == "wiki123"

    def test_update_page_success(self, pages_mixin):
        """Test updating an existing page."""
        # Arrange
        page_id = "987654321"
        title = "Updated Page"
        body = "<p>Updated content</p>"
        is_minor_edit = True
        version_comment = "Updated test"

        # Mock get_page_content to return a document
        mock_document = ConfluencePage(
            id=page_id,
            title=title,
            content="Updated content",
            space={"key": "PROJ", "name": "Project"},
            version={"number": 1},  # Add version information
        )
        with patch.object(pages_mixin, "get_page_content", return_value=mock_document):
            # Act - specify is_markdown=False since we're directly providing storage format
            result = pages_mixin.update_page(
                page_id,
                title,
                body,
                is_minor_edit=is_minor_edit,
                version_comment=version_comment,
                is_markdown=False,
            )

            # Assert
            # Verify update_page was called with the correct arguments
            # We now include type='page' and always_update=True parameters
            pages_mixin.confluence.update_page.assert_called_once_with(
                page_id=page_id,
                title=title,
                body=body,
                type="page",
                representation="storage",
                minor_edit=is_minor_edit,
                version_comment=version_comment,
                always_update=True,
            )

    def test_update_page_error(self, pages_mixin):
        """Test error handling when updating a page."""
        # Arrange
        pages_mixin.confluence.update_page.side_effect = Exception("API Error")

        # Act/Assert
        with pytest.raises(Exception, match="Failed to update page"):
            pages_mixin.update_page("987654321", "Test Page", "<p>Content</p>")

    def test_update_page_with_wiki_format(self, pages_mixin):
        """Test updating a page with wiki markup format."""
        # Arrange
        page_id = "wiki987"
        title = "Updated Wiki Page"
        wiki_body = "h1. Updated Heading\n\n||Header 1||Header 2||\n|Cell 1|Cell 2|"
        version_comment = "Wiki format update"

        # Mock get_page_content to return a document
        mock_document = ConfluencePage(
            id=page_id,
            title=title,
            content="Updated wiki content",
            space={"key": "PROJ", "name": "Project"},
            version={"number": 2},
        )
        with patch.object(pages_mixin, "get_page_content", return_value=mock_document):
            # Act - use wiki format
            result = pages_mixin.update_page(
                page_id,
                title,
                wiki_body,
                version_comment=version_comment,
                is_markdown=False,
                content_representation="wiki",
            )

            # Assert
            pages_mixin.confluence.update_page.assert_called_once_with(
                page_id=page_id,
                title=title,
                body=wiki_body,  # Should be passed as-is
                type="page",
                representation="wiki",  # Should use wiki representation
                minor_edit=False,
                version_comment=version_comment,
                always_update=True,
            )

            # Verify no markdown conversion happened
            pages_mixin.preprocessor.markdown_to_confluence_storage.assert_not_called()

            # Verify result is a ConfluencePage
            assert isinstance(result, ConfluencePage)
            assert result.id == page_id

    def test_delete_page_success(self, pages_mixin):
        """Test successfully deleting a page."""
        # Arrange
        page_id = "987654321"
        pages_mixin.confluence.remove_page.return_value = True

        # Act
        result = pages_mixin.delete_page(page_id)

        # Assert
        pages_mixin.confluence.remove_page.assert_called_once_with(page_id=page_id)
        assert result is True

    def test_delete_page_error(self, pages_mixin):
        """Test error handling when deleting a page."""
        # Arrange
        page_id = "987654321"
        pages_mixin.confluence.remove_page.side_effect = Exception("API Error")

        # Act/Assert
        with pytest.raises(Exception, match="Failed to delete page"):
            pages_mixin.delete_page(page_id)

    def test_get_page_children_success(self, pages_mixin):
        """Test successfully getting child pages."""
        # Arrange
        parent_id = "123456"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the response from get_page_child_by_type
        child_pages_data = {
            "results": [
                {
                    "id": "789012",
                    "title": "Child Page 1",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
                {
                    "id": "345678",
                    "title": "Child Page 2",
                    "space": {"key": "DEMO"},
                    "version": {"number": 3},
                },
            ]
        }
        pages_mixin.confluence.get_page_child_by_type.return_value = child_pages_data

        # Act
        results = pages_mixin.get_page_children(
            page_id=parent_id, limit=10, expand="version"
        )

        # Assert
        pages_mixin.confluence.get_page_child_by_type.assert_called_once_with(
            page_id=parent_id, type="page", start=0, limit=10, expand="version"
        )

        # Verify the results
        assert len(results) == 2
        assert isinstance(results[0], ConfluencePage)
        assert results[0].id == "789012"
        assert results[0].title == "Child Page 1"
        assert results[1].id == "345678"
        assert results[1].title == "Child Page 2"

    def test_get_page_children_with_content(self, pages_mixin):
        """Test getting child pages with content."""
        # Arrange
        parent_id = "123456"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the response with body content
        child_pages_data = {
            "results": [
                {
                    "id": "789012",
                    "title": "Child Page With Content",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                    "body": {"storage": {"value": "<p>This is some content</p>"}},
                }
            ]
        }
        pages_mixin.confluence.get_page_child_by_type.return_value = child_pages_data

        # Mock the preprocessor
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        results = pages_mixin.get_page_children(
            page_id=parent_id, expand="body.storage", convert_to_markdown=True
        )

        # Assert
        assert len(results) == 1
        assert results[0].content == "Processed Markdown"
        pages_mixin.preprocessor.process_html_content.assert_called_once_with(
            "<p>This is some content</p>",
            space_key="DEMO",
            confluence_client=pages_mixin.confluence,
        )

    def test_get_page_children_empty(self, pages_mixin):
        """Test getting child pages when there are none."""
        # Arrange
        parent_id = "123456"

        # Mock empty response
        pages_mixin.confluence.get_page_child_by_type.return_value = {"results": []}

        # Act
        results = pages_mixin.get_page_children(page_id=parent_id)

        # Assert
        assert len(results) == 0

    def test_get_page_children_error(self, pages_mixin):
        """Test error handling when getting child pages."""
        # Arrange
        parent_id = "123456"

        # Mock an exception
        pages_mixin.confluence.get_page_child_by_type.side_effect = Exception(
            "API Error"
        )

        # Act
        results = pages_mixin.get_page_children(page_id=parent_id)

        # Assert - should return empty list on error, not raise exception
        assert len(results) == 0

    def test_get_page_success(self, pages_mixin):
        """Test successful page retrieval."""
        # Setup
        page_id = "12345"
        page_data = {
            "id": page_id,
            "title": "Test Page",
            "body": {"storage": {"value": "<p>Test content</p>"}},
            "version": {"number": 1},
            "space": {"key": "TEST", "name": "Test Space"},
        }
        pages_mixin.confluence.get_page_by_id.return_value = page_data

        # Mock the preprocessor
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed content",
        )

        # Call the method
        result = pages_mixin.get_page_content(page_id)

        # Verify the API call
        pages_mixin.confluence.get_page_by_id.assert_called_once_with(
            page_id=page_id, expand="body.storage,version,space,children.attachment"
        )

        # Verify the result
        assert result.id == page_id
        assert result.title == "Test Page"
        assert result.content == "Processed content"
        assert (
            result.version.number == 1
        )  # Compare version number instead of the whole object
        assert result.space.key == "TEST"
        assert result.space.name == "Test Space"

    def test_create_page_with_markdown(self, pages_mixin):
        """Test creating a new page with markdown content."""
        # Arrange
        space_key = "PROJ"
        title = "New Test Page"
        markdown_body = "# Test Heading\n\nThis is *markdown* content."
        parent_id = "987654321"
        storage_format = (
            "<h1>Test Heading</h1><p>This is <em>markdown</em> content.</p>"
        )

        # Mock the markdown conversion
        pages_mixin.preprocessor.markdown_to_confluence_storage.return_value = (
            storage_format
        )

        # Mock get_page_content to return a ConfluencePage
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(
                id="123456789",
                title=title,
                content="Converted content",
                space={"key": space_key, "name": "Project"},
            ),
        ):
            # Act
            result = pages_mixin.create_page(
                space_key=space_key,
                title=title,
                body=markdown_body,
                parent_id=parent_id,
                is_markdown=True,
            )

            # Assert
            # Verify markdown was converted
            pages_mixin.preprocessor.markdown_to_confluence_storage.assert_called_once_with(
                markdown_body, enable_heading_anchors=False
            )

            # Verify create_page was called with the converted content
            pages_mixin.confluence.create_page.assert_called_once_with(
                space=space_key,
                title=title,
                body=storage_format,
                parent_id=parent_id,
                representation="storage",
            )

            # Verify result
            assert isinstance(result, ConfluencePage)
            assert result.id == "123456789"
            assert result.title == title

    def test_create_page_with_storage_format(self, pages_mixin):
        """Test creating a page with pre-converted storage format content."""
        # Arrange
        space_key = "PROJ"
        title = "New Test Page"
        storage_body = "<p>Already in storage format</p>"

        # Mock get_page_content
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(id="123456789", title=title),
        ):
            # Act
            result = pages_mixin.create_page(
                space_key=space_key, title=title, body=storage_body, is_markdown=False
            )

            # Assert
            # Verify conversion was not called
            pages_mixin.preprocessor.markdown_to_confluence_storage.assert_not_called()

            # Verify create_page was called with the original content
            pages_mixin.confluence.create_page.assert_called_once_with(
                space=space_key,
                title=title,
                body=storage_body,
                parent_id=None,
                representation="storage",
            )

    def test_update_page_with_markdown(self, pages_mixin):
        """Test updating a page with markdown content."""
        # Arrange
        page_id = "987654321"
        title = "Updated Page"
        markdown_body = "# Updated Content\n\nThis is *updated* content."
        storage_format = (
            "<h1>Updated Content</h1><p>This is <em>updated</em> content.</p>"
        )

        # Mock the markdown conversion
        pages_mixin.preprocessor.markdown_to_confluence_storage.return_value = (
            storage_format
        )

        # Mock get_page_content
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(
                id=page_id,
                title=title,
                content="Updated content",
                space={"key": "PROJ", "name": "Project"},
            ),
        ):
            # Act
            result = pages_mixin.update_page(
                page_id=page_id,
                title=title,
                body=markdown_body,
                is_minor_edit=True,
                version_comment="Updated test",
                is_markdown=True,
            )

            # Assert
            # Verify markdown was converted
            pages_mixin.preprocessor.markdown_to_confluence_storage.assert_called_once_with(
                markdown_body, enable_heading_anchors=False
            )

            # Verify update_page was called with the converted content
            pages_mixin.confluence.update_page.assert_called_once_with(
                page_id=page_id,
                title=title,
                body=storage_format,
                type="page",
                representation="storage",
                minor_edit=True,
                version_comment="Updated test",
                always_update=True,
            )

    def test_update_page_with_parent_id(self, pages_mixin):
        """Test updating a page and changing its parent."""
        # Arrange
        page_id = "987654321"
        title = "Updated Page"
        body = "<p>Updated content</p>"
        parent_id = "123456789"
        is_minor_edit = False
        version_comment = "Parent changed"

        # Mock get_page_content to return a document
        mock_document = ConfluencePage(
            id=page_id,
            title=title,
            content="Updated content",
            space={"key": "PROJ", "name": "Project"},
            version={"number": 2},
        )
        with patch.object(pages_mixin, "get_page_content", return_value=mock_document):
            # Act
            result = pages_mixin.update_page(
                page_id=page_id,
                title=title,
                body=body,
                is_minor_edit=is_minor_edit,
                version_comment=version_comment,
                is_markdown=False,
                parent_id=parent_id,
            )

            # Assert
            pages_mixin.confluence.update_page.assert_called_once_with(
                page_id=page_id,
                title=title,
                body=body,
                type="page",
                representation="storage",
                minor_edit=is_minor_edit,
                version_comment=version_comment,
                always_update=True,
                parent_id=parent_id,
            )
            assert result.id == page_id
            assert result.title == title
            assert result.version.number == 2

    def test_non_oauth_still_uses_v1_api(self, pages_mixin):
        """Test that non-OAuth authentication still uses v1 API."""
        # This test ensures backward compatibility for API token/basic auth
        # Arrange
        space_key = "PROJ"
        title = "New V1 Test Page"
        body = "<p>Test content for V1</p>"

        # Mock get_page_content to return a ConfluencePage
        with patch.object(
            pages_mixin,
            "get_page_content",
            return_value=ConfluencePage(
                id="v1_123456789",
                title=title,
                content="V1 page content",
                space={"key": space_key, "name": "Project"},
            ),
        ):
            # Act
            result = pages_mixin.create_page(space_key, title, body, is_markdown=False)

            # Assert that v1 API was used
            pages_mixin.confluence.create_page.assert_called_once_with(
                space=space_key,
                title=title,
                body=body,
                parent_id=None,
                representation="storage",
            )

            # Verify result is a ConfluencePage
            assert isinstance(result, ConfluencePage)
            assert result.id == "v1_123456789"
            assert result.title == title

    def test_get_page_siblings_with_parent(self, pages_mixin):
        """Test getting siblings for a page that has a parent."""
        # Arrange
        page_id = "123456"
        parent_id = "789012"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the page with ancestors (has parent)
        page_data = {
            "id": page_id,
            "title": "Target Page",
            "space": {"key": "DEMO"},
            "ancestors": [{"id": parent_id, "title": "Parent Page"}],
        }
        pages_mixin.confluence.get_page_by_id.return_value = page_data

        # Mock get_page_children to return siblings
        sibling_pages_data = {
            "results": [
                {
                    "id": page_id,
                    "title": "Target Page",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
                {
                    "id": "456789",
                    "title": "Sibling Page 1",
                    "space": {"key": "DEMO"},
                    "version": {"number": 2},
                },
                {
                    "id": "654321",
                    "title": "Sibling Page 2",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
            ]
        }
        pages_mixin.confluence.get_page_child_by_type.return_value = sibling_pages_data

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id, include_self=False)

        # Assert
        pages_mixin.confluence.get_page_by_id.assert_called_once_with(
            page_id=page_id, expand="ancestors,space"
        )
        pages_mixin.confluence.get_page_child_by_type.assert_called_once_with(
            page_id=parent_id, type="page", start=0, limit=200, expand="version"
        )

        # Should exclude the target page itself
        assert len(result) == 2
        assert result[0].id == "456789"
        assert result[0].title == "Sibling Page 1"
        assert result[1].id == "654321"
        assert result[1].title == "Sibling Page 2"

    def test_get_page_siblings_with_parent_include_self(self, pages_mixin):
        """Test getting siblings for a page that has a parent, including self."""
        # Arrange
        page_id = "123456"
        parent_id = "789012"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the page with ancestors (has parent)
        page_data = {
            "id": page_id,
            "title": "Target Page",
            "space": {"key": "DEMO"},
            "ancestors": [{"id": parent_id, "title": "Parent Page"}],
        }
        pages_mixin.confluence.get_page_by_id.return_value = page_data

        # Mock get_page_children to return siblings
        sibling_pages_data = {
            "results": [
                {
                    "id": page_id,
                    "title": "Target Page",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
                {
                    "id": "456789",
                    "title": "Sibling Page 1",
                    "space": {"key": "DEMO"},
                    "version": {"number": 2},
                },
            ]
        }
        pages_mixin.confluence.get_page_child_by_type.return_value = sibling_pages_data

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id, include_self=True)

        # Assert - should include the target page itself
        assert len(result) == 2
        assert result[0].id == page_id
        assert result[0].title == "Target Page"
        assert result[1].id == "456789"
        assert result[1].title == "Sibling Page 1"

    def test_get_page_siblings_root_page(self, pages_mixin):
        """Test getting siblings for a root page (no parent)."""
        # Arrange
        page_id = "123456"
        space_key = "DEMO"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the page without ancestors (root page)
        page_data = {
            "id": page_id,
            "title": "Root Page",
            "space": {"key": space_key},
            "ancestors": [],
        }
        pages_mixin.confluence.get_page_by_id.return_value = page_data

        # Mock get_all_pages_from_space to return all pages including root pages
        all_space_pages = [
            {
                "id": page_id,
                "title": "Root Page",
                "space": {"key": space_key},
                "ancestors": [],  # This is a root page
                "version": {"number": 1},
            },
            {
                "id": "789012",
                "title": "Root Sibling 1",
                "space": {"key": space_key},
                "ancestors": [],  # This is also a root page
                "version": {"number": 1},
            },
            {
                "id": "345678",
                "title": "Root Sibling 2",
                "space": {"key": space_key},
                "ancestors": [],  # This is also a root page
                "version": {"number": 1},
            },
            {
                "id": "999999",
                "title": "Child Page",
                "space": {"key": space_key},
                "ancestors": [
                    {"id": "111111"}
                ],  # This has a parent, so not a root page
                "version": {"number": 1},
            },
        ]
        pages_mixin.confluence.get_all_pages_from_space.return_value = all_space_pages

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id, include_self=False)

        # Assert
        pages_mixin.confluence.get_page_by_id.assert_called_once_with(
            page_id=page_id, expand="ancestors,space"
        )
        pages_mixin.confluence.get_all_pages_from_space.assert_called_once_with(
            space=space_key, start=0, limit=200, expand="ancestors,version"
        )

        # Should return siblings without the current page (only root pages, excluding current)
        assert len(result) == 2
        assert result[0].id == "789012"
        assert result[0].title == "Root Sibling 1"
        assert result[1].id == "345678"
        assert result[1].title == "Root Sibling 2"

    def test_get_page_siblings_no_siblings(self, pages_mixin):
        """Test getting siblings when page has no siblings."""
        # Arrange
        page_id = "123456"
        parent_id = "789012"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock the page with ancestors (has parent)
        page_data = {
            "id": page_id,
            "title": "Only Child",
            "space": {"key": "DEMO"},
            "ancestors": [{"id": parent_id, "title": "Parent Page"}],
        }
        pages_mixin.confluence.get_page_by_id.return_value = page_data

        # Mock get_page_children to return only the target page
        sibling_pages_data = {
            "results": [
                {
                    "id": page_id,
                    "title": "Only Child",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                }
            ]
        }
        pages_mixin.confluence.get_page_child_by_type.return_value = sibling_pages_data

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id, include_self=False)

        # Assert - should return empty list since only child and include_self=False
        assert len(result) == 0

    def test_get_page_siblings_invalid_page(self, pages_mixin):
        """Test getting siblings for a non-existent page."""
        # Arrange
        page_id = "nonexistent"
        pages_mixin.confluence.get_page_by_id.return_value = None

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id)

        # Assert - should return empty list for non-existent page
        assert len(result) == 0

    def test_get_page_siblings_error_handling(self, pages_mixin):
        """Test error handling in get_page_siblings."""
        # Arrange
        page_id = "123456"
        pages_mixin.confluence.get_page_by_id.side_effect = Exception("API Error")

        # Act
        result = pages_mixin.get_page_siblings(page_id=page_id)

        # Assert - should return empty list on error, not raise exception
        assert len(result) == 0


class TestPagesOAuthMixin:
    """Tests for PagesMixin with OAuth authentication."""

    @pytest.fixture
    def oauth_pages_mixin(self, oauth_confluence_client):
        """Create a PagesMixin instance for OAuth testing."""
        # PagesMixin inherits from ConfluenceClient, so we need to create it properly
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceClient.__init__"
        ) as mock_init:
            mock_init.return_value = None
            mixin = PagesMixin()
            # Copy the necessary attributes from our mocked client
            mixin.confluence = oauth_confluence_client.confluence
            mixin.config = oauth_confluence_client.config
            mixin.preprocessor = oauth_confluence_client.preprocessor
            return mixin

    def test_create_page_oauth_uses_v2_api(self, oauth_pages_mixin):
        """Test that OAuth authentication uses v2 API for creating pages."""
        # Arrange
        space_key = "PROJ"
        title = "New OAuth Test Page"
        body = "<p>Test content for OAuth</p>"
        parent_id = "987654321"

        # Mock the v2 adapter
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceV2Adapter"
        ) as mock_v2_adapter_class:
            mock_v2_adapter = MagicMock()
            mock_v2_adapter_class.return_value = mock_v2_adapter
            mock_v2_adapter.create_page.return_value = {
                "id": "oauth_123456789",
                "title": title,
            }

            # Mock get_page_content to return a ConfluencePage
            with patch.object(
                oauth_pages_mixin,
                "get_page_content",
                return_value=ConfluencePage(
                    id="oauth_123456789",
                    title=title,
                    content="OAuth page content",
                    space={"key": space_key, "name": "Project"},
                ),
            ):
                # Act - specify is_markdown=False since we're directly providing storage format
                result = oauth_pages_mixin.create_page(
                    space_key, title, body, parent_id, is_markdown=False
                )

                # Assert that v2 API was used instead of v1
                mock_v2_adapter.create_page.assert_called_once_with(
                    space_key=space_key,
                    title=title,
                    body=body,
                    parent_id=parent_id,
                    representation="storage",
                )

                # Verify v1 API was NOT called
                oauth_pages_mixin.confluence.create_page.assert_not_called()

                # Verify result is a ConfluencePage
                assert isinstance(result, ConfluencePage)
                assert result.id == "oauth_123456789"

    def test_create_page_oauth_with_wiki_format(self, oauth_pages_mixin):
        """Test that OAuth authentication uses v2 API for creating pages with wiki format."""
        # Arrange
        space_key = "PROJ"
        title = "OAuth Wiki Test Page"
        wiki_body = "h1. OAuth Wiki Test\n\n* Item 1\n* Item 2"

        # Mock the v2 adapter
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceV2Adapter"
        ) as mock_v2_adapter_class:
            mock_v2_adapter = MagicMock()
            mock_v2_adapter_class.return_value = mock_v2_adapter
            mock_v2_adapter.create_page.return_value = {
                "id": "oauth_wiki_123",
                "title": title,
            }

            # Mock get_page_content to return a ConfluencePage
            with patch.object(
                oauth_pages_mixin,
                "get_page_content",
                return_value=ConfluencePage(
                    id="oauth_wiki_123",
                    title=title,
                    content="OAuth wiki page content",
                    space={"key": space_key, "name": "Project"},
                ),
            ):
                # Act - use wiki format
                result = oauth_pages_mixin.create_page(
                    space_key,
                    title,
                    wiki_body,
                    is_markdown=False,
                    content_representation="wiki",
                )

                # Assert that v2 API was used with wiki representation
                mock_v2_adapter.create_page.assert_called_once_with(
                    space_key=space_key,
                    title=title,
                    body=wiki_body,
                    parent_id=None,
                    representation="wiki",
                )

                # Verify v1 API was NOT called
                oauth_pages_mixin.confluence.create_page.assert_not_called()

                # Verify no markdown conversion happened
                oauth_pages_mixin.preprocessor.markdown_to_confluence_storage.assert_not_called()

                # Verify result is a ConfluencePage
                assert isinstance(result, ConfluencePage)
                assert result.id == "oauth_wiki_123"
                assert result.title == title

    def test_update_page_oauth_uses_v2_api(self, oauth_pages_mixin):
        """Test that OAuth authentication uses v2 API for updating pages."""
        # Arrange
        page_id = "oauth_987654321"
        title = "Updated OAuth Test Page"
        body = "<p>Updated test content for OAuth</p>"
        version_comment = "OAuth update test"

        # Mock the v2 adapter
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceV2Adapter"
        ) as mock_v2_adapter_class:
            mock_v2_adapter = MagicMock()
            mock_v2_adapter_class.return_value = mock_v2_adapter
            mock_v2_adapter.update_page.return_value = {
                "id": page_id,
                "title": title,
            }

            # Mock get_page_content to return a ConfluencePage
            with patch.object(
                oauth_pages_mixin,
                "get_page_content",
                return_value=ConfluencePage(
                    id=page_id,
                    title=title,
                    content="Updated OAuth page content",
                    version={"number": 2},
                ),
            ):
                # Act - specify is_markdown=False since we're directly providing storage format
                result = oauth_pages_mixin.update_page(
                    page_id,
                    title,
                    body,
                    is_markdown=False,
                    version_comment=version_comment,
                )

                # Assert that v2 API was used instead of v1
                mock_v2_adapter.update_page.assert_called_once_with(
                    page_id=page_id,
                    title=title,
                    body=body,
                    representation="storage",
                    version_comment=version_comment,
                )

                # Verify v1 API was NOT called
                oauth_pages_mixin.confluence.update_page.assert_not_called()

                # Verify result is a ConfluencePage
                assert isinstance(result, ConfluencePage)
                assert result.id == page_id
                assert result.title == title

    def test_get_page_content_oauth_uses_v2_api(self, oauth_pages_mixin):
        """Test that OAuth authentication uses v2 API for getting page content."""
        # Arrange
        page_id = "oauth_get_123"

        # Mock the v2 adapter
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceV2Adapter"
        ) as mock_v2_adapter_class:
            mock_v2_adapter = MagicMock()
            mock_v2_adapter_class.return_value = mock_v2_adapter

            # Mock v2 API response
            mock_v2_adapter.get_page.return_value = {
                "id": page_id,
                "title": "OAuth Test Page",
                "body": {"storage": {"value": "<p>OAuth page content</p>"}},
                "space": {"key": "PROJ", "name": "Project"},
                "version": {"number": 3},
            }

            # Mock the preprocessor
            oauth_pages_mixin.preprocessor.process_html_content.return_value = (
                "<p>Processed HTML</p>",
                "Processed OAuth content",
            )

            # Act
            result = oauth_pages_mixin.get_page_content(
                page_id, convert_to_markdown=True
            )

            # Assert that v2 API was used instead of v1
            mock_v2_adapter.get_page.assert_called_once_with(
                page_id=page_id, expand="body.storage,version,space,children.attachment"
            )

            # Verify v1 API was NOT called
            oauth_pages_mixin.confluence.get_page_by_id.assert_not_called()

            # Verify the preprocessor was called
            oauth_pages_mixin.preprocessor.process_html_content.assert_called_once_with(
                "<p>OAuth page content</p>",
                space_key="PROJ",
                confluence_client=oauth_pages_mixin.confluence,
            )

            # Verify result is a ConfluencePage with correct data
            assert isinstance(result, ConfluencePage)
            assert result.id == page_id
            assert result.title == "OAuth Test Page"
            assert result.content == "Processed OAuth content"
            assert result.space.key == "PROJ"
            assert result.version.number == 3

    def test_delete_page_oauth_uses_v2_api(self, oauth_pages_mixin):
        """Test that OAuth authentication uses v2 API for deleting pages."""
        # Arrange
        page_id = "oauth_delete_123"

        # Mock the v2 adapter
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceV2Adapter"
        ) as mock_v2_adapter_class:
            mock_v2_adapter = MagicMock()
            mock_v2_adapter_class.return_value = mock_v2_adapter
            mock_v2_adapter.delete_page.return_value = True

            # Act
            result = oauth_pages_mixin.delete_page(page_id)

            # Assert that v2 API was used instead of v1
            mock_v2_adapter.delete_page.assert_called_once_with(page_id=page_id)

            # Verify v1 API was NOT called
            oauth_pages_mixin.confluence.remove_page.assert_not_called()

            # Verify result
            assert result is True


class TestGetPageBreadcrumbs:
    """Tests for the get_page_breadcrumbs method."""

    @pytest.fixture
    def pages_mixin(self, confluence_client):
        """Create a PagesMixin instance for testing."""
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceClient.__init__"
        ) as mock_init:
            mock_init.return_value = None
            mixin = PagesMixin()
            mixin.confluence = confluence_client.confluence
            mixin.config = confluence_client.config
            mixin.preprocessor = confluence_client.preprocessor
            return mixin

    def test_get_page_breadcrumbs_basic(self, pages_mixin):
        """Test basic breadcrumb functionality."""
        # Arrange
        page_id = "123456"

        # Mock ancestors response (returned in closest-to-farthest order)
        ancestors_data = [
            {
                "id": "parent123",
                "title": "Parent Page",
                "space": {"key": "PROJ", "name": "Project Space"},
                "type": "page",
                "status": "current",
            },
            {
                "id": "grandparent123",
                "title": "Grandparent Page",
                "space": {"key": "PROJ", "name": "Project Space"},
                "type": "page",
                "status": "current",
            },
        ]
        pages_mixin.confluence.get_page_ancestors.return_value = ancestors_data

        # Mock current page response
        current_page_data = {
            "id": page_id,
            "title": "Current Page",
            "space": {"key": "PROJ", "name": "Project Space"},
            "body": {"storage": {"value": "<p>Current page content</p>"}},
            "version": {"number": 1},
        }
        pages_mixin.confluence.get_page_by_id.return_value = current_page_data
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_breadcrumbs(page_id, include_content=False)

        # Assert
        assert len(result) == 3  # grandparent + parent + current

        # Verify breadcrumb order (root → parent → current)
        assert result[0].id == "grandparent123"
        assert result[0].title == "Grandparent Page"
        assert result[1].id == "parent123"
        assert result[1].title == "Parent Page"
        assert result[2].id == page_id
        assert result[2].title == "Current Page"

        # Verify all are ConfluencePage instances
        for page in result:
            assert isinstance(page, ConfluencePage)

    def test_get_page_breadcrumbs_with_content(self, pages_mixin):
        """Test breadcrumbs with content included."""
        # Arrange
        page_id = "123456"

        # Mock ancestors response
        ancestors_data = [
            {
                "id": "parent123",
                "title": "Parent Page",
                "space": {"key": "PROJ", "name": "Project Space"},
                "type": "page",
                "status": "current",
            }
        ]
        pages_mixin.confluence.get_page_ancestors.return_value = ancestors_data

        # Mock current page response with content
        current_page_data = {
            "id": page_id,
            "title": "Current Page",
            "space": {"key": "PROJ", "name": "Project Space"},
            "body": {"storage": {"value": "<p>Current page content</p>"}},
            "version": {"number": 1},
        }
        pages_mixin.confluence.get_page_by_id.return_value = current_page_data
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_breadcrumbs(page_id, include_content=True)

        # Assert
        assert len(result) == 2  # parent + current

        # Verify content is included for current page
        assert result[1].content == "Processed Markdown"

        # Verify get_page_content was called with include_content=True
        pages_mixin.confluence.get_page_by_id.assert_called_with(
            page_id=page_id, expand="body.storage,version,space,children.attachment"
        )

    def test_get_page_breadcrumbs_root_page(self, pages_mixin):
        """Test breadcrumbs for a root page (no ancestors)."""
        # Arrange
        page_id = "123456"

        # Mock empty ancestors response
        pages_mixin.confluence.get_page_ancestors.return_value = []

        # Mock current page response
        current_page_data = {
            "id": page_id,
            "title": "Root Page",
            "space": {"key": "PROJ", "name": "Project Space"},
            "body": {"storage": {"value": "<p>Root page content</p>"}},
            "version": {"number": 1},
        }
        pages_mixin.confluence.get_page_by_id.return_value = current_page_data
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_breadcrumbs(page_id)

        # Assert
        assert len(result) == 1  # Only current page
        assert result[0].id == page_id
        assert result[0].title == "Root Page"

    def test_get_page_breadcrumbs_deep_hierarchy(self, pages_mixin):
        """Test breadcrumbs for a deeply nested page."""
        # Arrange
        page_id = "123456"

        # Mock deep ancestors response (5 levels)
        ancestors_data = [
            {
                "id": "level1",
                "title": "Level 1",
                "space": {"key": "PROJ"},
                "type": "page",
                "status": "current",
            },
            {
                "id": "level2",
                "title": "Level 2",
                "space": {"key": "PROJ"},
                "type": "page",
                "status": "current",
            },
            {
                "id": "level3",
                "title": "Level 3",
                "space": {"key": "PROJ"},
                "type": "page",
                "status": "current",
            },
            {
                "id": "level4",
                "title": "Level 4",
                "space": {"key": "PROJ"},
                "type": "page",
                "status": "current",
            },
            {
                "id": "level5",
                "title": "Level 5",
                "space": {"key": "PROJ"},
                "type": "page",
                "status": "current",
            },
        ]
        pages_mixin.confluence.get_page_ancestors.return_value = ancestors_data

        # Mock current page response
        current_page_data = {
            "id": page_id,
            "title": "Deep Page",
            "space": {"key": "PROJ", "name": "Project Space"},
            "body": {"storage": {"value": "<p>Deep page content</p>"}},
            "version": {"number": 1},
        }
        pages_mixin.confluence.get_page_by_id.return_value = current_page_data
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_breadcrumbs(page_id)

        # Assert
        assert len(result) == 6  # 5 ancestors + current

        # Verify breadcrumb order (root → ... → current)
        assert result[0].id == "level5"  # Topmost ancestor
        assert result[1].id == "level4"
        assert result[2].id == "level3"
        assert result[3].id == "level2"
        assert result[4].id == "level1"  # Immediate parent
        assert result[5].id == page_id  # Current page

    def test_get_page_breadcrumbs_ancestors_error(self, pages_mixin):
        """Test breadcrumbs when ancestors retrieval fails."""
        # Arrange
        page_id = "123456"

        # Mock ancestors error - should return empty list
        pages_mixin.confluence.get_page_ancestors.side_effect = Exception("API Error")

        # Mock current page response
        current_page_data = {
            "id": page_id,
            "title": "Current Page",
            "space": {"key": "PROJ", "name": "Project Space"},
            "body": {"storage": {"value": "<p>Current page content</p>"}},
            "version": {"number": 1},
        }
        pages_mixin.confluence.get_page_by_id.return_value = current_page_data
        pages_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = pages_mixin.get_page_breadcrumbs(page_id)

        # Assert - should still return current page even if ancestors fail
        assert len(result) == 1
        assert result[0].id == page_id
        assert result[0].title == "Current Page"

    def test_get_page_breadcrumbs_current_page_error(self, pages_mixin):
        """Test breadcrumbs when current page retrieval fails."""
        # Arrange
        page_id = "nonexistent"

        # Mock ancestors response
        pages_mixin.confluence.get_page_ancestors.return_value = []

        # Mock current page error
        pages_mixin.confluence.get_page_by_id.side_effect = Exception("Page not found")

        # Act & Assert - should raise exception when current page fails
        with pytest.raises(Exception, match="Page not found"):
            pages_mixin.get_page_breadcrumbs(page_id)


class TestGetPageDescendants:
    """Tests for the get_page_descendants method."""

    @pytest.fixture
    def pages_mixin(self, confluence_client):
        """Create a PagesMixin instance for testing."""
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceClient.__init__"
        ) as mock_init:
            mock_init.return_value = None
            mixin = PagesMixin()
            mixin.confluence = confluence_client.confluence
            mixin.config = confluence_client.config
            mixin.preprocessor = confluence_client.preprocessor
            return mixin

    def test_get_page_descendants_single_level(self, pages_mixin):
        """Test getting descendants with max_depth=1 (direct children only)."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock direct children response
        children_data = {
            "results": [
                {
                    "id": "child1",
                    "title": "Child Page 1",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
                {
                    "id": "child2",
                    "title": "Child Page 2",
                    "space": {"key": "DEMO"},
                    "version": {"number": 1},
                },
            ]
        }

        # Mock get_page_children to return children for root, empty for children
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                child_pages = []
                for child_data in children_data["results"]:
                    page_model = ConfluencePage.from_api_response(
                        child_data,
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                    child_pages.append(page_model)
                return child_pages
            return []  # No grandchildren

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=1)

            # Assert
            assert len(result) == 2
            assert result[0].id == "child1"
            assert result[0].title == "Child Page 1"
            assert result[1].id == "child2"
            assert result[1].title == "Child Page 2"

    def test_get_page_descendants_multi_level(self, pages_mixin):
        """Test getting descendants with multiple levels (depth=2)."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock hierarchical structure: root -> child1, child2 -> grandchild1, grandchild2
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                # Root has 2 children
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "child1",
                            "title": "Child Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    ),
                    ConfluencePage.from_api_response(
                        {
                            "id": "child2",
                            "title": "Child Page 2",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    ),
                ]
            elif page_id == "child1":
                # Child1 has 1 grandchild
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "grandchild1",
                            "title": "Grandchild Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            elif page_id == "child2":
                # Child2 has 1 grandchild
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "grandchild2",
                            "title": "Grandchild Page 2",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            return []  # No more children

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=2)

            # Assert
            assert len(result) == 4
            # Children should come first (breadth-first)
            assert result[0].id == "child1"
            assert result[1].id == "child2"
            # Then grandchildren
            assert result[2].id == "grandchild1"
            assert result[3].id == "grandchild2"

    def test_get_page_descendants_unlimited_depth(self, pages_mixin):
        """Test getting descendants with unlimited depth."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock deep hierarchy: root -> child -> grandchild -> great-grandchild
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "child1",
                            "title": "Child Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            elif page_id == "child1":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "grandchild1",
                            "title": "Grandchild Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            elif page_id == "grandchild1":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "greatgrandchild1",
                            "title": "Great-Grandchild Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            return []

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=None)

            # Assert
            assert len(result) == 3
            assert result[0].id == "child1"
            assert result[1].id == "grandchild1"
            assert result[2].id == "greatgrandchild1"

    def test_get_page_descendants_with_content(self, pages_mixin):
        """Test getting descendants with content included."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock children with content
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                child_page = ConfluencePage.from_api_response(
                    {
                        "id": "child1",
                        "title": "Child with Content",
                        "space": {"key": "DEMO"},
                        "version": {"number": 1},
                        "body": {"storage": {"value": "<p>Child content</p>"}},
                    },
                    base_url=pages_mixin.config.url,
                    include_body=True,
                    content_override="Processed child content",
                    content_format="markdown",
                )
                return [child_page]
            return []

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(
                page_id, max_depth=1, include_content=True
            )

            # Assert
            assert len(result) == 1
            assert result[0].id == "child1"
            assert result[0].content == "Processed child content"

    def test_get_page_descendants_no_children(self, pages_mixin):
        """Test getting descendants for a page with no children."""
        # Arrange
        page_id = "leaf123"

        with patch.object(pages_mixin, "get_page_children", return_value=[]):
            # Act
            result = pages_mixin.get_page_descendants(page_id)

            # Assert
            assert len(result) == 0

    def test_get_page_descendants_limit_enforcement(self, pages_mixin):
        """Test that the limit parameter is enforced."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock many children
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                children = []
                for i in range(10):  # Create 10 children
                    child = ConfluencePage.from_api_response(
                        {
                            "id": f"child{i}",
                            "title": f"Child Page {i}",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                    children.append(child)
                return children
            return []

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act - limit to 5 descendants
            result = pages_mixin.get_page_descendants(page_id, limit=5)

            # Assert
            assert len(result) == 5
            for i in range(5):
                assert result[i].id == f"child{i}"

    def test_get_page_descendants_depth_zero(self, pages_mixin):
        """Test getting descendants with max_depth=0 (no descendants)."""
        # Arrange
        page_id = "root123"

        with patch.object(pages_mixin, "get_page_children") as mock_get_children:
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=0)

            # Assert
            assert len(result) == 0
            mock_get_children.assert_not_called()  # Should not fetch children at all

    def test_get_page_descendants_circular_reference_protection(self, pages_mixin):
        """Test protection against circular references."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock circular reference: root -> child1 -> child2 -> root (would be infinite)
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "child1",
                            "title": "Child Page 1",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            elif page_id == "child1":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "child2",
                            "title": "Child Page 2",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            elif page_id == "child2":
                # This would create a circular reference back to root
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "root123",  # Circular reference!
                            "title": "Root Page (circular)",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    )
                ]
            return []

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=None)

            # Assert - should stop at child2, not continue infinitely
            assert len(result) == 2
            assert result[0].id == "child1"
            assert result[1].id == "child2"

    def test_get_page_descendants_error_handling(self, pages_mixin):
        """Test error handling when children fetching fails."""
        # Arrange
        page_id = "root123"

        with patch.object(
            pages_mixin, "get_page_children", side_effect=Exception("API Error")
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id)

            # Assert - should return empty list on error, not raise exception
            assert len(result) == 0

    def test_get_page_descendants_partial_error(self, pages_mixin):
        """Test handling when some children succeed and others fail."""
        # Arrange
        page_id = "root123"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock mixed success/failure
        def mock_get_children(page_id, **kwargs):
            if page_id == "root123":
                return [
                    ConfluencePage.from_api_response(
                        {
                            "id": "child1",
                            "title": "Good Child",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    ),
                    ConfluencePage.from_api_response(
                        {
                            "id": "child2",
                            "title": "Bad Child",
                            "space": {"key": "DEMO"},
                            "version": {"number": 1},
                        },
                        base_url=pages_mixin.config.url,
                        include_body=False,
                    ),
                ]
            elif page_id == "child1":
                return []  # No grandchildren
            elif page_id == "child2":
                raise Exception("Failed to get children for child2")
            return []

        with patch.object(
            pages_mixin, "get_page_children", side_effect=mock_get_children
        ):
            # Act
            result = pages_mixin.get_page_descendants(page_id, max_depth=2)

            # Assert - should return partial results despite one failure
            assert len(result) == 2
            assert result[0].id == "child1"
            assert result[1].id == "child2"

    def test_get_page_descendants_invalid_parameters(self, pages_mixin):
        """Test parameter validation and defaults."""
        # Arrange
        page_id = "root123"

        with patch.object(pages_mixin, "get_page_children", return_value=[]):
            # Act & Assert - invalid limit should use default
            result1 = pages_mixin.get_page_descendants(page_id, limit=0)
            assert len(result1) == 0

            result2 = pages_mixin.get_page_descendants(page_id, limit=1000)
            assert len(result2) == 0

            # Invalid max_depth should use None (unlimited)
            result3 = pages_mixin.get_page_descendants(page_id, max_depth=-1)
            assert len(result3) == 0


class TestGetPageByPath:
    """Tests for the get_page_by_path method."""

    @pytest.fixture
    def pages_mixin(self, confluence_client):
        """Create a PagesMixin instance for testing."""
        with patch(
            "mcp_atlassian.confluence.pages.ConfluenceClient.__init__"
        ) as mock_init:
            mock_init.return_value = None
            mixin = PagesMixin()
            mixin.confluence = confluence_client.confluence
            mixin.config = confluence_client.config
            mixin.preprocessor = confluence_client.preprocessor
            return mixin

    def test_get_page_by_path_single_level(self, pages_mixin):
        """Test getting a page with a single-level path (root page)."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages response
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "root1",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            ),
            ConfluencePage.from_api_response(
                {
                    "id": "root2",
                    "title": "Meetings",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            ),
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "root1",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            },
            {
                "id": "root2",
                "title": "Meetings",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            },
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            # Act
            result = pages_mixin.get_page_by_path(space_key, path)

            # Assert
            assert result is not None
            assert result.id == "root1"
            assert result.title == "Documentation"
            pages_mixin.confluence.get_all_pages_from_space.assert_called_once_with(
                space=space_key, start=0, limit=200, expand="ancestors,version"
            )

    def test_get_page_by_path_multi_level(self, pages_mixin):
        """Test getting a page with a multi-level path."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation/API/REST"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages response
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock API children response
        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock REST children response
        rest_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "rest_page",
                    "title": "REST",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(pages_mixin, "get_page_children") as mock_get_children:
                # Configure children responses based on page ID
                def mock_children_side_effect(page_id, **kwargs):
                    if page_id == "doc_root":
                        return api_children
                    elif page_id == "api_page":
                        return rest_children
                    return []

                mock_get_children.side_effect = mock_children_side_effect

                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is not None
                assert result.id == "rest_page"
                assert result.title == "REST"

                # Verify the navigation calls
                assert mock_get_children.call_count == 2
                mock_get_children.assert_any_call(
                    page_id="doc_root",
                    start=0,
                    limit=200,
                    expand="version",
                    convert_to_markdown=False,
                )
                mock_get_children.assert_any_call(
                    page_id="api_page",
                    start=0,
                    limit=200,
                    expand="version",
                    convert_to_markdown=False,
                )

    def test_get_page_by_path_with_content(self, pages_mixin):
        """Test getting a page by path with content included."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages response
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock page content response
        content_page = ConfluencePage.from_api_response(
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "version": {"number": 1},
                "body": {"storage": {"value": "<p>Documentation content</p>"}},
            },
            base_url=pages_mixin.config.url,
            include_body=True,
            content_override="Documentation content in markdown",
            content_format="markdown",
        )

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin, "get_page_content", return_value=content_page
            ):
                # Act
                result = pages_mixin.get_page_by_path(
                    space_key, path, include_content=True
                )

                # Assert
                assert result is not None
                assert result.id == "doc_root"
                assert result.title == "Documentation"
                assert result.content == "Documentation content in markdown"
                pages_mixin.get_page_content.assert_called_once_with(
                    page_id="doc_root", convert_to_markdown=True
                )

    def test_get_page_by_path_case_insensitive(self, pages_mixin):
        """Test that path matching is case-insensitive."""
        # Arrange
        space_key = "DEMO"
        path = "documentation/api"  # lowercase
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages with mixed case titles
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",  # Title case
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock API children with uppercase
        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",  # Uppercase
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",  # Title case
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin, "get_page_children", return_value=api_children
            ):
                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is not None
                assert result.id == "api_page"
                assert result.title == "API"

    def test_get_page_by_path_backslash_separator(self, pages_mixin):
        """Test path with backslash separators (Windows-style)."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation\\API\\REST"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Set up the same hierarchy as multi-level test
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        rest_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "rest_page",
                    "title": "REST",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(pages_mixin, "get_page_children") as mock_get_children:

                def mock_children_side_effect(page_id, **kwargs):
                    if page_id == "doc_root":
                        return api_children
                    elif page_id == "api_page":
                        return rest_children
                    return []

                mock_get_children.side_effect = mock_children_side_effect

                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is not None
                assert result.id == "rest_page"
                assert result.title == "REST"

    def test_get_page_by_path_mixed_separators(self, pages_mixin):
        """Test path with mixed separators."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation/API\\REST"  # Mixed separators
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Set up the same hierarchy as multi-level test
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        rest_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "rest_page",
                    "title": "REST",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(pages_mixin, "get_page_children") as mock_get_children:

                def mock_children_side_effect(page_id, **kwargs):
                    if page_id == "doc_root":
                        return api_children
                    elif page_id == "api_page":
                        return rest_children
                    return []

                mock_get_children.side_effect = mock_children_side_effect

                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is not None
                assert result.id == "rest_page"

    def test_get_page_by_path_path_not_found(self, pages_mixin):
        """Test when the path doesn't exist."""
        # Arrange
        space_key = "DEMO"
        path = "Nonexistent/Page"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages that don't contain "Nonexistent"
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "other_root",
                "title": "Other Root",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            # Act
            result = pages_mixin.get_page_by_path(space_key, path)

            # Assert
            assert result is None

    def test_get_page_by_path_intermediate_page_has_no_children(self, pages_mixin):
        """Test when an intermediate page has no children but path continues."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation/Nonexistent"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin, "get_page_children", return_value=[]
            ):  # No children
                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is None

    def test_get_page_by_path_empty_space_key(self, pages_mixin):
        """Test with empty space key."""
        # Act
        result = pages_mixin.get_page_by_path("", "Documentation")

        # Assert
        assert result is None

    def test_get_page_by_path_empty_path(self, pages_mixin):
        """Test with empty path."""
        # Act
        result = pages_mixin.get_page_by_path("DEMO", "")

        # Assert
        assert result is None

    def test_get_page_by_path_whitespace_only_path(self, pages_mixin):
        """Test with whitespace-only path."""
        # Act
        result = pages_mixin.get_page_by_path("DEMO", "   ")

        # Assert
        assert result is None

    def test_get_page_by_path_path_with_empty_segments(self, pages_mixin):
        """Test path with empty segments (double slashes)."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation//API"  # Double slash creates empty segment
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock API children
        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin, "get_page_children", return_value=api_children
            ):
                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert - Should find API page despite empty segment
                assert result is not None
                assert result.id == "api_page"
                assert result.title == "API"

    def test_get_page_by_path_whitespace_in_segments(self, pages_mixin):
        """Test path with whitespace around segments."""
        # Arrange
        space_key = "DEMO"
        path = " Documentation / API "  # Whitespace around segments
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock API children
        api_children = [
            ConfluencePage.from_api_response(
                {
                    "id": "api_page",
                    "title": "API",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin, "get_page_children", return_value=api_children
            ):
                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert - Should find API page after trimming whitespace
                assert result is not None
                assert result.id == "api_page"
                assert result.title == "API"

    def test_get_page_by_path_no_root_pages(self, pages_mixin):
        """Test when space has no root pages."""
        # Arrange
        space_key = "EMPTY"
        path = "Documentation"

        with patch.object(
            pages_mixin.confluence, "get_all_pages_from_space", return_value=[]
        ):
            # Act
            result = pages_mixin.get_page_by_path(space_key, path)

            # Assert
            assert result is None

    def test_get_page_by_path_error_in_root_pages(self, pages_mixin):
        """Test error handling when getting root pages fails."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation"

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            side_effect=Exception("API Error"),
        ):
            # Act
            result = pages_mixin.get_page_by_path(space_key, path)

            # Assert
            assert result is None

    def test_get_page_by_path_error_in_children(self, pages_mixin):
        """Test error handling when getting children fails."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation/API"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin,
                "get_page_children",
                side_effect=Exception("Children API Error"),
            ):
                # Act
                result = pages_mixin.get_page_by_path(space_key, path)

                # Assert
                assert result is None

    def test_get_page_by_path_error_in_content_fetch(self, pages_mixin):
        """Test error handling when getting page content fails."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            )
        ]

        # Mock all_space_pages response with root pages
        all_space_pages = [
            {
                "id": "doc_root",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            }
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            with patch.object(
                pages_mixin,
                "get_page_content",
                side_effect=Exception("Content API Error"),
            ):
                # Act
                result = pages_mixin.get_page_by_path(
                    space_key, path, include_content=True
                )

                # Assert
                assert result is None

    def test_get_page_by_path_duplicate_titles_first_match(self, pages_mixin):
        """Test that the first match is returned when there are duplicate titles."""
        # Arrange
        space_key = "DEMO"
        path = "Documentation"
        pages_mixin.config.url = "https://example.atlassian.net/wiki"

        # Mock root pages with duplicate titles
        root_pages = [
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root_1",
                    "title": "Documentation",
                    "space": {"key": space_key},
                    "version": {"number": 1},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            ),
            ConfluencePage.from_api_response(
                {
                    "id": "doc_root_2",
                    "title": "Documentation",  # Duplicate title
                    "space": {"key": space_key},
                    "version": {"number": 2},
                },
                base_url=pages_mixin.config.url,
                include_body=False,
            ),
        ]

        # Mock all_space_pages response with root pages having duplicate titles
        all_space_pages = [
            {
                "id": "doc_root_1",
                "title": "Documentation",
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 1},
            },
            {
                "id": "doc_root_2",
                "title": "Documentation",  # Duplicate title
                "space": {"key": space_key},
                "ancestors": [],  # Root page
                "version": {"number": 2},
            },
        ]

        with patch.object(
            pages_mixin.confluence,
            "get_all_pages_from_space",
            return_value=all_space_pages,
        ):
            # Act
            result = pages_mixin.get_page_by_path(space_key, path)

            # Assert - Should return the first match
            assert result is not None
            assert result.id == "doc_root_1"
            assert result.title == "Documentation"
