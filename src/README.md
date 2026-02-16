# Code Organization

The `src/` directory has been refactored from a single 2600+ line file into modular components for better maintainability.

## Module Structure

### Core Modules

#### `index.py` (120 lines)
- **Purpose**: Main entry point for Cloudflare Workers
- **Exports**: `on_fetch` - main request handler
- **Dependencies**: database, handlers
- **Responsibilities**:
  - Request routing
  - CORS configuration
  - Static asset serving

#### `utils.py` (62 lines)
- **Purpose**: Common utility functions
- **Exports**: 
  - `parse_pr_url()` - Parse GitHub PR URLs
  - `parse_repo_url()` - Parse GitHub repository URLs
  - `parse_github_timestamp()` - Parse ISO 8601 timestamps
- **Dependencies**: None (stdlib only)
- **Responsibilities**:
  - URL parsing and validation
  - Timestamp parsing

#### `cache.py` (281 lines)
- **Purpose**: Caching and rate limiting
- **Exports**:
  - Rate limiting functions
  - Readiness cache management
  - Timeline cache management
- **Dependencies**: database (lazy imports)
- **Responsibilities**:
  - Application-level rate limiting (10 req/min per IP)
  - In-memory caching for readiness results (10 min TTL)
  - In-memory caching for timeline data (30 min TTL)
  - Cache invalidation

#### `database.py` (441 lines)
- **Purpose**: Database operations
- **Exports**:
  - `get_db()` - Get database connection
  - `init_database_schema()` - Initialize/migrate schema
  - `upsert_pr()` - Insert or update PR records
  - Readiness data CRUD operations
- **Dependencies**: None (standalone)
- **Responsibilities**:
  - D1 database connection management
  - Schema initialization and migrations
  - PR CRUD operations
  - Readiness data persistence

#### `github_api.py` (372 lines)
- **Purpose**: GitHub API interactions
- **Exports**:
  - `fetch_pr_data()` - Fetch PR details with parallel requests
  - `fetch_paginated_data()` - Handle GitHub API pagination
  - `fetch_pr_timeline_data()` - Fetch complete PR timeline
  - `build_pr_timeline()` - Build unified chronological timeline
- **Dependencies**: cache, utils
- **Responsibilities**:
  - GitHub API communication
  - Pagination handling
  - Timeline data aggregation
  - Response transformation

#### `analysis.py` (369 lines)
- **Purpose**: PR analysis and scoring
- **Exports**:
  - `analyze_review_progress()` - Analyze feedback loops
  - `classify_review_health()` - Classify review health
  - `calculate_ci_confidence()` - Calculate CI score
  - `calculate_pr_readiness()` - Calculate overall readiness
- **Dependencies**: None (stdlib only)
- **Responsibilities**:
  - Review progress tracking
  - Feedback loop detection
  - Response rate calculation
  - CI confidence scoring
  - Overall readiness calculation

#### `handlers.py` (1111 lines)
- **Purpose**: API endpoint handlers
- **Exports**: All `handle_*` functions
- **Dependencies**: All other modules
- **Responsibilities**:
  - HTTP request handling
  - Business logic orchestration
  - Response formatting
  - Error handling

## Import Dependencies

```
index.py
├── database (init_database_schema)
└── handlers (all handle_* functions)

handlers.py
├── utils (parse_pr_url, parse_repo_url)
├── database (get_db, upsert_pr)
├── github_api (fetch_pr_data, fetch_paginated_data, etc.)
├── analysis (analyze_review_progress, classify_review_health, etc.)
└── cache (all cache functions)

github_api.py
├── cache (get_timeline_cache, set_timeline_cache)
└── utils (parse_github_timestamp)

cache.py
└── database (lazy imports: load_readiness_from_db, etc.)

database.py
└── (no local dependencies)

analysis.py
└── (no local dependencies)

utils.py
└── (no local dependencies)
```

## Benefits of This Structure

1. **Maintainability**: Each module has a single, clear responsibility
2. **Testability**: Modules can be tested independently
3. **Readability**: Smaller files are easier to understand
4. **Reusability**: Functions are grouped by purpose
5. **Scalability**: Easy to add new features to appropriate modules

## File Sizes

- Original: 1 file × 2635 lines = 2635 lines
- Refactored: 7 files × 394 lines (avg) = 2756 lines (+121 lines for module docstrings/structure)

The slight increase in total lines is due to:
- Module-level docstrings (documentation)
- Import statements (explicit dependencies)
- Better code organization (some whitespace for readability)
