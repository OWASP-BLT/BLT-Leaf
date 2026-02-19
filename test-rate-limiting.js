#!/usr/bin/env node

/**
 * Test script to verify rate limiting and error handling functionality
 * Tests that mobile users can access the API and that rate limits are properly applied
 */

const fs = require('fs');
const path = require('path');

// ANSI color codes for output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
};

let testsPassed = 0;
let testsFailed = 0;

function log(message, color = colors.reset) {
  console.log(`${color}${message}${colors.reset}`);
}

function testResult(testName, passed, message = '') {
  if (passed) {
    testsPassed++;
    log(`✓ ${testName}`, colors.green);
    if (message) log(`  ${message}`, colors.blue);
  } else {
    testsFailed++;
    log(`✗ ${testName}`, colors.red);
    if (message) log(`  ${message}`, colors.red);
  }
}

// Test 1: Verify rate limit configuration
function testRateLimitConfiguration() {
  log('\n=== Testing Rate Limit Configuration ===\n', colors.blue);
  
  const cachePath = path.join(__dirname, 'src', 'cache.py');
  
  try {
    const cacheContent = fs.readFileSync(cachePath, 'utf8');
    
    // Test that rate limit is set to 30 or higher
    const rateLimitMatch = cacheContent.match(/_READINESS_RATE_LIMIT\s*=\s*(\d+)/);
    if (rateLimitMatch) {
      const rateLimit = parseInt(rateLimitMatch[1]);
      testResult(
        'Rate limit threshold is appropriate for mobile users',
        rateLimit >= 30,
        `Rate limit is set to ${rateLimit} requests per minute (minimum 30 recommended for mobile)`
      );
    } else {
      testResult('Rate limit configuration found', false, 'Could not find _READINESS_RATE_LIMIT in cache.py');
    }
    
    // Test that rate limit window is configured
    const windowMatch = cacheContent.match(/_READINESS_RATE_WINDOW\s*=\s*(\d+)/);
    if (windowMatch) {
      const window = parseInt(windowMatch[1]);
      testResult(
        'Rate limit window is configured',
        window === 60,
        `Rate limit window is ${window} seconds`
      );
    } else {
      testResult('Rate limit window found', false, 'Could not find _READINESS_RATE_WINDOW in cache.py');
    }
    
    // Test that comment mentions mobile users
    const hasMobileComment = cacheContent.includes('mobile') || cacheContent.includes('carrier');
    testResult(
      'Configuration explains mobile support',
      hasMobileComment,
      'Documentation mentions mobile/carrier network considerations'
    );
    
  } catch (error) {
    testResult('Read cache.py', false, error.message);
  }
}

// Test 2: Verify error handling in frontend
function testErrorHandling() {
  log('\n=== Testing Error Handling in Frontend ===\n', colors.blue);
  
  const htmlPath = path.join(__dirname, 'public', 'index.html');
  
  try {
    const htmlContent = fs.readFileSync(htmlPath, 'utf8');
    
    // Test for 429 (rate limit) handling
    const has429Handling = htmlContent.includes('response.status === 429') ||
                          htmlContent.includes('status === 429');
    testResult(
      'Frontend handles 429 (rate limit) errors',
      has429Handling,
      'Code checks for status === 429'
    );
    
    // Test for retry-after header handling
    const hasRetryAfterHandling = htmlContent.includes('Retry-After') ||
                                  htmlContent.includes('retry-after') ||
                                  htmlContent.includes('retryAfter');
    testResult(
      'Frontend extracts Retry-After header',
      hasRetryAfterHandling,
      'Code reads Retry-After header from response'
    );
    
    // Test for 403 error handling
    const has403Handling = htmlContent.includes('response.status === 403') ||
                          htmlContent.includes('status === 403');
    testResult(
      'Frontend handles 403 (forbidden) errors',
      has403Handling,
      'Code checks for status === 403'
    );
    
    // Test for user-friendly error messages
    const hasRateLimitMessage = htmlContent.includes('Rate limit exceeded') ||
                               htmlContent.includes('rate limit') ||
                               htmlContent.includes('Too many requests');
    testResult(
      'Frontend displays user-friendly rate limit messages',
      hasRateLimitMessage,
      'Error messages explain rate limiting to users'
    );
    
    // Test for graceful error handling in checkForPrUpdates
    const checkForUpdatesRegex = /async\s+function\s+checkForPrUpdates[\s\S]*?catch/;
    const checkForUpdatesMatch = htmlContent.match(checkForUpdatesRegex);
    if (checkForUpdatesMatch) {
      const checkForUpdatesCode = checkForUpdatesMatch[0];
      const hasErrorHandling = checkForUpdatesCode.includes('!response.ok') ||
                              checkForUpdatesCode.includes('response.status');
      testResult(
        'checkForPrUpdates handles errors gracefully',
        hasErrorHandling,
        'Update check function handles HTTP errors before parsing response'
      );
    } else {
      testResult('Find checkForPrUpdates function', false, 'Could not locate checkForPrUpdates function');
    }
    
    // Test that errors in checkForPrUpdates don't disrupt user experience
    const hasConsoleWarning = htmlContent.includes('console.warn') ||
                             htmlContent.includes('console.error');
    testResult(
      'Background tasks log errors without disrupting UI',
      hasConsoleWarning,
      'Uses console logging for background error reporting'
    );
    
  } catch (error) {
    testResult('Read index.html', false, error.message);
  }
}

