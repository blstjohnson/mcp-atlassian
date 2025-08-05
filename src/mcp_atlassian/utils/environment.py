"""Utility functions related to environment checking."""

import logging
import os

from .urls import is_atlassian_cloud_url

logger = logging.getLogger("mcp-atlassian.utils.environment")


def get_available_services() -> dict[str, bool | None]:
    """Determine which services are available based on environment variables."""
    confluence_url = os.getenv("CONFLUENCE_URL")
    confluence_is_setup = False
    if confluence_url:
        is_cloud = is_atlassian_cloud_url(confluence_url)

        # Prioritize Cloud authentication types
        if is_cloud:
            if all(
                [
                    os.getenv("ATLASSIAN_OAUTH_CLIENT_ID"),
                    os.getenv("ATLASSIAN_OAUTH_CLIENT_SECRET"),
                    os.getenv("ATLASSIAN_OAUTH_REDIRECT_URI"),
                    os.getenv("ATLASSIAN_OAUTH_SCOPE"),
                    os.getenv("ATLASSIAN_OAUTH_CLOUD_ID"),
                ]
            ):
                confluence_is_setup = True
                logger.info("Using Confluence OAuth 2.0 (3LO) authentication (Cloud-only features)")
            elif all(
                [
                    os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN"),
                    os.getenv("ATLASSIAN_OAUTH_CLOUD_ID"),
                ]
            ):
                confluence_is_setup = True
                logger.info("Using Confluence OAuth 2.0 (3LO) authentication (Cloud-only features) with provided access token")
            elif all(
                [
                    os.getenv("CONFLUENCE_USERNAME"),
                    os.getenv("CONFLUENCE_API_TOKEN"),
                ]
            ):
                confluence_is_setup = True
                logger.info("Using Confluence Cloud Basic Authentication (API Token)")
            # Minimal OAuth configuration (for user-provided tokens on Cloud)
            elif os.getenv("ATLASSIAN_OAUTH_ENABLE", "").lower() in ("true", "1", "yes"):
                confluence_is_setup = True
                logger.info("Assuming Confluence Cloud is configured via minimal OAuth (user-provided tokens)")
        # Then prioritize Server/Data Center authentication types
        else: # not is_cloud
            if os.getenv("CONFLUENCE_PERSONAL_TOKEN"):
                confluence_is_setup = True
                logger.info("Using Confluence Server/Data Center Personal Access Token (PAT)")
            elif all(
                [
                    os.getenv("CONFLUENCE_USERNAME"),
                    os.getenv("CONFLUENCE_API_TOKEN"),
                ]
            ):
                confluence_is_setup = True
                logger.info("Using Confluence Server/Data Center Basic Authentication")
            # Generic Bearer token for private servers
            elif os.getenv("CONFLUENCE_GENERIC_BEARER_ENABLE", "").lower() in ("true", "1", "yes"):
                confluence_is_setup = True
                logger.info("Confluence Server/Data Center enabled for generic Bearer token via CONFLUENCE_GENERIC_BEARER_ENABLE")
    # This block exists for cases where CONFLUENCE_URL is absent but OAuth is enabled globally (implicitly Cloud)
    elif os.getenv("ATLASSIAN_OAUTH_ENABLE", "").lower() in ("true", "1", "yes"):
        confluence_is_setup = True
        logger.info("Using Confluence minimal OAuth configuration - expecting user-provided tokens via headers (URL might be derived implicitly)")

    jira_url = os.getenv("JIRA_URL")
    jira_is_setup = False
    if jira_url:
        is_cloud = is_atlassian_cloud_url(jira_url)

        # OAuth check (highest precedence, applies to Cloud)
        if all(
            [
                os.getenv("ATLASSIAN_OAUTH_CLIENT_ID"),
                os.getenv("ATLASSIAN_OAUTH_CLIENT_SECRET"),
                os.getenv("ATLASSIAN_OAUTH_REDIRECT_URI"),
                os.getenv("ATLASSIAN_OAUTH_SCOPE"),
                os.getenv("ATLASSIAN_OAUTH_CLOUD_ID"),
            ]
        ):
            jira_is_setup = True
            logger.info(
                "Using Jira OAuth 2.0 (3LO) authentication (Cloud-only features)"
            )
        elif all(
            [
                os.getenv("ATLASSIAN_OAUTH_ACCESS_TOKEN"),
                os.getenv("ATLASSIAN_OAUTH_CLOUD_ID"),
            ]
        ):
            jira_is_setup = True
            logger.info(
                "Using Jira OAuth 2.0 (3LO) authentication (Cloud-only features) "
                "with provided access token"
            )
        elif is_cloud:  # Cloud non-OAuth
            if all(
                [
                    os.getenv("JIRA_USERNAME"),
                    os.getenv("JIRA_API_TOKEN"),
                ]
            ):
                jira_is_setup = True
                logger.info("Using Jira Cloud Basic Authentication (API Token)")
        else:  # Server/Data Center non-OAuth
            if os.getenv("JIRA_PERSONAL_TOKEN") or (
                os.getenv("JIRA_USERNAME") and os.getenv("JIRA_API_TOKEN")
            ):
                jira_is_setup = True
                logger.info(
                    "Using Jira Server/Data Center authentication (PAT or Basic Auth)"
                )
    elif os.getenv("ATLASSIAN_OAUTH_ENABLE", "").lower() in ("true", "1", "yes"):
        jira_is_setup = True
        logger.info(
            "Using Jira minimal OAuth configuration - expecting user-provided tokens via headers"
        )

    if not confluence_is_setup:
        logger.info(
            "Confluence is not configured or required environment variables are missing."
        )
    if not jira_is_setup:
        logger.info(
            "Jira is not configured or required environment variables are missing."
        )

    return {"confluence": confluence_is_setup, "jira": jira_is_setup}
