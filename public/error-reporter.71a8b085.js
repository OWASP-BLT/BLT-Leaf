// Global error reporter: forwards JS errors to the backend,
// which relays them to the configured SLACK_ERROR_WEBHOOK.
(function () {
    function safeTruncate(text, maxLen) {
        var str = String(text || '');
        if (str.length <= maxLen) return str;
        return str.slice(0, Math.max(0, maxLen - 1)) + '…';
    }

    function redactSensitive(text) {
        var str = String(text || '');
        // Redact obvious key/value secrets and auth-like tokens.
        str = str.replace(/(authorization|token|apikey|api[_-]?key|password|passwd|cookie|set-cookie|session|secret|bearer)\s*[:=]\s*([^\s,;]+)/gi, '$1:[redacted]');
        // Redact email addresses.
        str = str.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[redacted-email]');
        // Redact long token-like strings.
        str = str.replace(/\b[A-Za-z0-9_\-]{24,}\b/g, '[redacted-token]');
        return str;
    }

    function sendPayload(payload) {
        try {
            var body = JSON.stringify(payload);

            // Prefer sendBeacon (good for unload), fallback to fetch if beacon fails.
            var ok = false;
            try {
                ok = navigator.sendBeacon('/api/client-error', body);
            } catch (e) {
                ok = false;
            }

            if (!ok) {
                fetch('/api/client-error', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: body,
                    keepalive: true,
                }).catch(function () { });
            }
        } catch (e) { /* ignore reporting failures */ }
    }

    function reportError(errorType, message, stack, extra) {
        var payload = Object.assign(
            { error_type: errorType, message: message, stack: stack || '' },
            extra || {}
        );
        sendPayload(payload);
    }

    // 1) Catch runtime errors + resource loading errors (capture=true is important for resources)
    window.addEventListener('error', function (event) {
        // Resource errors (script/img/link) often have event.target and no event.error
        var target = event.target || {};
        var resourceUrl = target.src || target.href;

        if (resourceUrl && (target.tagName === 'SCRIPT' || target.tagName === 'LINK' || target.tagName === 'IMG')) {
            reportError(
                'ResourceError',
                'Failed to load or execute resource',
                (event.error && event.error.stack) || '',
                { url: location.href, resource: resourceUrl }
            );
            return;
        }

        // Normal runtime error (ReferenceError/TypeError/etc.)
        reportError(
            (event.error && event.error.name) || 'Error',
            event.message || (event.error && event.error.message) || String(event.error) || 'Unknown error',
            (event.error && event.error.stack) || '',
            { url: location.href, line: event.lineno, col: event.colno }
        );
    }, true);

    // 2) Catch unhandled promise rejections
    window.addEventListener('unhandledrejection', function (event) {
        var reason = event.reason || {};
        reportError(
            (reason.name) || 'UnhandledRejection',
            reason.message || String(reason),
            reason.stack || '',
            { url: location.href }
        );
    });

    // 3) Forward handled errors that are logged via console.error
    // This helps when "real errors" are caught by try/catch and only logged.
    (function hookConsoleError() {
        var original = console.error;
        console.error = function () {
            try {
                var args = Array.prototype.slice.call(arguments);
                var errors = args.filter(function (a) { return a instanceof Error; });

                if (errors.length > 0) {
                    var primary = errors[0];
                    var message = redactSensitive(primary.name + ': ' + (primary.message || ''));
                    var stack = redactSensitive(primary.stack || '');
                    reportError(
                        primary.name || 'ConsoleError',
                        safeTruncate(message, 300),
                        safeTruncate(stack || message, 2000),
                        {
                            url: location.href,
                            source: 'console.error:unhandled',
                            report_channel: 'dedupe-candidate',
                            error_count: String(errors.length),
                        }
                    );
                }
            } catch (e) { /* ignore */ }

            return original.apply(console, arguments);
        };
    })();
})();