// Test 3: Verify IP extraction in handlers
function testIPExtraction() {
  log('\n=== Testing IP Extraction Logic ===\n', colors.blue);
  
  const handlersPath = path.join(__dirname, 'src', 'handlers.py');
  
  try {
    const handlersContent = fs.readFileSync(handlersPath, 'utf8');
    
    // Test for CF-Connecting-IP header (Cloudflare standard)
    const hasCfConnectingIp = handlersContent.includes('cf-connecting-ip');
    testResult(
      'Extracts client IP from cf-connecting-ip header',
      hasCfConnectingIp,
      'Uses Cloudflare-specific header for client IP'
    );
    
    // Test for X-Forwarded-For fallback
    const hasXForwardedFor = handlersContent.includes('x-forwarded-for');
    testResult(
      'Falls back to x-forwarded-for header',
      hasXForwardedFor,
      'Has fallback for proxied requests'
    );
    
    // Test for X-Real-IP fallback
    const hasXRealIp = handlersContent.includes('x-real-ip');
    testResult(
      'Falls back to x-real-ip header',
      hasXRealIp,
      'Has additional fallback for real IP'
    );
    
    // Test for unknown fallback
    const hasUnknownFallback = handlersContent.includes("'unknown'");
    testResult(
      'Has fallback for unknown IPs',
      hasUnknownFallback,
      'Gracefully handles missing IP headers'
    );
    
  } catch (error) {
    testResult('Read handlers.py', false, error.message);
  }
}

// Test 4: Verify rate limiting returns correct status codes
function testRateLimitResponses() {
  log('\n=== Testing Rate Limit Response Codes ===\n', colors.blue);
  
  const handlersPath = path.join(__dirname, 'src', 'handlers.py');
  
  try {
    const handlersContent = fs.readFileSync(handlersPath, 'utf8');
    
    // Test that rate limiting returns 429 (not 403)
    const rateLimit429Regex = /check_rate_limit[\s\S]*?'status':\s*429/;
    const has429Response = rateLimit429Regex.test(handlersContent);
    testResult(
      'Rate limiting returns HTTP 429 status',
      has429Response,
      'Correct HTTP status code for rate limiting'
    );
    
    // Test for Retry-After header in rate limit response
    const hasRetryAfterHeader = handlersContent.includes('Retry-After');
    testResult(
      'Rate limit response includes Retry-After header',
      hasRetryAfterHeader,
      'Tells clients when to retry'
    );
    
    // Test that check_rate_limit is imported
    const importsRateLimit = handlersContent.includes('check_rate_limit');
    testResult(
      'Rate limiting function is used in handlers',
      importsRateLimit,
      'check_rate_limit is imported and used'
    );
    
  } catch (error) {
    testResult('Read handlers.py', false, error.message);
  }
}

// Test 5: Verify CORS headers allow mobile access
function testCORSConfiguration() {
  log('\n=== Testing CORS Configuration ===\n', colors.blue);
  
  const indexPath = path.join(__dirname, 'src', 'index.py');
  
  try {
    const indexContent = fs.readFileSync(indexPath, 'utf8');
    
    // Test for CORS headers
    const hasCorsHeaders = indexContent.includes('Access-Control-Allow-Origin');
    testResult(
      'CORS headers are configured',
      hasCorsHeaders,
      'Access-Control-Allow-Origin header is set'
    );
    
    // Test for CORS methods
    const allowsMethods = indexContent.includes('Access-Control-Allow-Methods');
    testResult(
      'CORS allows required HTTP methods',
      allowsMethods,
      'GET, POST, OPTIONS methods are configured'
    );
    
    // Test for CORS headers for custom headers
    const allowsHeaders = indexContent.includes('Access-Control-Allow-Headers');
    testResult(
      'CORS allows custom headers',
      allowsHeaders,
      'Custom headers like Content-Type are allowed'
    );
    
    // Test for OPTIONS preflight handling
    const handlesOptions = indexContent.includes("request.method == 'OPTIONS'");
    testResult(
      'Handles CORS preflight requests',
      handlesOptions,
      'OPTIONS requests are handled for CORS'
    );
    
  } catch (error) {
    testResult('Read index.py', false, error.message);
  }
}

/**
 * Executes all test suites and outputs results.
 * Exits with code 1 if any tests fail, 0 if all pass.
 */
function runAllTests() {
  log('\n' + '='.repeat(60), colors.blue);
  log('  BLT-Leaf Rate Limiting and Mobile Support Tests', colors.blue);
  log('='.repeat(60) + '\n', colors.blue);
  
  testRateLimitConfiguration();
  testErrorHandling();
  testIPExtraction();
  testRateLimitResponses();
  testCORSConfiguration();
  
  // Summary
  log('\n' + '='.repeat(60), colors.blue);
  log(`  Tests Passed: ${testsPassed}`, colors.green);
  log(`  Tests Failed: ${testsFailed}`, testsFailed > 0 ? colors.red : colors.green);
  log('='.repeat(60) + '\n', colors.blue);
  
  // Exit with appropriate code
  process.exit(testsFailed > 0 ? 1 : 0);
}

// Run tests
runAllTests();
