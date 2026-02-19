# Mobile 403 Error Fix

## Issue Description
Mobile users were experiencing "Request failed with status 403" errors when accessing the BLT-Leaf application. This was primarily caused by aggressive rate limiting that treated all users on the same mobile carrier network as a single entity.

## Root Cause
1. **Shared IP Addresses**: Mobile users on the same cellular carrier network share a public IP address, causing them to collectively consume a single rate limit quota
2. **Low Rate Limit**: The original rate limit of 10 requests per minute per IP was too restrictive for shared mobile IPs
3. **Poor Error Handling**: The frontend didn't distinguish between different error types or provide helpful feedback to users
4. **Background Tasks**: Automatic update checks failed silently, causing confusion

## Changes Made

### 1. Increased Rate Limit Threshold
**File**: `src/cache.py`
- Increased `_READINESS_RATE_LIMIT` from 10 to 30 requests per minute
- This 3x increase provides better support for mobile users sharing IPs
- Added documentation explaining the mobile network consideration

### 2. Improved Error Handling
**File**: `public/index.html`

#### a) Main PR List Loading
- Added specific handling for HTTP 429 (rate limit exceeded)
- Added specific handling for HTTP 403 (forbidden)
- Extracts and displays `Retry-After` header value
- Shows user-friendly error messages explaining the situation

#### b) Background Update Checks
- Gracefully handles rate limiting without disrupting user experience
- Logs warnings to console instead of showing error dialogs
- Automatically retries on next check interval

#### c) Readiness Analysis
- Handles rate limiting when checking PR readiness
- Shows clear error messages with retry time
- Distinguishes between rate limiting and other errors

#### d) PR Refresh
- Handles GitHub API rate limiting (separate from application rate limiting)
- Shows appropriate error messages for different failure scenarios

### 3. Comprehensive Test Suite
**File**: `test-rate-limiting.js`

Created 20 automated tests covering:
- Rate limit configuration (verifies 30 req/min threshold)
- Frontend error handling (429, 403, Retry-After)
- IP extraction logic (cf-connecting-ip, x-forwarded-for, x-real-ip)
- Rate limit response codes and headers
- CORS configuration for mobile access

**File**: `package.json`
- Added `test:rate-limiting` script
- Updated main `test` script to run both data-display and rate-limiting tests
- All 71 tests now pass (51 existing + 20 new)

## Technical Details

### IP Extraction
The application extracts client IP in the following order:
1. `cf-connecting-ip` (Cloudflare standard)
2. `x-forwarded-for` (proxy standard)
3. `x-real-ip` (alternative proxy header)
4. `'unknown'` (fallback)

This ensures proper IP identification across different network configurations.

### Rate Limiting
- **Endpoints affected**: `/api/prs/{id}/readiness`, `/api/prs/{id}/review-analysis`, `/api/prs/{id}/timeline`
- **Not rate limited**: `/api/prs`, `/api/repos`, `/api/prs/updates`, `/api/refresh`
- **Threshold**: 30 requests per minute per IP address
- **Window**: 60 seconds (sliding window)
- **Response**: HTTP 429 with `Retry-After` header

### Error Codes
- **429**: Rate limit exceeded (application-level)
- **403**: Forbidden (typically GitHub API rate limiting or access issues)
- **401**: Unauthorized (authentication required)
- **404**: Not found
- **500**: Server error

## Testing

### Run Tests
```bash
# Run all tests
npm test

# Run rate limiting tests only
npm run test:rate-limiting

# Run data display tests only
npm run test:data-display
```

### Manual Testing
To manually test the rate limiting:
1. Deploy the application
2. Make more than 30 requests to `/api/prs/{id}/readiness` within 60 seconds
3. Observe that the 31st request returns HTTP 429 with `Retry-After` header
4. Frontend should display: "Rate limit exceeded. Please try again in X seconds."

### Mobile Testing
To verify the fix on mobile:
1. Access the application on a mobile device
2. Navigate through the application normally
3. Click "Check Readiness" on multiple PRs
4. Verify that error messages are clear and helpful if rate limiting occurs
5. Verify that background update checks don't disrupt the user experience

## Benefits
1. **Better Mobile Support**: 3x higher rate limit accommodates shared mobile IPs
2. **User-Friendly Errors**: Clear messages explain what's happening and when to retry
3. **Graceful Degradation**: Background tasks fail silently without disrupting UX
4. **Comprehensive Testing**: Automated tests ensure the fix remains stable
5. **Proper HTTP Semantics**: Uses correct status codes (429 for rate limiting, not 403)

## Future Improvements
Consider these additional enhancements:
1. **Session-Based Rate Limiting**: Use session IDs or user tokens in addition to IP addresses
2. **Exponential Backoff**: Implement automatic retry with increasing delays
3. **Rate Limit Headers**: Add `X-RateLimit-Remaining` to all rate-limited responses
4. **Monitoring**: Track rate limit hits to identify if further increases are needed
5. **Per-Endpoint Limits**: Different rate limits for different endpoints based on usage patterns

## References
- Issue: #403-error-on-mobile
- PR: copilot/fix-403-error-mobile
- Related Files:
  - `src/cache.py` - Rate limit configuration
  - `src/handlers.py` - Rate limit enforcement
  - `public/index.html` - Error handling
  - `test-rate-limiting.js` - Test suite
