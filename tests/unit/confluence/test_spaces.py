"""Unit tests for the SpacesMixin class."""

from unittest.mock import call, patch

import requests
from fixtures.confluence_mocks import (
    MOCK_EMPTY_ROOT_PAGES_CQL_RESPONSE,
    MOCK_ROOT_PAGES_CQL_RESPONSE,
    MOCK_SPACES_RESPONSE,
)

from mcp_atlassian.models.confluence import ConfluencePage


def create_mock_raw_page(page_id: str, title: str, content: str = "") -> dict:
    """Create a mock raw page response as returned by confluence.get_all_pages_from_space."""
    return {
        "id": page_id,
        "title": title,
        "space": {"key": "TEST"},
        "body": {"storage": {"value": content}},
        "version": {"number": 1},
    }


class TestSpacesMixin:
    """Tests for the SpacesMixin class."""

    # Using the global spaces_mixin fixture from conftest.py

    def test_get_spaces(self, spaces_mixin):
        """Test that get_spaces returns spaces from the Confluence client."""
        # Act
        result = spaces_mixin.get_spaces(start=10, limit=20)

        # Assert
        spaces_mixin.confluence.get_all_spaces.assert_called_once_with(
            start=10, limit=20
        )
        assert result == MOCK_SPACES_RESPONSE

    def test_get_user_contributed_spaces_success(self, spaces_mixin):
        """Test getting spaces that the user has contributed to."""
        # Arrange
        mock_result = {
            "results": [
                {
                    "content": {"_expandable": {"space": "/rest/api/space/TEST"}},
                    "resultGlobalContainer": {
                        "title": "Test Space",
                        "displayUrl": "/spaces/TEST",
                    },
                }
            ]
        }
        spaces_mixin.confluence.cql.return_value = mock_result

        # Act
        result = spaces_mixin.get_user_contributed_spaces(limit=100)

        # Assert
        spaces_mixin.confluence.cql.assert_called_once_with(
            cql="contributor = currentUser() order by lastmodified DESC", limit=100
        )
        assert result == {"TEST": {"key": "TEST", "name": "Test Space"}}

    def test_get_user_contributed_spaces_extraction_methods(self, spaces_mixin):
        """Test that the method extracts space keys from different result structures."""
        # Arrange - Test different extraction methods
        mock_results = {
            "results": [
                # Case 1: Extract from resultGlobalContainer.displayUrl
                {
                    "resultGlobalContainer": {
                        "title": "Space 1",
                        "displayUrl": "/spaces/SPACE1/pages",
                    }
                },
                # Case 2: Extract from content._expandable.space
                {
                    "content": {"_expandable": {"space": "/rest/api/space/SPACE2"}},
                    "resultGlobalContainer": {"title": "Space 2"},
                },
                # Case 3: Extract from url
                {
                    "url": "/spaces/SPACE3/pages/12345",
                    "resultGlobalContainer": {"title": "Space 3"},
                },
            ]
        }
        spaces_mixin.confluence.cql.return_value = mock_results

        # Act
        result = spaces_mixin.get_user_contributed_spaces()

        # Assert
        assert "SPACE1" in result
        assert result["SPACE1"]["name"] == "Space 1"
        assert "SPACE2" in result
        assert result["SPACE2"]["name"] == "Space 2"
        assert "SPACE3" in result
        assert result["SPACE3"]["name"] == "Space 3"

    def test_get_user_contributed_spaces_with_duplicate_spaces(self, spaces_mixin):
        """Test that duplicate spaces are deduplicated."""
        # Arrange
        mock_results = {
            "results": [
                # Same space key appears multiple times
                {
                    "resultGlobalContainer": {
                        "title": "Space 1",
                        "displayUrl": "/spaces/SPACE1",
                    }
                },
                {
                    "resultGlobalContainer": {
                        "title": "Space 1",
                        "displayUrl": "/spaces/SPACE1",
                    }
                },
                {"content": {"_expandable": {"space": "/rest/api/space/SPACE1"}}},
            ]
        }
        spaces_mixin.confluence.cql.return_value = mock_results

        # Act
        result = spaces_mixin.get_user_contributed_spaces()

        # Assert
        assert len(result) == 1
        assert "SPACE1" in result
        assert result["SPACE1"]["name"] == "Space 1"

    def test_get_user_contributed_spaces_api_error(self, spaces_mixin):
        """Test handling of API errors."""
        # Arrange
        spaces_mixin.confluence.cql.side_effect = requests.RequestException("API Error")

        # Act
        result = spaces_mixin.get_user_contributed_spaces()

        # Assert
        assert result == {}

    def test_get_user_contributed_spaces_key_error(self, spaces_mixin):
        """Test handling of KeyError when parsing results."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = {"invalid_key": []}

        # Act
        result = spaces_mixin.get_user_contributed_spaces()

        # Assert
        assert result == {}

    def test_get_user_contributed_spaces_type_error(self, spaces_mixin):
        """Test handling of TypeError when processing results."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = (
            None  # Will cause TypeError when iterating
        )

        # Act
        result = spaces_mixin.get_user_contributed_spaces()

        # Assert
        assert result == {}

    # ============================================================================
    # Tests for get_space_root_pages method
    # ============================================================================

    def test_get_space_root_pages_success(self, spaces_mixin):
        """Test successful root page retrieval."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE
        spaces_mixin.preprocessor.process_html_content.return_value = (
            "<h1>Processed HTML</h1>",
            "# Processed Markdown",
        )

        # Act
        result = spaces_mixin.get_space_root_pages("TEST", limit=50)

        # Assert
        spaces_mixin.confluence.cql.assert_called_once_with(
            cql='space = "TEST" AND parent = null AND type = page',
            start=0,
            limit=50,
            expand="version",
        )
        assert len(result) == 2
        assert isinstance(result[0], ConfluencePage)
        assert result[0].id == "root123"
        assert result[0].title == "Welcome to Test Space"
        assert result[1].id == "root456"
        assert result[1].title == "Getting Started Guide"

    def test_get_space_root_pages_with_content_processing(self, spaces_mixin):
        """Test root page retrieval with content processing."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE
        spaces_mixin.preprocessor.process_html_content.return_value = (
            "<h1>Processed HTML</h1>",
            "# Processed Markdown",
        )

        # Act
        result = spaces_mixin.get_space_root_pages("TEST", convert_to_markdown=True)

        # Assert
        assert len(result) == 2
        # Verify content processing was called
        assert spaces_mixin.preprocessor.process_html_content.call_count == 2

        # Check that the calls included the expected HTML content
        call_args_list = spaces_mixin.preprocessor.process_html_content.call_args_list
        assert any("<h1>Welcome</h1>" in str(call[0]) for call in call_args_list)

    def test_get_space_root_pages_empty_results(self, spaces_mixin):
        """Test handling of empty results (no root pages in space)."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_EMPTY_ROOT_PAGES_CQL_RESPONSE

        # Act
        result = spaces_mixin.get_space_root_pages("EMPTY")

        # Assert
        spaces_mixin.confluence.cql.assert_called_once_with(
            cql='space = "EMPTY" AND parent = null AND type = page',
            start=0,
            limit=50,
            expand="version",
        )
        assert result == []

    def test_get_space_root_pages_invalid_results(self, spaces_mixin):
        """Test handling of invalid CQL results."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = {"invalid": "data"}

        # Act
        result = spaces_mixin.get_space_root_pages("TEST")

        # Assert
        assert result == []

    def test_get_space_root_pages_pagination(self, spaces_mixin):
        """Test pagination parameters."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE

        # Act
        result = spaces_mixin.get_space_root_pages("TEST", start=10, limit=25)

        # Assert
        spaces_mixin.confluence.cql.assert_called_once_with(
            cql='space = "TEST" AND parent = null AND type = page',
            start=10,
            limit=25,
            expand="version",
        )

    def test_get_space_root_pages_limit_validation(self, spaces_mixin):
        """Test limit parameter validation."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE

        # Act - test with invalid limits
        result1 = spaces_mixin.get_space_root_pages("TEST", limit=0)  # Too small
        result2 = spaces_mixin.get_space_root_pages("TEST", limit=300)  # Too large

        # Assert - should use default limit of 50
        expected_calls = [
            call(
                cql='space = "TEST" AND parent = null AND type = page',
                start=0,
                limit=50,
                expand="version",
            ),
            call(
                cql='space = "TEST" AND parent = null AND type = page',
                start=0,
                limit=50,
                expand="version",
            ),
        ]
        spaces_mixin.confluence.cql.assert_has_calls(expected_calls)

    def test_get_space_root_pages_expand_parameter(self, spaces_mixin):
        """Test custom expand parameter."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE

        # Act
        result = spaces_mixin.get_space_root_pages(
            "TEST", expand="version,body.storage"
        )

        # Assert
        spaces_mixin.confluence.cql.assert_called_once_with(
            cql='space = "TEST" AND parent = null AND type = page',
            start=0,
            limit=50,
            expand="version,body.storage",
        )

    def test_get_space_root_pages_cql_error(self, spaces_mixin):
        """Test handling of CQL errors."""
        # Arrange
        spaces_mixin.confluence.cql.side_effect = requests.RequestException("CQL Error")

        # Act
        result = spaces_mixin.get_space_root_pages("TEST")

        # Assert
        assert result == []

    def test_get_space_root_pages_processing_error(self, spaces_mixin):
        """Test handling of content processing errors."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE
        spaces_mixin.preprocessor.process_html_content.return_value = (
            "<h1>Processed HTML</h1>",
            "# Processed Markdown",
        )

        # Mock ConfluencePage.from_api_response to fail on the first call and succeed on the second
        original_from_api_response = ConfluencePage.from_api_response
        call_count = 0

        def mock_from_api_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Simulated processing error")
            return original_from_api_response(*args, **kwargs)

        with patch.object(
            ConfluencePage, "from_api_response", side_effect=mock_from_api_response
        ):
            # Act
            result = spaces_mixin.get_space_root_pages("TEST")

        # Assert - Should skip the invalid page but return the valid one
        assert len(result) == 1  # Only the valid page should be returned
        assert result[0].id == "root456"  # The valid page

    def test_get_space_root_pages_convert_to_markdown_false(self, spaces_mixin):
        """Test root page retrieval without markdown conversion."""
        # Arrange
        spaces_mixin.confluence.cql.return_value = MOCK_ROOT_PAGES_CQL_RESPONSE
        spaces_mixin.preprocessor.process_html_content.return_value = (
            "<h1>Processed HTML</h1>",
            "# Processed Markdown",
        )

        # Act
        result = spaces_mixin.get_space_root_pages("TEST", convert_to_markdown=False)

        # Assert
        assert len(result) == 2
        # Content processing should still be called for pages with body content
        assert spaces_mixin.preprocessor.process_html_content.call_count == 2

        # Verify the content is processed but returns HTML instead of markdown
        for page in result:
            # When convert_to_markdown=False, the content should be processed HTML
            if hasattr(page, "body") and page.body:
                # The content_override should be the processed HTML, not markdown
                assert (
                    "<h1>Processed HTML</h1>" in str(page.body)
                    or page.body == "<h1>Processed HTML</h1>"
                )

    # ============================================================================
    # Tests for get_space_pages_flat method
    # ============================================================================

    def test_get_space_pages_flat_success_small_collection(self, spaces_mixin):
        """Test successful flat page retrieval for small collection (single batch)."""
        # Arrange - Mock a small collection that fits in one batch
        mock_raw_pages = [
            create_mock_raw_page("page1", "Page 1", "<p>Content 1</p>"),
            create_mock_raw_page("page2", "Page 2", "<p>Content 2</p>"),
        ]

        # Mock confluence.get_all_pages_from_space to return our test data on first call, empty on second
        spaces_mixin.confluence.get_all_pages_from_space.side_effect = [
            mock_raw_pages,
            [],
        ]

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=False, limit=100
        )

        # Assert
        assert len(result) == 2
        assert isinstance(result[0], ConfluencePage)
        assert result[0].id == "page1"
        assert result[0].title == "Page 1"
        assert result[1].id == "page2"
        assert result[1].title == "Page 2"

        # Verify confluence.get_all_pages_from_space was called correctly
        assert spaces_mixin.confluence.get_all_pages_from_space.call_count == 1
        spaces_mixin.confluence.get_all_pages_from_space.assert_called_with(
            space="TEST", start=0, limit=50, expand="body.storage"
        )

    def test_get_space_pages_flat_success_multi_batch(self, spaces_mixin):
        """Test successful flat page retrieval with multiple batches (pagination)."""
        # Arrange - Mock multiple batches to test pagination
        mock_pages_batch1 = [
            create_mock_raw_page(f"page{i}", f"Page {i}")
            for i in range(1, 51)  # 50 pages in first batch
        ]
        mock_pages_batch2 = [
            create_mock_raw_page(f"page{i}", f"Page {i}")
            for i in range(51, 76)  # 25 pages in second batch
        ]

        # Mock confluence.get_all_pages_from_space to return batches, then empty
        spaces_mixin.confluence.get_all_pages_from_space.side_effect = [
            mock_pages_batch1,
            mock_pages_batch2,
            [],
        ]

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=False, limit=100
        )

        # Assert
        assert len(result) == 75  # 50 + 25 pages
        assert result[0].id == "page1"
        assert result[49].id == "page50"  # Last of first batch
        assert result[50].id == "page51"  # First of second batch
        assert result[74].id == "page75"  # Last page

        # Verify pagination calls
        assert spaces_mixin.confluence.get_all_pages_from_space.call_count == 2
        expected_calls = [
            call(space="TEST", start=0, limit=50, expand="body.storage"),
            call(space="TEST", start=50, limit=50, expand="body.storage"),
        ]
        spaces_mixin.confluence.get_all_pages_from_space.assert_has_calls(
            expected_calls
        )

    def test_get_space_pages_flat_limit_enforcement(self, spaces_mixin):
        """Test that the limit parameter is properly enforced."""
        # Arrange - Mock more pages than the limit
        batch1 = [
            create_mock_raw_page(f"page{i}", f"Page {i}") for i in range(1, 51)
        ]  # 50 pages
        batch2 = [
            create_mock_raw_page(f"page{i}", f"Page {i}") for i in range(51, 76)
        ]  # 25 pages

        spaces_mixin.confluence.get_all_pages_from_space.side_effect = [batch1, batch2]

        # Act - Set limit to 75
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=False, limit=75
        )

        # Assert - Should stop at limit
        assert len(result) == 75
        assert result[74].id == "page75"

        # Should have made exactly 2 calls (50 + 25 = 75)
        assert spaces_mixin.confluence.get_all_pages_from_space.call_count == 2

    def test_get_space_pages_flat_with_content_inclusion(self, spaces_mixin):
        """Test flat page retrieval with content inclusion."""
        # Arrange
        mock_pages = [create_mock_raw_page("page1", "Page 1", "<p>Full content</p>")]
        spaces_mixin.confluence.get_all_pages_from_space.return_value = mock_pages

        # Mock the content processing
        spaces_mixin.preprocessor.process_html_content.return_value = (
            "<p>Processed HTML</p>",
            "Processed Markdown",
        )

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=True, limit=100
        )

        # Assert
        assert len(result) == 1
        assert result[0].id == "page1"
        # Verify content processing was called
        spaces_mixin.preprocessor.process_html_content.assert_called_once_with(
            "<p>Full content</p>",
            space_key="TEST",
            confluence_client=spaces_mixin.confluence,
        )

    def test_get_space_pages_flat_empty_space(self, spaces_mixin):
        """Test handling of empty spaces (no pages)."""
        # Arrange
        spaces_mixin.confluence.get_all_pages_from_space.return_value = []

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "EMPTY", include_content=False, limit=100
        )

        # Assert
        assert result == []
        spaces_mixin.confluence.get_all_pages_from_space.assert_called_once_with(
            space="EMPTY", start=0, limit=50, expand="body.storage"
        )

    def test_get_space_pages_flat_limit_validation(self, spaces_mixin):
        """Test limit parameter validation."""
        # Arrange
        mock_pages = [create_mock_raw_page("page1", "Page 1")]
        spaces_mixin.confluence.get_all_pages_from_space.return_value = mock_pages

        # Act - Test with invalid limits
        result1 = spaces_mixin.get_space_pages_flat("TEST", limit=0)  # Too small
        result2 = spaces_mixin.get_space_pages_flat("TEST", limit=6000)  # Too large

        # Assert - Should use default limit of 1000 for both
        assert len(result1) == 1
        assert len(result2) == 1
        assert spaces_mixin.confluence.get_all_pages_from_space.call_count == 2

    def test_get_space_pages_flat_api_error_during_pagination(self, spaces_mixin):
        """Test handling of API errors during pagination."""
        # Arrange - First call succeeds, second call fails
        mock_pages_batch1 = [
            create_mock_raw_page(f"page{i}", f"Page {i}") for i in range(1, 51)
        ]

        spaces_mixin.confluence.get_all_pages_from_space.side_effect = [
            mock_pages_batch1,
            Exception("Network error during pagination"),
        ]

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=False, limit=100
        )

        # Assert - Should return partial results from successful first batch
        assert len(result) == 50
        assert result[0].id == "page1"
        assert result[49].id == "page50"

    def test_get_space_pages_flat_content_processing_error(self, spaces_mixin):
        """Test handling of content processing errors for individual pages."""
        # Arrange
        mock_pages = [
            create_mock_raw_page("page1", "Page 1", "<p>Content 1</p>"),
            create_mock_raw_page("page2", "Page 2", "<p>Content 2</p>"),
        ]
        spaces_mixin.confluence.get_all_pages_from_space.return_value = mock_pages

        # Mock content processing to fail for first page, succeed for second
        def mock_process_content(content, **kwargs):
            if "Content 1" in content:
                raise Exception("Content processing failed")
            return ("<p>Processed HTML 2</p>", "Processed Markdown 2")

        spaces_mixin.preprocessor.process_html_content.side_effect = (
            mock_process_content
        )

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=True, limit=100
        )

        # Assert - Should handle processing errors gracefully and continue with other pages
        assert len(result) == 2
        assert (
            result[0].id == "page1"
        )  # First page should still be included (without processed content)
        assert result[1].id == "page2"  # Second page should be processed normally

        # Verify that content processing was attempted for both pages
        assert spaces_mixin.preprocessor.process_html_content.call_count == 2

    def test_get_space_pages_flat_convert_to_markdown_false(self, spaces_mixin):
        """Test flat page retrieval without markdown conversion."""
        # Arrange
        mock_pages = [create_mock_raw_page("page1", "Page 1", "<p>HTML content</p>")]
        spaces_mixin.confluence.get_all_pages_from_space.return_value = mock_pages

        # Act
        result = spaces_mixin.get_space_pages_flat(
            "TEST", include_content=False, convert_to_markdown=False
        )

        # Assert
        assert len(result) == 1
        spaces_mixin.confluence.get_all_pages_from_space.assert_called_once_with(
            space="TEST", start=0, limit=50, expand="body.storage"
        )

    def test_get_space_pages_flat_large_space_performance(self, spaces_mixin):
        """Test performance considerations for large spaces."""

        # Arrange - Simulate a large space with multiple batches
        def mock_get_all_pages_from_space(**kwargs):
            start = kwargs.get("start", 0)
            limit = kwargs.get("limit", 50)

            # Generate mock pages for this batch
            batch_start = start + 1  # Page IDs start from 1
            batch_end = min(start + limit, 200) + 1  # Simulate 200 total pages

            if start >= 200:
                return []  # No more pages

            return [
                create_mock_raw_page(f"page{i}", f"Page {i}")
                for i in range(batch_start, batch_end)
            ]

        spaces_mixin.confluence.get_all_pages_from_space.side_effect = (
            mock_get_all_pages_from_space
        )

        # Act - Request all pages with reasonable limit
        result = spaces_mixin.get_space_pages_flat(
            "LARGE", include_content=False, limit=200
        )

        # Assert
        assert len(result) == 200
        assert result[0].id == "page1"
        assert result[199].id == "page200"

        # Should have made 4 calls (50 + 50 + 50 + 50 = 200)
        assert spaces_mixin.confluence.get_all_pages_from_space.call_count == 4
