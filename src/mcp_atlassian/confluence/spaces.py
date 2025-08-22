"""Module for Confluence space operations."""

import logging
from typing import cast

import requests

from ..models.confluence import ConfluencePage
from ..utils.decorators import handle_atlassian_api_errors
from .client import ConfluenceClient

logger = logging.getLogger("mcp-atlassian")


class SpacesMixin(ConfluenceClient):
    """Mixin for Confluence space operations."""

    def get_spaces(self, start: int = 0, limit: int = 10) -> dict[str, object]:
        """
        Get all available spaces.

        Args:
            start: The starting index for pagination
            limit: Maximum number of spaces to return

        Returns:
            Dictionary containing space information with results and metadata
        """
        spaces = self.confluence.get_all_spaces(start=start, limit=limit)
        # Cast the return value to the expected type
        return cast(dict[str, object], spaces)

    def get_user_contributed_spaces(self, limit: int = 250) -> dict:
        """
        Get spaces the current user has contributed to.

        Args:
            limit: Maximum number of results to return

        Returns:
            Dictionary of space keys to space information
        """
        try:
            # Use CQL to find content the user has contributed to
            cql = "contributor = currentUser() order by lastmodified DESC"
            results = self.confluence.cql(cql=cql, limit=limit)

            # Extract and deduplicate spaces
            spaces = {}
            for result in results.get("results", []):
                space_key = None
                space_name = None

                # Try to extract space from container
                if "resultGlobalContainer" in result:
                    container = result.get("resultGlobalContainer", {})
                    space_name = container.get("title")
                    display_url = container.get("displayUrl", "")
                    if display_url and "/spaces/" in display_url:
                        space_key = display_url.split("/spaces/")[1].split("/")[0]

                # Try to extract from content expandable
                if (
                    not space_key
                    and "content" in result
                    and "_expandable" in result["content"]
                ):
                    expandable = result["content"].get("_expandable", {})
                    space_path = expandable.get("space", "")
                    if space_path and space_path.startswith("/rest/api/space/"):
                        space_key = space_path.split("/rest/api/space/")[1]

                # Try to extract from URL
                if not space_key and "url" in result:
                    url = result.get("url", "")
                    if url and url.startswith("/spaces/"):
                        space_key = url.split("/spaces/")[1].split("/")[0]

                # Only add if we found a space key and it's not already in our results
                if space_key and space_key not in spaces:
                    # Add some defaults if we couldn't extract all fields
                    space_name = space_name or f"Space {space_key}"
                    spaces[space_key] = {"key": space_key, "name": space_name}

            return spaces

        except KeyError as e:
            logger.error(f"Missing key in Confluence spaces data: {str(e)}")
            return {}
        except ValueError as e:
            logger.error(f"Invalid value in Confluence spaces: {str(e)}")
            return {}
        except TypeError as e:
            logger.error(f"Type error when processing Confluence spaces: {str(e)}")
            return {}
        except requests.RequestException as e:
            logger.error(f"Network error when fetching spaces: {str(e)}")
            return {}
        except Exception as e:  # noqa: BLE001 - Intentional fallback with logging
            logger.error(f"Unexpected error fetching Confluence spaces: {str(e)}")
            logger.debug("Full exception details for Confluence spaces:", exc_info=True)
            return {}

    @handle_atlassian_api_errors("Confluence API")
    def get_space_root_pages(
        self,
        space_key: str,
        start: int = 0,
        limit: int = 50,
        expand: str = "version",
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get root pages (pages with no parent) from a specific Confluence space.

        Root pages are the top-level entry points for navigation in a space.
        These are pages that have no parent page and serve as the starting
        points for the space's content hierarchy.

        Args:
            space_key: The key of the space to get root pages from
            start: Starting index for pagination (default: 0)
            limit: Maximum number of pages to return (1-200, default: 50)
            expand: Fields to expand in the response (default: "version")
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only, default: True)

        Returns:
            List of ConfluencePage models representing root-level pages

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)
        """
        # Validate limit parameter
        if limit < 1 or limit > 200:
            logger.warning(f"Invalid limit {limit}, using default of 50")
            limit = 50

        # Primary approach: Use CQL to find pages without parents
        cql = f'space = "{space_key}" AND parent = null AND type = page'

        try:
            logger.debug(
                f"Searching for root pages in space '{space_key}' using CQL: {cql}"
            )

            # Use CQL search to find root pages
            results = self.confluence.cql(
                cql=cql, start=start, limit=limit, expand=expand
            )

            if not results or "results" not in results:
                logger.info(f"No root pages found in space '{space_key}'")
                return []

            page_models = []

            # Process each page result
            for cql_result in results.get("results", []):
                try:
                    # Extract the actual page data from CQL result
                    page_data = cql_result.get("content", {})
                    if not page_data:
                        logger.warning(
                            f"CQL result missing 'content' field: {cql_result}"
                        )
                        continue

                    # Handle content processing if needed
                    content_override = None
                    if "body" in page_data and "storage" in page_data["body"]:
                        content = page_data["body"]["storage"]["value"]
                        if content:
                            processed_html, processed_markdown = (
                                self.preprocessor.process_html_content(
                                    content,
                                    space_key=space_key,
                                    confluence_client=self.confluence,
                                )
                            )
                            if convert_to_markdown:
                                content_override = processed_markdown
                            else:
                                content_override = processed_html

                    # Create ConfluencePage model
                    page_model = ConfluencePage.from_api_response(
                        page_data,
                        base_url=self.config.url,
                        include_body=bool(content_override),
                        content_override=content_override,
                        content_format="markdown" if convert_to_markdown else "storage",
                        is_cloud=self.config.is_cloud,
                    )

                    page_models.append(page_model)

                except Exception as e:
                    logger.warning(
                        f"Failed to process root page in space '{space_key}': {str(e)}"
                    )
                    continue

            logger.debug(
                f"Successfully retrieved {len(page_models)} root pages from space '{space_key}'"
            )
            return page_models

        except Exception as e:
            logger.error(
                f"CQL search failed for root pages in space '{space_key}': {str(e)}"
            )
            # Fallback: Return empty list if CQL fails
            logger.info(
                f"Returning empty list for space '{space_key}' due to search failure"
            )
            return []

    @handle_atlassian_api_errors("Confluence API")
    def get_space_pages_flat(
        self,
        space_key: str,
        include_content: bool = False,
        limit: int = 1000,
        *,
        convert_to_markdown: bool = True,
    ) -> list[ConfluencePage]:
        """
        Get all pages from a specific Confluence space without pagination constraints.

        This method retrieves ALL pages from a space efficiently by using automatic
        pagination to collect pages in batches until all pages are retrieved or the
        limit is reached. This is useful for getting a complete overview of a space's
        content without having to manually handle pagination.

        Args:
            space_key: The key of the space to get all pages from
            include_content: Whether to fetch page content (default: False)
            limit: Safety limit for very large spaces (1-5000, default: 1000)
            convert_to_markdown: When True, returns content in markdown format,
                               otherwise returns raw HTML (keyword-only, default: True)

        Returns:
            List of ConfluencePage models representing all pages in the space

        Raises:
            MCPAtlassianAuthenticationError: If authentication fails with the Confluence API (401/403)

        Example:
            # Get all pages in a space (up to 1000)
            pages = spaces_mixin.get_space_pages_flat("DEV")

            # Get all pages with content included
            pages = spaces_mixin.get_space_pages_flat("TEAM", include_content=True)

            # Get all pages with custom limit
            pages = spaces_mixin.get_space_pages_flat("PROJ", limit=500)
        """
        # Validate limit parameter
        if limit < 1 or limit > 5000:
            logger.warning(f"Invalid limit {limit}, using default of 1000")
            limit = 1000

        logger.debug(
            f"Getting all pages from space '{space_key}' with limit {limit}, "
            f"include_content={include_content}, convert_to_markdown={convert_to_markdown}"
        )

        all_pages = []
        start = 0
        batch_size = 50  # Use reasonable batch size to avoid API limits

        try:
            while len(all_pages) < limit:
                # Calculate how many pages to request in this batch
                remaining_limit = limit - len(all_pages)
                current_batch_size = min(batch_size, remaining_limit)

                logger.debug(
                    f"Fetching batch: start={start}, limit={current_batch_size}, "
                    f"total_collected={len(all_pages)}/{limit}"
                )

                # Get pages for this batch using the underlying confluence client
                # This mirrors the logic from PagesMixin.get_space_pages but uses the underlying client directly
                raw_pages = self.confluence.get_all_pages_from_space(
                    space=space_key,
                    start=start,
                    limit=current_batch_size,
                    expand="body.storage",
                )

                # Process the raw pages into ConfluencePage models (same logic as PagesMixin.get_space_pages)
                batch_pages = []
                for page in raw_pages:
                    try:
                        content_override = None

                        # Only process content if include_content is True
                        if include_content:
                            content = page["body"]["storage"]["value"]
                            try:
                                processed_html, processed_markdown = (
                                    self.preprocessor.process_html_content(
                                        content,
                                        space_key=space_key,
                                        confluence_client=self.confluence,
                                    )
                                )
                                # Use the appropriate content format based on convert_to_markdown
                                content_override = (
                                    processed_markdown
                                    if convert_to_markdown
                                    else processed_html
                                )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to process content for page {page.get('id', 'unknown')} "
                                    f"'{page.get('title', 'unknown')}': {str(e)}"
                                )
                                # Continue without content override if processing fails
                                content_override = None

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
                            include_body=include_content,
                            content_override=content_override,
                            content_format="storage"
                            if not convert_to_markdown
                            else "markdown",
                            is_cloud=self.config.is_cloud,
                        )
                        batch_pages.append(page_model)
                    except Exception as e:
                        logger.warning(
                            f"Failed to process page {page.get('id', 'unknown')} "
                            f"'{page.get('title', 'unknown')}': {str(e)}"
                        )
                        # Continue with other pages even if one fails
                        continue

                # If no pages returned, we've reached the end
                if not batch_pages:
                    logger.debug(
                        f"No more pages found at start={start}, stopping pagination"
                    )
                    break

                # Add pages to our collection
                all_pages.extend(batch_pages)

                # If we got fewer pages than requested, we've reached the end
                if len(batch_pages) < current_batch_size:
                    logger.debug(
                        f"Received {len(batch_pages)} pages, less than requested {current_batch_size}, "
                        "assuming end of results"
                    )
                    break

                # Move to next batch
                start += len(batch_pages)

            logger.info(
                f"Successfully retrieved {len(all_pages)} pages from space '{space_key}' "
                f"(limit: {limit}, include_content: {include_content})"
            )

            return all_pages

        except Exception as e:
            logger.error(
                f"Error during paginated fetch of all pages from space '{space_key}': {str(e)}"
            )
            logger.debug("Full exception details:", exc_info=True)
            # Return partial results if we have any
            if all_pages:
                logger.info(
                    f"Returning {len(all_pages)} partially collected pages due to error"
                )
                return all_pages
            return []
