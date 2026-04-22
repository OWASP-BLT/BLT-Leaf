// Global error reporter: forwards JS errors to the backend,
// which relays them to the configured SLACK_ERROR_WEBHOOK.
(function () {
    function safeTruncate(text, maxLen) {
        var str = String(text || '');
        if (str.length <= maxLen) return str;
        if (maxLen <= 3) return str.slice(0, Math.max(0, maxLen));
        return str.slice(0, maxLen - 3) + '...';
    }

    function redactSensitive(text) {
        var str = String(text || '');
        str = str.replace(
            /(authorization|token|apikey|api[_-]?key|password|passwd|cookie|set-cookie|session|secret|bearer)\s*[:=]\s*([^\s,;]+)/gi,
            '$1:[redacted]'
        );
        str = str.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[redacted-email]');
        str = str.replace(/\b[A-Za-z0-9_\-]{24,}\b/g, '[redacted-token]');
        return str;
    }

    function sanitizeText(text, maxLen) {
        return safeTruncate(redactSensitive(text), maxLen);
    }

    function sanitizeExtra(extra) {
        var clean = {};
        var source = extra || {};

        Object.keys(source).forEach(function (key) {
            var value = source[key];
            if (value == null) {
                clean[key] = value;
                return;
            }
            if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
                clean[key] = sanitizeText(value, 500);
                return;
            }
            clean[key] = '[redacted-object]';
        });

        return clean;
    }

    function getPageUrl() {
        try {
            return location.origin + location.pathname;
        } catch (e) {
            return location.pathname || '';
        }
    }

    function serializeConsoleArg(value) {
        if (value instanceof Error) {
            return value.name + ': ' + value.message + '\n' + (value.stack || '');
        }
        if (typeof value === 'object') {
            try {
                return JSON.stringify(value);
            } catch (e) {
                return '[object]';
            }
        }
        return String(value);
    }

    function sendPayload(payload) {
        try {
            var body = JSON.stringify(payload);

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
                }).catch(function () {});
            }
        } catch (e) {}
    }

    function reportError(errorType, message, stack, extra) {
        var payload = Object.assign(
            {
                error_type: sanitizeText(errorType || 'Error', 100),
                message: sanitizeText(message || 'Unknown error', 300),
                stack: sanitizeText(stack || '', 2000),
            },
            sanitizeExtra(extra)
        );
        sendPayload(payload);
    }

    window.addEventListener(
        'error',
        function (event) {
            var target = event.target || {};
            var resourceUrl = target.src || target.href;
            var shouldReportResource =
                target.tagName === 'SCRIPT' ||
                target.tagName === 'LINK' ||
                (target.tagName === 'IMG' &&
                    !target.hasAttribute('onerror') &&
                    !target.hasAttribute('data-ignore-error'));

            if (resourceUrl && shouldReportResource) {
                reportError(
                    'ResourceError',
                    'Failed to load or execute resource',
                    (event.error && event.error.stack) || '',
                    { url: getPageUrl(), resource: resourceUrl }
                );
                return;
            }

            reportError(
                (event.error && event.error.name) || 'Error',
                event.message ||
                    (event.error && event.error.message) ||
                    String(event.error) ||
                    'Unknown error',
                (event.error && event.error.stack) || '',
                { url: getPageUrl(), line: event.lineno, col: event.colno }
            );
        },
        true
    );

    window.addEventListener('unhandledrejection', function (event) {
        var reason = event.reason || {};
        reportError(
            reason.name || 'UnhandledRejection',
            reason.message || String(reason),
            reason.stack || '',
            { url: getPageUrl() }
        );
    });

    (function hookConsoleError() {
        var original = console.error;
        console.error = function () {
            try {
                var args = Array.prototype.slice.call(arguments);
                var errors = args.filter(function (arg) {
                    return arg instanceof Error;
                });
                var msg = args.map(serializeConsoleArg).join(' ');

                if (errors.length > 0) {
                    var primary = errors[0];
                    reportError(
                        primary.name || 'ConsoleError',
                        (primary.name || 'ConsoleError') + ': ' + (primary.message || ''),
                        primary.stack || msg,
                        {
                            url: getPageUrl(),
                            source: 'console.error:unhandled',
                            report_channel: 'dedupe-candidate',
                            error_count: String(errors.length),
                        }
                    );
                } else if (msg) {
                    reportError('ConsoleError', msg, msg, {
                        url: getPageUrl(),
                        source: 'console.error',
                    });
                }
            } catch (e) {}

            return original.apply(console, arguments);
        };
    })();
})();
