"""Configuration module for the Confluence client."""

import logging
import os
from dataclasses import dataclass
from typing import Literal

from ..utils.env import get_custom_headers, is_env_ssl_verify
from ..utils.oauth import (
    BYOAccessTokenOAuthConfig,
    OAuthConfig,
    get_oauth_config_from_env,
)
from ..utils.urls import is_atlassian_cloud_url


@dataclass
class ConfluenceConfig:
    """Confluence API configuration.

    Handles authentication for Confluence Cloud and Server/Data Center:
    - Cloud: username/API token (basic auth) or OAuth 2.0 (3LO)
    - Server/DC: personal access token or basic auth
    """

    url: str  # Base URL for Confluence
    auth_type: Literal["basic", "pat", "oauth", "bearer_token"]  # Authentication type
    username: str | None = None  # Email or username
    api_token: str | None = None  # API token used as password
    personal_token: str | None = None  # Personal access token (Server/DC)
    bearer_token: str | None = None  # Generic Bearer token for private servers
    oauth_config: OAuthConfig | BYOAccessTokenOAuthConfig | None = None
    ssl_verify: bool = True  # Whether to verify SSL certificates
    spaces_filter: str | None = None  # List of space keys to filter searches
    http_proxy: str | None = None  # HTTP proxy URL
    https_proxy: str | None = None  # HTTPS proxy URL
    no_proxy: str | None = None  # Comma-separated list of hosts to bypass proxy
    socks_proxy: str | None = None  # SOCKS proxy URL (optional)
    custom_headers: dict[str, str] | None = None  # Custom HTTP headers

    @property
    def is_cloud(self) -> bool:
        """Check if this is a cloud instance.

        Returns:
            True if this is a cloud instance (atlassian.net), False otherwise.
            Localhost URLs are always considered non-cloud (Server/Data Center).
        """
        # Multi-Cloud OAuth mode: URL might be None, but we use api.atlassian.com
        if (
            self.auth_type == "oauth"
            and self.oauth_config
            and self.oauth_config.cloud_id
        ):
            # OAuth with cloud_id uses api.atlassian.com which is always Cloud
            return True

        # For other auth types, check the URL
        return is_atlassian_cloud_url(self.url) if self.url else False

    @property
    def verify_ssl(self) -> bool:
        """Compatibility property for old code.

        Returns:
            The ssl_verify value
        """
        return self.ssl_verify

    @classmethod
    def from_env(cls) -> "ConfluenceConfig":
        """Create configuration from environment variables.

        Returns:
            ConfluenceConfig with values from environment variables

        Raises:
            ValueError: If any required environment variable is missing
        """
        url = os.getenv("CONFLUENCE_URL")
        if not url and not os.getenv("ATLASSIAN_OAUTH_ENABLE"):
            error_msg = "Missing required CONFLUENCE_URL environment variable"
            raise ValueError(error_msg)

        # Determine authentication type based on available environment variables
        username = os.getenv("CONFLUENCE_USERNAME")
        api_token = os.getenv("CONFLUENCE_API_TOKEN")
        personal_token = os.getenv("CONFLUENCE_PERSONAL_TOKEN")

        # Check for OAuth configuration
        oauth_config = get_oauth_config_from_env()
        auth_type = None

        # Use the shared utility function directly
        is_cloud = is_atlassian_cloud_url(url)

        # Determine authentication type based on environment variables and server type
        # Prioritize OAuth if explicitly enabled and configured, then PAT, then Basic, then Generic Bearer
        if oauth_config and is_cloud:  # OAuth only makes sense for cloud
            auth_type = "oauth"
        elif personal_token and not is_cloud:  # PAT is primarily for Server/DC
            auth_type = "pat"
        elif username and api_token:  # Basic Auth can be for both Cloud and Server/DC
            auth_type = "basic"
        elif (
            os.getenv("CONFLUENCE_GENERIC_BEARER_ENABLE") and not is_cloud
        ):  # New generic Bearer for private servers
            auth_type = "bearer_token"
        elif is_cloud:
            error_msg = (
                "Cloud authentication requires CONFLUENCE_USERNAME and CONFLUENCE_API_TOKEN, "
                "or OAuth configuration (set ATLASSIAN_OAUTH_ENABLE=true and provide client credentials/cloud ID)."
            )
            raise ValueError(error_msg)
        else:
            # If none of the above specific auth types are configured, check for generic bearer token setup on non-cloud.
            if (
                url
                and os.getenv("CONFLUENCE_GENERIC_BEARER_ENABLE", "").lower()
                in ("true", "1", "yes")
                and not is_cloud
            ):
                auth_type = "bearer_token"
                logging.getLogger(
                    "mcp-atlassian.confluence.config"
                ).info(  # Added logging import
                    "Confluence configured for generic bearer token and ready to accept user-provided tokens (via request header)."
                )
            else:  # Final fallback if no valid configuration or generic bearer is not enabled/suitable
                error_msg = (
                    "Confluence URL found but no valid authentication is configured. "
                    "For Cloud: CONFLUENCE_USERNAME/CONFLUENCE_API_TOKEN or ATLASSIAN_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI/SCOPE/CLOUD_ID. "
                    "For Server/Data Center: CONFLUENCE_PERSONAL_TOKEN, CONFLUENCE_USERNAME/CONFLUENCE_API_TOKEN, "
                    "or CONFLUENCE_GENERIC_BEARER_ENABLE=true with Bearer token in requests."
                )
                raise ValueError(error_msg)

        # SSL verification
        ssl_verify = is_env_ssl_verify("CONFLUENCE_SSL_VERIFY")  # Provided env_var_name

        # Get the spaces filter if provided
        spaces_filter = os.getenv("CONFLUENCE_SPACES_FILTER")

        # Proxy settings
        http_proxy = os.getenv("CONFLUENCE_HTTP_PROXY", os.getenv("HTTP_PROXY"))
        https_proxy = os.getenv("CONFLUENCE_HTTPS_PROXY", os.getenv("HTTPS_PROXY"))
        no_proxy = os.getenv("CONFLUENCE_NO_PROXY", os.getenv("NO_PROXY"))
        socks_proxy = os.getenv("CONFLUENCE_SOCKS_PROXY", os.getenv("SOCKS_PROXY"))

        # Custom headers - service-specific only
        custom_headers = get_custom_headers("CONFLUENCE_CUSTOM_HEADERS")

        return cls(
            url=url,
            auth_type=auth_type,
            username=username,
            api_token=api_token,
            personal_token=personal_token,
            bearer_token=os.getenv("CONFLUENCE_GENERIC_BEARER_TOKEN")
            if auth_type == "bearer_token"
            else None,
            oauth_config=oauth_config,
            ssl_verify=ssl_verify,
            spaces_filter=spaces_filter,
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            no_proxy=no_proxy,
            socks_proxy=socks_proxy,
            custom_headers=custom_headers,
        )

    def is_auth_configured(self) -> bool:
        """Check if the current authentication configuration is complete and valid for making API calls.

        Returns:
            bool: True if authentication is fully configured, False otherwise.
        """
        logger = logging.getLogger("mcp-atlassian.confluence.config")
        if self.auth_type == "oauth":
            # Handle different OAuth configuration types
            if self.oauth_config:
                # Full OAuth configuration (traditional mode)
                if isinstance(self.oauth_config, OAuthConfig):
                    if (
                        self.oauth_config.client_id
                        and self.oauth_config.client_secret
                        and self.oauth_config.redirect_uri
                        and self.oauth_config.scope
                        and self.oauth_config.cloud_id
                    ):
                        return True
                    # Minimal OAuth configuration (user-provided tokens mode)
                    # This is valid if we have oauth_config but missing client credentials
                    # In this case, we expect authentication to come from user-provided headers
                    elif (
                        not self.oauth_config.client_id
                        and not self.oauth_config.client_secret
                    ):
                        logger.debug(
                            "Minimal OAuth config detected - expecting user-provided tokens via headers"
                        )
                        return True
                # Bring Your Own Access Token mode
                elif isinstance(self.oauth_config, BYOAccessTokenOAuthConfig):
                    if self.oauth_config.cloud_id and self.oauth_config.access_token:
                        return True

            # Partial configuration is invalid
            logger.warning("Incomplete OAuth configuration detected")
            return False
        elif self.auth_type == "pat":
            return bool(self.personal_token)
        elif self.auth_type == "basic":
            return bool(self.username and self.api_token)
        elif self.auth_type == "bearer_token":
            # For this mode, the global configuration only needs a URL, as the actual token comes from the request headers.
            return bool(self.url)
        logger.warning(
            f"Unknown or unsupported auth_type: {self.auth_type} in ConfluenceConfig"
        )
        return False
