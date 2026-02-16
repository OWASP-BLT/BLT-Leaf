/**
 * Shared utility functions for BLT-Leaf
 * These functions are used by both the main application and tests
 */

/**
 * Escape HTML special characters to prevent XSS attacks
 * @param {string} text - The text to escape
 * @returns {string} - The escaped HTML
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Format a date as relative time (e.g., "3 hours ago", "just now")
 * @param {string} dateString - ISO 8601 date string
 * @returns {string} - Formatted relative time
 */
function timeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    const intervals = {
        year: 31536000,
        month: 2592000,
        week: 604800,
        day: 86400,
        hour: 3600,
        minute: 60
    };

    for (const [name, value] of Object.entries(intervals)) {
        const interval = Math.floor(seconds / value);
        if (interval >= 1) return `${interval} ${name}${interval === 1 ? '' : 's'} ago`;
    }

    return 'just now';
}

// Export for use in both browser and test environments
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { escapeHtml, timeAgo };
}
