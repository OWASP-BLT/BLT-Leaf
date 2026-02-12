const { test, expect } = require('@playwright/test');

test.describe('Frontend JavaScript Tests', () => {
  test('should run all frontend tests successfully', async ({ page }) => {
    // Navigate to the test page
    await page.goto('http://localhost:8080/test_frontend.html');
    
    // Wait for tests to complete (look for summary element)
    await page.waitForSelector('.summary', { timeout: 10000 });
    
    // Get the summary text
    const summary = await page.locator('.summary').textContent();
    console.log('Test Summary:', summary);
    
    // Check if there are any failed tests
    const failedCount = await page.locator('.test-case.fail').count();
    
    if (failedCount > 0) {
      // Log failed test details
      const failedTests = await page.locator('.test-case.fail').allTextContents();
      console.error('Failed tests:', failedTests);
    }
    
    // Assert that all tests passed (no failed tests)
    expect(failedCount).toBe(0);
    
    // Verify the summary indicates success
    expect(summary).toContain('Failed: 0');
  });
});
