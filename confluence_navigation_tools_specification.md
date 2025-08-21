# MCP Atlassian Confluence Navigation Tools - Technical Specifications

## Overview

This document provides comprehensive technical specifications for implementing 6 core navigation tools and additional enhanced navigation functionality for the MCP Atlassian Confluence server. The specifications follow established project patterns analyzed from the existing codebase and memory bank findings.

## Table of Contents

1. [Core Navigation Tools](#core-navigation-tools)
   - [get_space_root_pages](#1-get_space_root_pages)
   - [get_page_siblings](#2-get_page_siblings) 
   - [get_page_breadcrumbs](#3-get_page_breadcrumbs)
   - [get_page_descendants](#4-get_page_descendants)
   - [get_page_by_path](#5-get_page_by_path)
   - [get_space_pages_flat](#6-get_space_pages_flat)
2. [Enhanced Navigation Tools](#enhanced-navigation-tools)
3. [Server Tool Definitions](#server-tool-definitions)
4. [Data Models](#data-models)
5. [Implementation Guidelines](#implementation-guidelines)
6. [Testing Strategy](#testing-strategy)

---

## Core Navigation Tools

### 1. get_space_root_pages

**Purpose**: Find entry points for navigation in a space by retrieving all top-level pages (pages with no parent).

#### Function Signature
```python
def get_space_root_pages(
    self,
    space_key: str,
    start: int = 0,
    limit: int = 25,
    expand: str = "version",
    *,
    convert_to_markdown: bool = True,
) -> list[ConfluencePage]:
```

#### Parameters
- **space_key** (required): The key of the space to get root pages from
- **start** (optional): Starting index for pagination (default: 0)
- **limit** (optional): Maximum number of pages to return (1-50, default: 25)
- **expand** (optional): Fields to expand in response (default: "version")
- **convert_to_markdown** (keyword-only): Content format flag (default: True)

#### Return Type
`list[ConfluencePage]` - List of page models representing root-level pages

#### API Implementation
**Primary Method**: CQL query to find pages without ancestors
```python
cql = f'space="{space_key}" AND ancestor is EMPTY'
results = self.confluence.cql(cql=cql, start=start, limit=limit)
```

**Fallback Method**: REST API with depth filter
```
GET /rest/api/content?spaceKey={space_key}&depth=root&start={start}&limit={limit}&expand={expand}
```

#### Error Handling
- **Invalid space key**: Return empty list with warning log
- **Authentication errors**: Raise `MCPAtlassianAuthenticationError`
- **API errors**: Log error and return empty list
- **CQL not supported**: Fallback to REST API approach

#### Performance Considerations
- Use CQL for efficient root page discovery
- Implement pagination for large spaces
- Cache space metadata for repeated calls
- Process content only if `expand` includes body

#### Mixin Assignment
**SpacesMixin** - Space-level navigation operation

---

### 2. get_page_siblings

**Purpose**: Navigate horizontally at the same level by getting pages with the same parent.

#### Function Signature
```python
def get_page_siblings(
    self,
    page_id: str,
    include_self: bool = False,
    start: int = 0,
    limit: int = 25,
    expand: str = "version",
    *,
    convert_to_markdown: bool = True,
) -> list[ConfluencePage]:
```

#### Parameters
- **page_id** (required): ID of the page to find siblings for
- **include_self** (optional): Whether to include the page itself (default: False)
- **start** (optional): Starting index for pagination (default: 0)
- **limit** (optional): Maximum number of pages to return (1-50, default: 25)
- **expand** (optional): Fields to expand in response (default: "version")
- **convert_to_markdown** (keyword-only): Content format flag (default: True)

#### Return Type
`list[ConfluencePage]` - List of sibling pages

#### API Implementation
**Step 1**: Get the target page's parent information
```python
page = self.confluence.get_page_by_id(page_id, expand="ancestors")
```

**Step 2**: If page has no parent (root level), use CQL to find other root pages:
```python
space_key = page.get("space", {}).get("key")
cql = f'space="{space_key}" AND ancestor is EMPTY'
```

**Step 3**: If page has parent, get parent's children:
```python
parent_id = page["ancestors"][-1]["id"]  # Last ancestor is immediate parent
children = self.confluence.get_page_child_by_type(
    page_id=parent_id, type="page", start=start, limit=limit, expand=expand
)
```

**Step 4**: Filter out the original page if `include_self=False`

#### Error Handling
- **Page not found**: Return empty list with warning
- **No siblings**: Return empty list (normal case)
- **Authentication errors**: Raise `MCPAtlassianAuthenticationError`
- **API errors**: Log and return empty list

#### Performance Considerations
- Single API call for parent lookup
- Efficient child enumeration
- Client-side filtering for self exclusion

#### Mixin Assignment
**PagesMixin** - Page-level navigation operation

---

### 3. get_page_breadcrumbs

**Purpose**: Show current location context with full path from space root to target page.

#### Function Signature
```python
def get_page_breadcrumbs(
    self,
    page_id: str,
    include_space: bool = True,
    reverse_order: bool = False,
) -> list[dict[str, Any]]:
```

#### Parameters
- **page_id** (required): ID of the page to get breadcrumbs for
- **include_space** (optional): Whether to include space as first breadcrumb (default: True)
- **reverse_order** (optional): Return path from page to root instead (default: False)

#### Return Type
`list[dict[str, Any]]` - Breadcrumb trail with each item containing:
```python
{
    "id": str,
    "title": str,
    "type": str,  # "space" or "page"
    "url": str | None,
    "level": int,  # 0=space, 1=root page, 2=child, etc.
}
```

#### API Implementation
**Primary Method**: Use existing `get_page_ancestors()` method
```python
page = self.confluence.get_page_by_id(page_id, expand="ancestors,space")
ancestors = page.get("ancestors", [])
space_info = page.get("space", {})
```

**Processing**:
1. Build breadcrumb list starting with space (if `include_space=True`)
2. Add ancestors in hierarchical order (root to immediate parent)
3. Add target page as final breadcrumb
4. Reverse if `reverse_order=True`
5. Calculate level numbers and construct URLs

#### Error Handling
- **Page not found**: Return empty list
- **Authentication errors**: Raise `MCPAtlassianAuthenticationError`
- **Missing space info**: Include generic space breadcrumb

#### Performance Considerations
- Single API call to get page with ancestors
- Client-side processing for breadcrumb construction
- URL generation using existing patterns

#### Mixin Assignment
**PagesMixin** - Page-level navigation operation

---

### 4. get_page_descendants

**Purpose**: Deep subtree exploration with recursive traversal of all nested child pages.

#### Function Signature
```python
def get_page_descendants(
    self,
    page_id: str,
    max_depth: int | None = None,
    include_content: bool = False,
    expand: str = "version",
    *,
    convert_to_markdown: bool = True,
) -> list[ConfluencePage]:
```

#### Parameters
- **page_id** (required): ID of the root page to traverse from
- **max_depth** (optional): Maximum recursion depth (None for unlimited)
- **include_content** (optional): Whether to fetch page content (default: False)
- **expand** (optional): Fields to expand in response (default: "version")
- **convert_to_markdown** (keyword-only): Content format flag (default: True)

#### Return Type
`list[ConfluencePage]` - Flattened list of all descendant pages in breadth-first order

#### API Implementation
**Recursive Traversal Algorithm**:
```python
def _collect_descendants(page_id: str, current_depth: int = 0) -> list[dict]:
    if max_depth is not None and current_depth >= max_depth:
        return []
    
    children = self.confluence.get_page_child_by_type(
        page_id=page_id, type="page", expand=expand
    )
    
    descendants = []
    for child in children.get("results", []):
        descendants.append(child)
        # Recursive call for grandchildren
        grand_descendants = _collect_descendants(child["id"], current_depth + 1)
        descendants.extend(grand_descendants)
    
    return descendants
```

#### Error Handling
- **Page not found**: Return empty list
- **Circular references**: Implement visited set to prevent infinite loops
- **Max depth exceeded**: Stop traversal and log warning
- **API errors**: Log and continue with partial results

#### Performance Considerations
- **Depth limiting**: Essential for large hierarchies
- **Batch processing**: Consider chunking for very large trees
- **Content loading**: Only fetch content if specifically requested
- **Caching**: Cache intermediate results for common subtrees

#### Mixin Assignment
**PagesMixin** - Page-level navigation operation

---

### 5. get_page_by_path

**Purpose**: Intuitive path-based navigation using hierarchical paths like "Space/Parent/Child".

#### Function Signature
```python
def get_page_by_path(
    self,
    path: str,
    *,
    convert_to_markdown: bool = True,
) -> ConfluencePage | None:
```

#### Parameters
- **path** (required): Hierarchical path string (e.g., "SPACE/Parent Page/Child Page")
- **convert_to_markdown** (keyword-only): Content format flag (default: True)

#### Return Type
`ConfluencePage | None` - The target page or None if not found

#### API Implementation
**Path Parsing and Resolution**:
```python
def parse_path(path: str) -> tuple[str, list[str]]:
    """Parse path into space key and page titles."""
    parts = [part.strip() for part in path.split("/") if part.strip()]
    if len(parts) < 2:
        raise ValueError("Path must include at least space and page name")
    return parts[0], parts[1:]

def resolve_path(space_key: str, page_titles: list[str]) -> ConfluencePage | None:
    """Resolve path by traversing hierarchy."""
    # Start with root page
    current_page = self.get_page_by_title(space_key, page_titles[0])
    if not current_page:
        return None
    
    # Traverse down the hierarchy
    for title in page_titles[1:]:
        children = self.get_page_children(current_page.id, convert_to_markdown=False)
        current_page = None
        for child in children:
            if child.title == title:
                current_page = child
                break
        if not current_page:
            return None
    
    # Get final page with content if found
    return self.get_page_content(current_page.id, convert_to_markdown=convert_to_markdown)
```

#### Error Handling
- **Invalid path format**: Raise `ValueError` with clear message
- **Space not found**: Return None with warning log
- **Page not found in path**: Return None with informative log
- **Ambiguous titles**: Return first match with warning about duplicates

#### Performance Considerations
- **Early termination**: Stop on first failed lookup
- **Caching**: Cache intermediate page lookups
- **Batch optimization**: Consider bulk title lookups for performance

#### Mixin Assignment
**PagesMixin** - Page-level navigation operation

---

### 6. get_space_pages_flat

**Purpose**: Complete space overview without pagination - get all pages in a space efficiently.

#### Function Signature
```python
def get_space_pages_flat(
    self,
    space_key: str,
    include_content: bool = False,
    expand: str = "version",
    max_pages: int = 1000,
    *,
    convert_to_markdown: bool = True,
) -> list[ConfluencePage]:
```

#### Parameters
- **space_key** (required): The key of the space to get all pages from
- **include_content** (optional): Whether to fetch page content (default: False)
- **expand** (optional): Fields to expand in response (default: "version")
- **max_pages** (optional): Safety limit for very large spaces (default: 1000)
- **convert_to_markdown** (keyword-only): Content format flag (default: True)

#### Return Type
`list[ConfluencePage]` - Complete list of all pages in the space

#### API Implementation
**Efficient Pagination Strategy**:
```python
def get_all_pages_paginated(space_key: str) -> list[dict]:
    """Get all pages using automatic pagination."""
    all_pages = []
    start = 0
    limit = 50  # Optimal batch size
    
    while len(all_pages) < max_pages:
        batch = self.confluence.get_all_pages_from_space(
            space=space_key, start=start, limit=limit, expand=expand
        )
        
        if not batch:  # No more pages
            break
            
        all_pages.extend(batch)
        
        if len(batch) < limit:  # Last batch
            break
            
        start += limit
    
    return all_pages[:max_pages]  # Respect max_pages limit
```

#### Error Handling
- **Space not found**: Return empty list with warning
- **Max pages exceeded**: Log warning and return truncated results
- **Authentication errors**: Raise `MCPAtlassianAuthenticationError`
- **API errors**: Log and return partial results

#### Performance Considerations
- **Batch size optimization**: Use 50-page batches for efficiency
- **Memory management**: Consider streaming for very large spaces
- **Content loading**: Only process content if specifically requested
- **Progress tracking**: Log progress for large operations

#### Mixin Assignment
**SpacesMixin** - Space-level navigation operation

---

## Enhanced Navigation Tools

### 7. get_space_hierarchy

**Purpose**: Get complete hierarchical tree structure of a space.

#### Function Signature
```python
def get_space_hierarchy(
    self,
    space_key: str,
    max_depth: int = 5,
    include_metadata: bool = True,
) -> dict[str, Any]:
```

#### Return Type
Nested dictionary representing the complete space hierarchy:
```python
{
    "space": {"key": str, "name": str},
    "tree": [
        {
            "page": {"id": str, "title": str, "url": str},
            "level": int,
            "children": [...],  # Recursive structure
            "metadata": {...}  # Optional metadata
        }
    ],
    "stats": {"total_pages": int, "max_depth": int}
}
```

### 8. find_pages_by_pattern

**Purpose**: Advanced search with title patterns and content filters.

#### Function Signature
```python
def find_pages_by_pattern(
    self,
    pattern: str,
    space_keys: list[str] | None = None,
    search_type: str = "title",  # "title", "content", "both"
    case_sensitive: bool = False,
    limit: int = 50,
) -> list[ConfluencePage]:
```

### 9. get_page_navigation_context

**Purpose**: Get comprehensive navigation context for a page.

#### Function Signature
```python
def get_page_navigation_context(
    self,
    page_id: str,
) -> dict[str, Any]:
```

#### Return Type
Complete navigation context:
```python
{
    "current_page": ConfluencePage,
    "breadcrumbs": list[dict],
    "siblings": list[ConfluencePage],
    "children": list[ConfluencePage],
    "parent": ConfluencePage | None,
    "space_root_pages": list[ConfluencePage]
}
```

### 10. batch_page_operations

**Purpose**: Efficient batch operations for multiple pages.

#### Function Signature
```python
def batch_get_pages(
    self,
    page_ids: list[str],
    include_content: bool = False,
    *,
    convert_to_markdown: bool = True,
) -> dict[str, ConfluencePage | None]:
```

---

## Server Tool Definitions

All server tools follow the established pattern with `@confluence_mcp.tool(tags={"confluence", "read"})` decorator.

### get_space_root_pages Tool

```python
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
            description="Maximum number of pages to return (1-50)",
            default=25,
            ge=1,
            le=50,
        ),
    ] = 25,
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
    for navigation in a space.
    
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
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    
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
        result = {"error": f"Failed to get root pages: {e}"}
    
    return json.dumps(result, indent=2, ensure_ascii=False)
```

### get_page_siblings Tool

```python
@confluence_mcp.tool(tags={"confluence", "read"})
async def get_page_siblings(
    ctx: Context,
    page_id: Annotated[
        str,
        Field(
            description="The ID of the page to find siblings for"
        ),
    ],
    include_self: Annotated[
        bool,
        Field(
            description="Whether to include the page itself in the results",
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
            default=25,
            ge=1,
            le=50,
        ),
    ] = 25,
    expand: Annotated[
        str,
        Field(
            description="Fields to expand in the response",
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
            description="Whether to convert page content to markdown",
            default=True,
        ),
    ] = True,
) -> str:
    """Get sibling pages (pages with the same parent) of a specific page.
    
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
    """
    confluence_fetcher = await get_confluence_fetcher(ctx)
    
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
        result = {"error": f"Failed to get page siblings: {e}"}
    
    return json.dumps(result, indent=2, ensure_ascii=False)
```

### Additional Tool Specifications

Similar patterns apply for:
- `get_page_breadcrumbs` - Returns breadcrumb trail as JSON
- `get_page_descendants` - Returns flattened descendant list
- `get_page_by_path` - Returns single page or error
- `get_space_pages_flat` - Returns complete page list with progress info

---

## Data Models

### Navigation-Specific Models

#### BreadcrumbItem
```python
class BreadcrumbItem(ApiModel):
    """Model representing a single breadcrumb item."""
    
    id: str
    title: str
    type: str  # "space" or "page"
    url: str | None = None
    level: int
    
    @classmethod
    def from_space(cls, space: ConfluenceSpace, level: int = 0) -> "BreadcrumbItem":
        """Create breadcrumb from space data."""
        return cls(
            id=space.id,
            title=space.name,
            type="space",
            url=None,  # Spaces don't have direct URLs
            level=level,
        )
    
    @classmethod
    def from_page(cls, page: ConfluencePage, level: int) -> "BreadcrumbItem":
        """Create breadcrumb from page data."""
        return cls(
            id=page.id,
            title=page.title,
            type="page",
            url=page.url,
            level=level,
        )
```

#### NavigationContext
```python
class NavigationContext(ApiModel):
    """Model representing complete navigation context for a page."""
    
    current_page: ConfluencePage
    breadcrumbs: list[BreadcrumbItem] = Field(default_factory=list)
    siblings: list[ConfluencePage] = Field(default_factory=list)
    children: list[ConfluencePage] = Field(default_factory=list)
    parent: ConfluencePage | None = None
    space_info: ConfluenceSpace | None = None
    
    def to_simplified_dict(self) -> dict[str, Any]:
        """Convert to simplified dictionary."""
        return {
            "current_page": self.current_page.to_simplified_dict(),
            "breadcrumbs": [bc.to_simplified_dict() for bc in self.breadcrumbs],
            "siblings": [page.to_simplified_dict() for page in self.siblings],
            "children": [page.to_simplified_dict() for page in self.children],
            "parent": self.parent.to_simplified_dict() if self.parent else None,
            "space": self.space_info.to_simplified_dict() if self.space_info else None,
        }
```

### Extended ConfluencePage Model

Add navigation-specific properties to the existing `ConfluencePage` model:

```python
# Add to existing ConfluencePage class
@property
def has_children(self) -> bool:
    """Check if page has child pages."""
    return bool(self.children.get("page", {}).get("size", 0) > 0)

@property
def is_root_page(self) -> bool:
    """Check if this is a root page (no ancestors)."""
    return len(self.ancestors) == 0

@property
def depth_level(self) -> int:
    """Get the depth level of this page (0 = root page)."""
    return len(self.ancestors)

@property
def parent_id(self) -> str | None:
    """Get the immediate parent page ID."""
    return self.ancestors[-1]["id"] if self.ancestors else None
```

---

## Implementation Guidelines

### Mixin Organization

#### SpacesMixin Extensions
Add these methods to `src/mcp_atlassian/confluence/spaces.py`:
- `get_space_root_pages()` - Core space navigation
- `get_space_pages_flat()` - Complete space enumeration  
- `get_space_hierarchy()` - Enhanced tree structure

#### PagesMixin Extensions  
Add these methods to `src/mcp_atlassian/confluence/pages.py`:
- `get_page_siblings()` - Horizontal navigation
- `get_page_breadcrumbs()` - Path context
- `get_page_descendants()` - Deep traversal
- `get_page_by_path()` - Path-based lookup
- `get_page_navigation_context()` - Complete context

### Code Organization

#### File Structure
```
src/mcp_atlassian/confluence/
├── spaces.py          # SpacesMixin extensions
├── pages.py           # PagesMixin extensions  
├── navigation.py      # New: Navigation utilities and helpers
└── client.py          # Unchanged: Base client

src/mcp_atlassian/models/confluence/
├── navigation.py      # New: Navigation-specific models
├── page.py           # Extended: Add navigation properties
└── space.py          # Unchanged: Existing space models

src/mcp_atlassian/servers/
└── confluence.py     # Add new tool definitions
```

#### New Navigation Utilities Module
Create `src/mcp_atlassian/confluence/navigation.py`:
```python
"""Navigation utilities and helper functions."""

from typing import Any
from ..models.confluence import ConfluencePage, ConfluenceSpace


class NavigationHelper:
    """Helper class for navigation operations."""
    
    @staticmethod
    def build_breadcrumb_trail(
        page: dict[str, Any], 
        include_space: bool = True,
        reverse_order: bool = False,
    ) -> list[dict[str, Any]]:
        """Build breadcrumb trail from page data."""
        # Implementation here
        pass
    
    @staticmethod
    def filter_pages_by_criteria(
        pages: list[ConfluencePage],
        criteria: dict[str, Any],
    ) -> list[ConfluencePage]:
        """Filter pages based on various criteria."""
        # Implementation here
        pass
    
    @staticmethod
    def calculate_tree_statistics(hierarchy: dict[str, Any]) -> dict[str, int]:
        """Calculate statistics for a page hierarchy."""
        # Implementation here
        pass
```

### Dependency Relationships

#### Tool Dependencies
```
get_page_siblings → get_page_ancestors (from existing PagesMixin)
get_page_breadcrumbs → get_page_ancestors (from existing PagesMixin)  
get_page_descendants → get_page_children (from existing PagesMixin)
get_page_by_path → get_page_by_title + get_page_children (from existing PagesMixin)
get_space_pages_flat → get_space_pages (from existing PagesMixin)
get_space_root_pages → CQL search (from existing SearchMixin)
```

#### Model Dependencies
```
BreadcrumbItem → ConfluencePage, ConfluenceSpace
NavigationContext → ConfluencePage, BreadcrumbItem
Extended ConfluencePage → existing ConfluencePage model
```

### Integration with Existing Preprocessing

#### Content Processing
All navigation tools support the existing content conversion pipeline:
```python
# In each method that returns ConfluencePage objects
if convert_to_markdown and content:
    processed_html, processed_markdown = self.preprocessor.process_html_content(
        content, space_key=space_key, confluence_client=self.confluence
    )
    page_content = processed_markdown if convert_to_markdown else processed_html
```

#### Authentication Integration
Support both v1 and v2 APIs based on authentication type:
```python
# Check auth type for API version selection
v2_adapter = self._v2_adapter
if v2_adapter:
    # Use v2 API for OAuth
    response = v2_adapter.get_page(...)
else:
    # Use v1 API for token/basic auth
    response = self.confluence.get_page_by_id(...)
```

---

## Testing Strategy

### Unit Test Structure

#### Test Organization
```
tests/unit/confluence/
├── test_spaces_navigation.py    # New: SpacesMixin navigation tests
├── test_pages_navigation.py     # New: PagesMixin navigation tests
├── test_navigation_models.py    # New: Navigation model tests
├── test_navigation_helpers.py   # New: Navigation utility tests
└── test_navigation_server.py    # New: Server tool tests
```

#### Mock Data Requirements

#### Hierarchical Test Data
```python
# In tests/fixtures/confluence_mocks.py
MOCK_HIERARCHICAL_PAGES = {
    "space_key": "TEST",
    "root_pages": [
        {
            "id": "root1",
            "title": "Root Page 1", 
            "ancestors": [],
            "children": ["child1", "child2"]
        },
        {
            "id": "root2", 
            "title": "Root Page 2",
            "ancestors": [],
            "children": ["child3"]
        }
    ],
    "child_pages": [
        {
            "id": "child1",
            "title": "Child Page 1",
            "ancestors": [{"id": "root1", "title": "Root Page 1"}],
            "children": ["grandchild1"]
        },
        # ... more child pages
    ],
    "grandchild_pages": [
        {
            "id": "grandchild1", 
            "title": "Grandchild Page 1",
            "ancestors": [
                {"id": "root1", "title": "Root Page 1"},
                {"id": "child1", "title": "Child Page 1"}
            ],
            "children": []
        }
    ]
}
```

#### Navigation-Specific Fixtures
```python
# In tests/unit/confluence/conftest.py

@pytest.fixture
def mock_hierarchical_space():
    """Provide hierarchical test data."""
    return MOCK_HIERARCHICAL_PAGES

@pytest.fixture  
def navigation_test_pages():
    """Factory for creating navigation test scenarios."""
    def _create_scenario(scenario: str):
        scenarios = {
            "simple_hierarchy": {...},
            "deep_nesting": {...},
            "sibling_groups": {...},
            "orphaned_pages": {...}
        }
        return scenarios.get(scenario, {})
    return _create_scenario

@pytest.fixture
def spaces_navigation_mixin(mock_config, mock_atlassian_confluence, mock_preprocessor):
    """Create SpacesMixin with navigation methods for testing."""
    with patch("mcp_atlassian.confluence.spaces.ConfluenceClient.__init__") as mock_init:
        mock_init.return_value = None
        mixin = SpacesMixin()
        mixin.confluence = mock_atlassian_confluence  
        mixin.config = mock_config
        mixin.preprocessor = mock_preprocessor
        return mixin

@pytest.fixture
def pages_navigation_mixin(mock_config, mock_atlassian_confluence, mock_preprocessor):
    """Create PagesMixin with navigation methods for testing."""
    with patch("mcp_atlassian.confluence.pages.ConfluenceClient.__init__") as mock_init:
        mock_init.return_value = None
        mixin = PagesMixin()
        mixin.confluence = mock_atlassian_confluence
        mixin.config = mock_config  
        mixin.preprocessor = mock_preprocessor
        return mixin
```

### Test Case Categories

#### Core Functionality Tests
```python
class TestGetSpaceRootPages:
    """Test space root page discovery."""
    
    def test_get_root_pages_success(self, spaces_navigation_mixin):
        """Test successful root page retrieval."""
        # Test implementation
        pass
    
    def test_get_root_pages_empty_space(self, spaces_navigation_mixin):
        """Test behavior with empty space."""
        pass
    
    def test_get_root_pages_pagination(self, spaces_navigation_mixin):
        """Test pagination functionality."""
        pass
    
    def test_get_root_pages_invalid_space(self, spaces_navigation_mixin):
        """Test error handling for invalid space."""
        pass

class TestGetPageSiblings:
    """Test sibling page discovery."""
    
    def test_get_siblings_with_parent(self, pages_navigation_mixin):
        """Test siblings for page with parent."""
        pass
    
    def test_get_siblings_root_page(self, pages_navigation_mixin):
        """Test siblings for root page."""
        pass
    
    def test_get_siblings_include_self(self, pages_navigation_mixin):
        """Test include_self parameter."""
        pass
    
    def test_get_siblings_no_siblings(self, pages_navigation_mixin):
        """Test only child scenario."""
        pass
```

#### Error Handling Tests
```python
class TestNavigationErrorHandling:
    """Test error scenarios across navigation tools."""
    
    @pytest.mark.parametrize("method_name,args", [
        ("get_space_root_pages", ("INVALID",)),
        ("get_page_siblings", ("invalid_id",)),
        ("get_page_breadcrumbs", ("invalid_id",)),
        # ... more methods
    ])
    def test_invalid_input_handling(self, navigation_mixin, method_name, args):
        """Test handling of invalid inputs."""
        pass
    
    def test_authentication_error_propagation(self, navigation_mixin):
        """Test auth error handling."""
        pass
    
    def test_api_timeout_handling(self, navigation_mixin):
        """Test API timeout scenarios."""
        pass
```

#### Performance and Edge Case Tests
```python
class TestNavigationPerformance:
    """Test performance characteristics."""
    
    def test_large_space_pagination(self, spaces_navigation_mixin):
        """Test behavior with large spaces."""
        pass
    
    def test_deep_hierarchy_limits(self, pages_navigation_mixin):
        """Test deep nesting scenarios.""" 
        pass
    
    def test_circular_reference_detection(self, pages_navigation_mixin):
        """Test circular reference handling."""
        pass
```

#### Integration Tests
```python
class TestNavigationIntegration:
    """Test tool integration."""
    
    def test_breadcrumb_to_sibling_workflow(self, navigation_mixin):
        """Test common navigation workflow."""
        pass
    
    def test_hierarchy_exploration_workflow(self, navigation_mixin):
        """Test tree exploration workflow.""" 
        pass
```

### Server Tool Testing

#### Server Test Pattern
```python
class TestConfluenceNavigationServer:
    """Test server tool implementations."""
    
    @pytest.mark.asyncio
    async def test_get_space_root_pages_tool(self, mock_context):
        """Test get_space_root_pages server tool."""
        # Mock the confluence_fetcher
        mock_fetcher = MagicMock()
        mock_fetcher.get_space_root_pages.return_value = [
            ConfluencePageFactory.create(page_id="root1", title="Root 1"),
            ConfluencePageFactory.create(page_id="root2", title="Root 2"),
        ]
        
        with patch("mcp_atlassian.servers.confluence.get_confluence_fetcher") as mock_get:
            mock_get.return_value = mock_fetcher
            
            # Test the server tool
            result = await get_space_root_pages(
                ctx=mock_context,
                space_key="TEST",
                start=0,
                limit=25
            )
            
            # Verify result
            result_data = json.loads(result)
            assert result_data["space_key"] == "TEST"
            assert len(result_data["results"]) == 2
            assert result_data["results"][0]["id"] == "root1"
```

### Mock Data Integration

#### Extended Mock Responses
```python
# Extend existing fixtures/confluence_mocks.py

MOCK_ROOT_PAGES_RESPONSE = {
    "results": [
        {
            "id": "root123",
            "title": "Root Page",
            "type": "page", 
            "space": {"key": "TEST", "name": "Test Space"},
            "ancestors": [],  # No ancestors = root page
            "version": {"number": 1},
        }
    ],
    "size": 1,
    "start": 0,
    "limit": 25,
}

MOCK_SIBLING_PAGES_RESPONSE = {
    "results": [
        {
            "id": "sibling1",
            "title": "Sibling Page 1", 
            "ancestors": [{"id": "parent123", "title": "Parent Page"}],
        },
        {
            "id": "sibling2", 
            "title": "Sibling Page 2",
            "ancestors": [{"id": "parent123", "title": "Parent Page"}],
        }
    ]
}
```

### Regression Testing

#### Test Coverage Requirements
- **Minimum 95% line coverage** for all navigation methods
- **100% branch coverage** for error handling paths  
- **Integration test coverage** for all server tools
- **Performance regression tests** for large data sets

#### Continuous Integration
- **Automated test execution** on all PRs
- **Performance benchmarking** for navigation operations
- **Memory usage validation** for large hierarchy operations
- **Cross-authentication testing** (OAuth vs Token vs Basic)

---

## Summary

This specification provides comprehensive technical guidance for implementing 6 core navigation tools plus enhanced functionality for the MCP Atlassian Confluence server. The design follows established project patterns while addressing the identified gaps in navigation capabilities.

### Key Implementation Priorities

1. **Phase 1**: Core navigation tools (get_space_root_pages, get_page_siblings, get_page_breadcrumbs)
2. **Phase 2**: Advanced tools (get_page_descendants, get_page_by_path, get_space_pages_flat)  
3. **Phase 3**: Enhanced tools and optimizations

### Success Criteria

- ✅ All tools follow established project patterns
- ✅ Comprehensive error handling and logging
- ✅ Full test coverage with realistic scenarios
- ✅ Performance optimization for large spaces
- ✅ Consistent API documentation and examples
- ✅ Integration with existing content preprocessing
- ✅ Support for both v1 and v2 Confluence APIs

The specification provides a solid foundation for implementation while maintaining consistency with the existing MCP Atlassian codebase architecture and patterns.