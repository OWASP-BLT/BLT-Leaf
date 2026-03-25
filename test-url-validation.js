#!/usr/bin/env node

/**
 * Focused tests for frontend URL validation logic in public/index.html.
 *
 * This test loads and evaluates the parser constants/function directly from
 * the page script so behavior stays aligned with production code.
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const indexPath = path.join(__dirname, 'public', 'index.html');
const html = fs.readFileSync(indexPath, 'utf8');

function extractBlock(source, startToken, endToken) {
  const start = source.indexOf(startToken);
  const end = source.indexOf(endToken, start);
  if (start === -1 || end === -1) {
    throw new Error(`Could not extract block between ${startToken} and ${endToken}`);
  }
  return source.slice(start, end);
}

const parserBlock = extractBlock(
  html,
  'const PR_PATH_RE =',
  'function showSectionMessage('
);

const sandbox = {
  URL,
  Set,
  result: null,
};

vm.createContext(sandbox);
vm.runInContext(`${parserBlock}\nresult = parseGitHubTrackingUrl;`, sandbox);

const parseGitHubTrackingUrl = sandbox.result;
if (typeof parseGitHubTrackingUrl !== 'function') {
  throw new Error('parseGitHubTrackingUrl function not found in page script');
}

let passed = 0;
let failed = 0;

function check(name, fn) {
  try {
    fn();
    console.log(`PASS: ${name}`);
    passed += 1;
  } catch (err) {
    console.error(`FAIL: ${name}`);
    console.error(`  ${err.message}`);
    failed += 1;
  }
}

function expectValid(url, expectedType, expectedCanonical) {
  const out = parseGitHubTrackingUrl(url);
  if (!out.valid) {
    throw new Error(`Expected valid URL but got invalid (${out.reason})`);
  }
  if (out.type !== expectedType) {
    throw new Error(`Expected type ${expectedType}, got ${out.type}`);
  }
  if (out.canonicalUrl !== expectedCanonical) {
    throw new Error(`Expected canonical ${expectedCanonical}, got ${out.canonicalUrl}`);
  }
}

function expectInvalid(url) {
  const out = parseGitHubTrackingUrl(url);
  if (out.valid) {
    throw new Error(`Expected invalid URL but got valid (${out.canonicalUrl})`);
  }
}

check('Accepts PR URL with query suffix', () => {
  expectValid(
    'https://github.com/OWASP-BLT/BLT-Leaf/pull/262?diff=split',
    'pr',
    'https://github.com/OWASP-BLT/BLT-Leaf/pull/262'
  );
});

check('Accepts PR URL with fragment suffix', () => {
  expectValid(
    'https://github.com/OWASP-BLT/BLT-Leaf/pull/262#discussion_r1',
    'pr',
    'https://github.com/OWASP-BLT/BLT-Leaf/pull/262'
  );
});

check('Accepts repository URL for bulk flow', () => {
  expectValid(
    'https://github.com/OWASP-BLT/BLT-Leaf',
    'repo',
    'https://github.com/OWASP-BLT/BLT-Leaf'
  );
});

check('Accepts organization URL', () => {
  expectValid(
    'https://github.com/OWASP-BLT',
    'org',
    'https://github.com/OWASP-BLT'
  );
});

check('Accepts /orgs/owner URL', () => {
  expectValid(
    'https://github.com/orgs/OWASP-BLT',
    'org',
    'https://github.com/OWASP-BLT'
  );
});

check('Rejects non-GitHub host', () => {
  expectInvalid('https://example.com/OWASP-BLT/BLT-Leaf/pull/262');
});

check('Rejects GitHub issue URL', () => {
  expectInvalid('https://github.com/OWASP-BLT/BLT-Leaf/issues/1');
});

check('Rejects GitHub commit URL', () => {
  expectInvalid('https://github.com/OWASP-BLT/BLT-Leaf/commit/abcdef');
});

check('Rejects reserved owner route', () => {
  expectInvalid('https://github.com/settings');
});

console.log(`\nSummary: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
