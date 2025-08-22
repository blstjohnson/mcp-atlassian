"""Module for Confluence page operations."""

import logging

import requests
from requests.exceptions import HTTPError

from ..exceptions import MCPAtlassianAuthenticationError
from ..models.confluence import ConfluencePage
from ..utils.decorators import handle_atlassian_api_errors
from .client import ConfluenceClient
from .v2_adapter import ConfluenceV2Adapter

logger = logging.getLogger("mcp-atlassian")


class PagesMixin(ConfluenceClient):
    """Mixin for Confluence page operations."""

    @property
    def _v2_adapter(self) -> ConfluenceV2Adapter | None:
        """Get v2 API adapter for OAuth authentication.

        Returns:
            ConfluenceV2Adapter instance if OAuth is configured, None otherwise
        """
        if self.config.auth_type == "oauth" and self.config.is_cloud:
            return ConfluenceV2Adapter(
                session=self.confluence._session, base_url=self.confluence.url
            )
        return None

    def get_page_content(
        self, page_id: str, *, convert_to_markdown: bool = True
    ) -> ConfluencePage:
        """
        Get content of a specific page.

        Args:
            page_id: The ID of the page to retrieve
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only)

        Returns:
            ConfluencePage model containing the page content and metadata

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)
            Exception: If there is an error retrieving the page
        """
        try:
            # Use v2 API for OAuth authentication, v1 API for token/basic auth
            v2_adapter = self._v2_adapter
            if v2_adapter:
                logger.debug(
                    f"Using v2 API for OAuth authentication to get page '{page_id}'"
                )
                page = v2_adapter.get_page(
                    page_id=page_id,
                    expand="body.storage,version,space,children.attachment",
                )
            else:
                logger.debug(
                    f"Using v1 API for token/basic authentication to get page '{page_id}'"
                )
                page = self.confluence.get_page_by_id(
                    page_id=page_id,
                    expand="body.storage,version,space,children.attachment",
                )

            space_key = page.get("space", {}).get("key", "")
            content = page["body"]["storage"]["value"]
            processed_html, processed_markdown = self.preprocessor.process_html_content(
                content, space_key=space_key, confluence_client=self.confluence
            )

            # Use the appropriate content format based on the convert_to_markdown flag
            page_content = processed_markdown if convert_to_markdown else processed_html

            # Create and return the ConfluencePage model
            return ConfluencePage.from_api_response(
                page,
                base_url=self.config.url,
                include_body=True,
                # Override content with our processed version
                content_override=page_content,
                content_format="storage" if not convert_to_markdown else "markdown",
                is_cloud=self.config.is_cloud,
            )
        except HTTPError as http_err:
            if http_err.response is not None and http_err.response.status_code in [
                401,
                403,
            ]:
                error_msg = (
                    f"Authentication failed for Confluence API ({http_err.response.status_code}). "
                    "Token may be expired or invalid. Please verify credentials."
                )
                logger.error(error_msg)
                raise MCPAtlassianAuthenticationError(error_msg) from http_err
            else:
                logger.error(f"HTTP error during API call: {http_err}", exc_info=False)
                raise http_err
        except Exception as e:
            logger.error(
                f"Error retrieving page content for page ID {page_id}: {str(e)}"
            )
            raise Exception(f"Error retrieving page content: {str(e)}") from e

    def get_page_ancestors(self, page_id: str) -> list[ConfluencePage]:
        """
        Get ancestors (parent pages) of a specific page.

        Args:
            page_id: The ID of the page to get ancestors for

        Returns:
            List of ConfluencePage models representing the ancestors in hierarchical order
                (immediate parent first, root ancestor last)

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)
        """
        try:
            # Use the Atlassian Python API to get ancestors
            ancestors = self.confluence.get_page_ancestors(page_id)

            # Process each ancestor
            ancestor_models = []
            for ancestor in ancestors:
                # Create the page model without fetching content
                page_model = ConfluencePage.from_api_response(
                    ancestor,
                    base_url=self.config.url,
                    include_body=False,
                )
                ancestor_models.append(page_model)

            return ancestor_models
        except HTTPError as http_err:
            if http_err.response is not None and http_err.response.status_code in [
                401,
                403,
            ]:
                error_msg = (
                    f"Authentication failed for Confluence API ({http_err.response.status_code}). "
                    "Token may be expired or invalid. Please verify credentials."
                )
                logger.error(error_msg)
                raise MCPAtlassianAuthenticationError(error_msg) from http_err
            else:
                logger.error(f"HTTP error during API call: {http_err}", exc_info=False)
                raise http_err
        except Exception as e:
            logger.error(f"Error fetching ancestors for page {page_id}: {str(e)}")
            logger.debug("Full exception details:", exc_info=True)
            return []

    def get_page_by_title(
        self, space_key: str, title: str, *, convert_to_markdown: bool = True
    ) -> ConfluencePage | None:
        """
        Get a specific page by its title from a Confluence space.

        Args:
            space_key: The key of the space containing the page
            title: The title of the page to retrieve
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only)

        Returns:
            ConfluencePage model containing the page content and metadata, or None if not found
        """
        try:
            # Directly try to find the page by title
            page = self.confluence.get_page_by_title(
                space=space_key, title=title, expand="body.storage,version"
            )

            if not page:
                logger.warning(
                    f"Page '{title}' not found in space '{space_key}'. "
                    f"The space may be invalid, the page may not exist, or permissions may be insufficient."
                )
                return None

            content = page["body"]["storage"]["value"]
            processed_html, processed_markdown = self.preprocessor.process_html_content(
                content, space_key=space_key, confluence_client=self.confluence
            )

            # Use the appropriate content format based on the convert_to_markdown flag
            page_content = processed_markdown if convert_to_markdown else processed_html

            # Create and return the ConfluencePage model
            return ConfluencePage.from_api_response(
                page,
                base_url=self.config.url,
                include_body=True,
                # Override content with our processed version
                content_override=page_content,
                content_format="storage" if not convert_to_markdown else "markdown",
                is_cloud=self.config.is_cloud,
            )

        except KeyError as e:
            logger.error(f"Missing key in page data: {str(e)}")
            return None
        except requests.RequestException as e:
            logger.error(f"Network error when fetching page: {str(e)}")
            return None
        except (ValueError, TypeError) as e:
            logger.error(f"Error processing page data: {str(e)}")
            return None
        except Exception as e:  # noqa: BLE001 - Intentional fallback with full logging
            logger.error(f"Unexpected error fetching page: {str(e)}")
            # Log the full traceback at debug level for troubleshooting
            logger.debug("Full exception details:", exc_info=True)
            return None

    def get_space_pages(
        self,
        space_key: str,
        start: int = 0,
        limit: int = 10,
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get all pages from a specific space.

        Args:
            space_key: The key of the space to get pages from
            start: The starting index for pagination
            limit: Maximum number of pages to return
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only)

        Returns:
            List of ConfluencePage models containing page content and metadata
        """
        pages = self.confluence.get_all_pages_from_space(
            space=space_key, start=start, limit=limit, expand="body.storage"
        )

        page_models = []
        for page in pages:
            content = page["body"]["storage"]["value"]
            processed_html, processed_markdown = self.preprocessor.process_html_content(
                content, space_key=space_key, confluence_client=self.confluence
            )

            # Use the appropriate content format based on the convert_to_markdown flag
            page_content = processed_markdown if convert_to_markdown else processed_html

            # Ensure space information is included
            if "space" not in page:
                page["space"] = {
                    "key": space_key,
                    "name": space_key,  # Use space_key as name if not available
                }

            # Create the ConfluencePage model
            page_model = ConfluencePage.from_api_response(
                page,
                base_url=self.config.url,
                include_body=True,
                # Override content with our processed version
                content_override=page_content,
                content_format="storage" if not convert_to_markdown else "markdown",
                is_cloud=self.config.is_cloud,
            )

            page_models.append(page_model)

        return page_models

    def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        parent_id: str | None = None,
        *,
        is_markdown: bool = True,
        enable_heading_anchors: bool = False,
        content_representation: str | None = None,
    ) -> ConfluencePage:
        """
        Create a new page in a Confluence space.

        Args:
            space_key: The key of the space to create the page in
            title: The title of the new page
            body: The content of the page (markdown, wiki markup, or storage format)
            parent_id: Optional ID of a parent page
            is_markdown: Whether the body content is in markdown format (default: True, keyword-only)
            enable_heading_anchors: Whether to enable automatic heading anchor generation (default: False, keyword-only)
            content_representation: Content format when is_markdown=False ('wiki' or 'storage', keyword-only)

        Returns:
            ConfluencePage model containing the new page's data

        Raises:
            Exception: If there is an error creating the page
        """
        try:
            # Determine body and representation based on content type
            if is_markdown:
                # Convert markdown to Confluence storage format
                final_body = self.preprocessor.markdown_to_confluence_storage(
                    body, enable_heading_anchors=enable_heading_anchors
                )
                representation = "storage"
            else:
                # Use body as-is with specified representation
                final_body = body
                representation = content_representation or "storage"

            # Use v2 API for OAuth authentication, v1 API for token/basic auth
            v2_adapter = self._v2_adapter
            if v2_adapter:
                logger.debug(
                    f"Using v2 API for OAuth authentication to create page '{title}'"
                )
                result = v2_adapter.create_page(
                    space_key=space_key,
                    title=title,
                    body=final_body,
                    parent_id=parent_id,
                    representation=representation,
                )
            else:
                logger.debug(
                    f"Using v1 API for token/basic authentication to create page '{title}'"
                )
                result = self.confluence.create_page(
                    space=space_key,
                    title=title,
                    body=final_body,
                    parent_id=parent_id,
                    representation=representation,
                )

            # Get the new page content
            page_id = result.get("id")
            if not page_id:
                raise ValueError("Create page response did not contain an ID")

            return self.get_page_content(page_id)
        except Exception as e:
            logger.error(
                f"Error creating page '{title}' in space {space_key}: {str(e)}"
            )
            raise Exception(
                f"Failed to create page '{title}' in space {space_key}: {str(e)}"
            ) from e

    def update_page(
        self,
        page_id: str,
        title: str,
        body: str,
        *,
        is_minor_edit: bool = False,
        version_comment: str = "",
        is_markdown: bool = True,
        parent_id: str | None = None,
        enable_heading_anchors: bool = False,
        content_representation: str | None = None,
    ) -> ConfluencePage:
        """
        Update an existing page in Confluence.

        Args:
            page_id: The ID of the page to update
            title: The new title of the page
            body: The new content of the page (markdown, wiki markup, or storage format)
            is_minor_edit: Whether this is a minor edit (keyword-only)
            version_comment: Optional comment for this version (keyword-only)
            is_markdown: Whether the body content is in markdown format (default: True, keyword-only)
            parent_id: Optional new parent page ID (keyword-only)
            enable_heading_anchors: Whether to enable automatic heading anchor generation (default: False, keyword-only)
            content_representation: Content format when is_markdown=False ('wiki' or 'storage', keyword-only)

        Returns:
            ConfluencePage model containing the updated page's data

        Raises:
            Exception: If there is an error updating the page
        """
        try:
            # Determine body and representation based on content type
            if is_markdown:
                # Convert markdown to Confluence storage format
                final_body = self.preprocessor.markdown_to_confluence_storage(
                    body, enable_heading_anchors=enable_heading_anchors
                )
                representation = "storage"
            else:
                # Use body as-is with specified representation
                final_body = body
                representation = content_representation or "storage"

            logger.debug(f"Updating page {page_id} with title '{title}'")

            # Use v2 API for OAuth authentication, v1 API for token/basic auth
            v2_adapter = self._v2_adapter
            if v2_adapter:
                logger.debug(
                    f"Using v2 API for OAuth authentication to update page '{page_id}'"
                )
                response = v2_adapter.update_page(
                    page_id=page_id,
                    title=title,
                    body=final_body,
                    representation=representation,
                    version_comment=version_comment,
                )
            else:
                logger.debug(
                    f"Using v1 API for token/basic authentication to update page '{page_id}'"
                )
                update_kwargs = {
                    "page_id": page_id,
                    "title": title,
                    "body": final_body,
                    "type": "page",
                    "representation": representation,
                    "minor_edit": is_minor_edit,
                    "version_comment": version_comment,
                    "always_update": True,
                }
                if parent_id:
                    update_kwargs["parent_id"] = parent_id

                self.confluence.update_page(**update_kwargs)

            # After update, refresh the page data
            return self.get_page_content(page_id)
        except Exception as e:
            logger.error(f"Error updating page {page_id}: {str(e)}")
            raise Exception(f"Failed to update page {page_id}: {str(e)}") from e

    def get_page_children(
        self,
        page_id: str,
        start: int = 0,
        limit: int = 25,
        expand: str = "version",
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get child pages of a specific Confluence page.

        Args:
            page_id: The ID of the parent page
            start: The starting index for pagination
            limit: Maximum number of child pages to return
            expand: Fields to expand in the response
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only)

        Returns:
            List of ConfluencePage models containing the child pages
        """
        try:
            # Use the Atlassian Python API's get_page_child_by_type method
            results = self.confluence.get_page_child_by_type(
                page_id=page_id, type="page", start=start, limit=limit, expand=expand
            )

            # Process results
            page_models = []

            # Handle both pagination modes
            if isinstance(results, dict) and "results" in results:
                child_pages = results.get("results", [])
            else:
                child_pages = results or []

            space_key = ""

            # Get space key from the first result if available
            if child_pages and "space" in child_pages[0]:
                space_key = child_pages[0].get("space", {}).get("key", "")

            # Process each child page
            for page in child_pages:
                # Only process content if we have "body" expanded
                content_override = None
                if "body" in page and convert_to_markdown:
                    content = page.get("body", {}).get("storage", {}).get("value", "")
                    if content:
                        _, processed_markdown = self.preprocessor.process_html_content(
                            content,
                            space_key=space_key,
                            confluence_client=self.confluence,
                        )
                        content_override = processed_markdown

                # Create the page model
                page_model = ConfluencePage.from_api_response(
                    page,
                    base_url=self.config.url,
                    include_body=True,
                    content_override=content_override,
                    content_format="markdown" if convert_to_markdown else "storage",
                )

                page_models.append(page_model)

            return page_models

        except Exception as e:
            logger.error(f"Error fetching child pages for page {page_id}: {str(e)}")
            logger.debug("Full exception details:", exc_info=True)
            return []

    def delete_page(self, page_id: str) -> bool:
        """
        Delete a Confluence page by its ID.

        Args:
            page_id: The ID of the page to delete

        Returns:
            Boolean indicating success (True) or failure (False)

        Raises:
            Exception: If there is an error deleting the page
        """
        try:
            logger.debug(f"Deleting page {page_id}")

            # Use v2 API for OAuth authentication, v1 API for token/basic auth
            v2_adapter = self._v2_adapter
            if v2_adapter:
                logger.debug(
                    f"Using v2 API for OAuth authentication to delete page '{page_id}'"
                )
                return v2_adapter.delete_page(page_id=page_id)
            else:
                logger.debug(
                    f"Using v1 API for token/basic authentication to delete page '{page_id}'"
                )
                response = self.confluence.remove_page(page_id=page_id)

                # The Atlassian library's remove_page returns the raw response from
                # the REST API call. For a successful deletion, we should get a
                # response object, but it might be empty (HTTP 204 No Content).
                # For REST DELETE operations, a success typically returns 204 or 200

                # Check if we got a response object
                if isinstance(response, requests.Response):
                    # Check if status code indicates success (2xx)
                    success = 200 <= response.status_code < 300
                    logger.debug(
                        f"Delete page {page_id} returned status code {response.status_code}"
                    )
                    return success
                # If it's not a response object but truthy (like True), consider it a success
                elif response:
                    return True
                # Default to true since no exception was raised
                # This is safer than returning false when we don't know what happened
                return True

        except Exception as e:
            logger.error(f"Error deleting page {page_id}: {str(e)}")
            raise Exception(f"Failed to delete page {page_id}: {str(e)}") from e

    @handle_atlassian_api_errors("Confluence API")
    def get_page_siblings(
        self,
        page_id: str,
        include_self: bool = False,
        start: int = 0,
        limit: int = 50,
        expand: str = "version",
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get sibling pages (pages with the same parent) of a specific Confluence page.

        Sibling pages are pages that share the same parent page. For root pages
        (pages with no parent), siblings are other root pages in the same space.
        This method is useful for horizontal navigation within a page hierarchy.

        Args:
            page_id: The ID of the page to find siblings for
            include_self: Whether to include the page itself in results (default: False)
            start: Starting index for pagination (default: 0)
            limit: Maximum number of pages to return (1-200, default: 50)
            expand: Fields to expand in the response (default: "version")
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only, default: True)

        Returns:
            List of ConfluencePage models representing sibling pages

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)
        """
        # Validate limit parameter
        if limit < 1 or limit > 200:
            logger.warning(f"Invalid limit {limit}, using default of 50")
            limit = 50

        try:
            # First, get the page itself to access space information
            page_data = self.confluence.get_page_by_id(
                page_id=page_id, expand="ancestors,space"
            )

            if not page_data:
                logger.warning(f"Page {page_id} not found")
                return []

            # Extract space key for root page sibling lookup
            space_key = page_data.get("space", {}).get("key", "")
            if not space_key:
                logger.warning(f"Could not determine space for page {page_id}")
                return []

            # Get ancestors to determine if this is a root page
            ancestors = page_data.get("ancestors", [])

            if not ancestors:
                # This is a root page - get other root pages in the same space
                logger.debug(
                    f"Page {page_id} is a root page, getting root siblings from space {space_key}"
                )

                # Get root pages directly using Confluence API to avoid cross-mixin dependency
                # This is equivalent to get_space_root_pages but avoids MyPy type issues
                try:
                    # Get all pages in the space and filter for root pages (no ancestors)
                    all_space_pages = self.confluence.get_all_pages_from_space(
                        space=space_key,
                        start=0,
                        limit=200,
                        expand=f"ancestors,{expand}",
                    )

                    # Filter for root pages and convert to ConfluencePage models
                    all_root_pages = []
                    for page_data in all_space_pages:
                        # Check if this is a root page (no ancestors)
                        if not page_data.get("ancestors", []):
                            # Only process content if needed
                            content_override = None
                            if "body" in expand and convert_to_markdown:
                                content = (
                                    page_data.get("body", {})
                                    .get("storage", {})
                                    .get("value", "")
                                )
                                if content:
                                    _, processed_markdown = (
                                        self.preprocessor.process_html_content(
                                            content,
                                            space_key=space_key,
                                            confluence_client=self.confluence,
                                        )
                                    )
                                    content_override = processed_markdown

                            # Create ConfluencePage model
                            page_model = ConfluencePage.from_api_response(
                                page_data,
                                base_url=self.config.url,
                                include_body="body" in expand,
                                content_override=content_override,
                                content_format="markdown"
                                if convert_to_markdown
                                else "storage",
                                is_cloud=self.config.is_cloud,
                            )
                            all_root_pages.append(page_model)

                except Exception as e:
                    logger.error(
                        f"Error fetching root pages for space {space_key}: {str(e)}"
                    )
                    return []

                # Filter out the current page if include_self=False
                sibling_pages = []
                for page in all_root_pages:
                    if page.id != page_id or include_self:
                        sibling_pages.append(page)

                # Apply pagination manually since we filtered
                total_siblings = len(sibling_pages)
                if start >= total_siblings:
                    return []

                end_index = min(start + limit, total_siblings)
                return sibling_pages[start:end_index]

            else:
                # This page has a parent - get children of the parent
                parent_id = ancestors[-1]["id"]  # Last ancestor is immediate parent
                logger.debug(
                    f"Page {page_id} has parent {parent_id}, getting sibling children"
                )

                # Get all children of the parent
                all_children = self.get_page_children(
                    page_id=parent_id,
                    start=0,  # Get all children first, then filter/paginate
                    limit=200,  # Get a reasonable number to filter from
                    expand=expand,
                    convert_to_markdown=convert_to_markdown,
                )

                # Filter out the current page if include_self=False
                sibling_pages = []
                for page in all_children:
                    if page.id != page_id or include_self:
                        sibling_pages.append(page)

                # Apply pagination manually since we filtered
                total_siblings = len(sibling_pages)
                if start >= total_siblings:
                    return []

                end_index = min(start + limit, total_siblings)
                return sibling_pages[start:end_index]

        except Exception as e:
            logger.error(f"Error fetching siblings for page {page_id}: {str(e)}")
            logger.debug("Full exception details:", exc_info=True)
            return []

    def get_page_breadcrumbs(
        self, page_id: str, include_content: bool = False
    ) -> list[ConfluencePage]:
        """
        Get breadcrumb navigation trail for a specific Confluence page.

        A breadcrumb trail shows the hierarchical path from the root page to the current page,
        providing navigation context within the page tree. This is useful for understanding
        page location and enabling easy navigation to parent/ancestor pages.

        Args:
            page_id: The ID of the page to get breadcrumbs for
            include_content: Whether to include page content in the results (default: False)

        Returns:
            List of ConfluencePage models representing the breadcrumb trail from root to current page
            The list is ordered from topmost ancestor to the current page.

        Raises:
            Exception: If there is an error retrieving the current page content
        """
        # Get current page content - always convert to markdown for consistency
        current_page = self.get_page_content(page_id=page_id, convert_to_markdown=True)

        # Get ancestors (returned in closest-to-farthest order)
        # Ancestors from get_page_ancestors don't include content by default
        ancestors = self.get_page_ancestors(page_id)

        # Reverse ancestors to get root-to-parent order, then add current page
        breadcrumbs = list(reversed(ancestors)) + [current_page]

        return breadcrumbs

    @handle_atlassian_api_errors("Confluence API")
    def get_page_descendants(
        self,
        page_id: str,
        max_depth: int | None = None,
        limit: int = 200,
        include_content: bool = False,
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get all descendant pages (children, grandchildren, etc.) of a specific Confluence page.

        This method recursively traverses the page tree starting from the specified page,
        collecting all descendant pages in a flat list. It provides depth limiting to
        prevent infinite recursion and supports content inclusion for detailed results.

        Args:
            page_id: The ID of the page to get descendants for
            max_depth: Maximum depth to traverse (None for unlimited, default: None)
                      Depth 0 = no descendants, depth 1 = direct children only, etc.
            limit: Maximum total number of descendants to return (1-500, default: 200)
            include_content: Whether to include page content in the results (default: False)
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only, default: True)

        Returns:
            List of ConfluencePage models representing all descendants in discovery order
            (breadth-first traversal from immediate children to deepest descendants)

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)

        Example:
            # Get all descendants (unlimited depth)
            descendants = pages_mixin.get_page_descendants("123456")

            # Get only direct children (depth 1)
            children = pages_mixin.get_page_descendants("123456", max_depth=1)

            # Get descendants with content included
            full_descendants = pages_mixin.get_page_descendants("123456", include_content=True)
        """
        # Validate limit parameter
        if limit < 1 or limit > 500:
            logger.warning(f"Invalid limit {limit}, using default of 200")
            limit = 200

        # Validate max_depth parameter
        if max_depth is not None and max_depth < 0:
            logger.warning(f"Invalid max_depth {max_depth}, using None (unlimited)")
            max_depth = None

        descendants = []
        visited = set()  # Track visited pages to prevent infinite loops

        # Use queue for breadth-first traversal: (page_id, depth)
        queue = [(page_id, 0)]
        visited.add(page_id)

        try:
            while queue and len(descendants) < limit:
                current_page_id, current_depth = queue.pop(0)

                # Check depth limit
                if max_depth is not None and current_depth >= max_depth:
                    continue

                try:
                    # Determine expand parameter based on whether content is needed
                    expand = "version"
                    if include_content:
                        expand = "version,body.storage"

                    # Get children for this page
                    children = self.get_page_children(
                        page_id=current_page_id,
                        start=0,
                        limit=min(
                            200, limit - len(descendants)
                        ),  # Don't fetch more than we need
                        expand=expand,
                        convert_to_markdown=convert_to_markdown,
                    )

                    # Add children to descendants list and queue for further processing
                    for child in children:
                        if len(descendants) >= limit:
                            break

                        # Check for circular reference before adding child
                        if child.id not in visited:
                            descendants.append(child)
                            visited.add(child.id)
                            # Add child to queue for further processing at next depth level
                            queue.append((child.id, current_depth + 1))
                        else:
                            logger.warning(
                                f"Circular reference detected for page {child.id}, skipping"
                            )

                except Exception as e:
                    logger.error(
                        f"Error getting children for page {current_page_id} at depth {current_depth}: {str(e)}"
                    )
                    # Continue with other pages even if one fails

            logger.info(
                f"Retrieved {len(descendants)} descendants for page {page_id} "
                f"(max_depth: {max_depth}, limit: {limit})"
            )

            return descendants

        except Exception as e:
            logger.error(f"Error fetching descendants for page {page_id}: {str(e)}")
            logger.debug("Full exception details:", exc_info=True)
            return []

    @handle_atlassian_api_errors("Confluence API")
    def get_page_by_path(
        self,
        space_key: str,
        path: str,
        include_content: bool = False,
        *,
        convert_to_markdown: bool = True,
    ) -> ConfluencePage | None:
        """
        Get a Confluence page by navigating through a hierarchical path.

        This method resolves a page by traversing the page hierarchy using a path format
        like "Parent/Child/Grandchild". It starts from the space root pages and follows
        the path segments to find the target page.

        Args:
            space_key: The key of the space containing the page hierarchy
            path: Hierarchical path to the page (e.g., "Parent/Child/Grandchild")
                 Supports both "/" and "\" as path separators for cross-platform compatibility
            include_content: Whether to include page content in the result (default: False)
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only, default: True)

        Returns:
            ConfluencePage model containing the target page, or None if path not found

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)

        Example:
            # Find a page using hierarchical path
            page = pages_mixin.get_page_by_path("DEV", "Documentation/API/REST")

            # Find page with content included
            page = pages_mixin.get_page_by_path("PROJ", "Meetings/Weekly", include_content=True)

            # Handle different path separators
            page = pages_mixin.get_page_by_path("TEAM", "Project\\Reports\\Monthly")
        """
        # Validate inputs
        if not space_key or not space_key.strip():
            logger.warning("Empty space_key provided to get_page_by_path")
            return None

        if not path or not path.strip():
            logger.warning("Empty path provided to get_page_by_path")
            return None

        # Clean and split the path
        path = path.strip()
        # Support both forward slash and backslash as separators for cross-platform compatibility
        path_segments = []
        for segment in path.replace("\\", "/").split("/"):
            segment = segment.strip()
            if segment:  # Skip empty segments
                path_segments.append(segment)

        if not path_segments:
            logger.warning(f"No valid path segments found in path: {path}")
            return None

        logger.debug(
            f"Navigating path in space '{space_key}': {' -> '.join(path_segments)}"
        )

        try:
            # Start with root pages in the space
            # Get root pages directly using Confluence API to avoid cross-mixin dependency
            # This is equivalent to get_space_root_pages but avoids MyPy type issues
            try:
                # Get all pages in the space and filter for root pages (no ancestors)
                all_space_pages = self.confluence.get_all_pages_from_space(
                    space=space_key,
                    start=0,
                    limit=200,
                    expand="ancestors,version",
                )

                # Filter for root pages and convert to ConfluencePage models
                current_pages = []
                for page_data in all_space_pages:
                    # Check if this is a root page (no ancestors)
                    if not page_data.get("ancestors", []):
                        # Create ConfluencePage model
                        page_model = ConfluencePage.from_api_response(
                            page_data,
                            base_url=self.config.url,
                            include_body=False,
                            is_cloud=self.config.is_cloud,
                        )
                        current_pages.append(page_model)

            except Exception as e:
                logger.error(
                    f"Error fetching root pages for space {space_key}: {str(e)}"
                )
                return None

            current_page = None

            # Navigate through each path segment
            for i, segment in enumerate(path_segments):
                logger.debug(
                    f"Looking for segment '{segment}' among {len(current_pages)} pages"
                )

                # Find the page matching this segment (case-insensitive)
                found_page = None
                for page in current_pages:
                    if page.title.lower() == segment.lower():
                        found_page = page
                        break

                if not found_page:
                    logger.info(
                        f"Path segment '{segment}' not found at level {i + 1} "
                        f"in space '{space_key}'. Available pages: {[p.title for p in current_pages]}"
                    )
                    return None

                current_page = found_page

                # If this is not the last segment, get children for next iteration
                if i < len(path_segments) - 1:
                    current_pages = self.get_page_children(
                        page_id=current_page.id,
                        start=0,
                        limit=200,  # Get enough children to find our next segment
                        expand="version",
                        convert_to_markdown=False,  # We'll handle content conversion at the end
                    )

                    if not current_pages:
                        logger.info(
                            f"Page '{current_page.title}' has no children, but path continues with '{path_segments[i + 1]}'"
                        )
                        return None

            # At this point, current_page should be our target page
            if current_page is None:
                logger.warning(
                    "Unexpected state: current_page is None after path traversal"
                )
                return None

            # If content is requested, get the full page content
            if include_content:
                logger.debug(
                    f"Fetching content for page '{current_page.title}' (ID: {current_page.id})"
                )
                return self.get_page_content(
                    page_id=current_page.id, convert_to_markdown=convert_to_markdown
                )
            else:
                # Return the page without content
                return current_page

        except Exception as e:
            logger.error(
                f"Error navigating path '{path}' in space '{space_key}': {str(e)}"
            )
            logger.debug("Full exception details:", exc_info=True)
            return None
