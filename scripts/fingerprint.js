/**
 * fingerprint.js — Content-hash static assets for cache busting.
 *
 * For each asset listed in ASSETS:
 *   1. Compute the first 8 hex chars of its SHA-256 content hash.
 *   2. Write a fingerprinted copy:  <stem>.<hash>.<ext>  (e.g. theme.c06488f2.js)
 *   3. Delete any stale fingerprinted copies for the same base name.
 *   4. Rewrite all src="…<stem>.<ext>…" references in HTML_FILES to the new name.
 *
 * Run automatically via the wrangler build command:
 *   node scripts/fingerprint.js && bash scripts/migration.sh
 *
 * Or manually:
 *   node scripts/fingerprint.js
 */

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PUBLIC = path.join(__dirname, '..', 'public');

// Local JS/CSS assets to fingerprint.
// CDN resources, sw.js, and HTML files are intentionally excluded.
const ASSETS = [
    'error-reporter.js',
    'how-it-works.js',
    'theme.js',
];

// HTML files whose asset references will be rewritten.
const HTML_FILES = [
    'index.html',
    'how-it-works.html',
    'diagnostics.html',
    'test-error.html',
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function hashFile(filePath) {
    const content = fs.readFileSync(filePath);
    return crypto.createHash('sha256').update(content).digest('hex').slice(0, 8);
}

function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ── Fingerprint each asset ────────────────────────────────────────────────────

const manifest = {};
const missingAssets = [];

for (const asset of ASSETS) {
    const srcPath = path.join(PUBLIC, asset);
    if (!fs.existsSync(srcPath)) {
        missingAssets.push(asset);
        continue;
    }

    const ext = path.extname(asset);         // '.js'
    const stem = path.basename(asset, ext);  // 'theme'
    const hash = hashFile(srcPath);
    const fingerprinted = `${stem}.${hash}${ext}`;  // 'theme.c06488f2.js'
    const destPath = path.join(PUBLIC, fingerprinted);

    // Remove stale fingerprinted copies (different hash) for this asset.
    const stalePattern = new RegExp(
        `^${escapeRegex(stem)}\\.[0-9a-f]{8}\\${ext}$`
    );
    for (const existing of fs.readdirSync(PUBLIC)) {
        if (stalePattern.test(existing) && existing !== fingerprinted) {
            fs.unlinkSync(path.join(PUBLIC, existing));
            console.log(`[fingerprint] Removed stale: ${existing}`);
        }
    }

    // Write the fingerprinted copy if it doesn't already exist.
    if (!fs.existsSync(destPath)) {
        fs.copyFileSync(srcPath, destPath);
        console.log(`[fingerprint] Created: ${fingerprinted}`);
    } else {
        console.log(`[fingerprint] Up to date: ${fingerprinted}`);
    }

    manifest[asset] = fingerprinted;
}

if (missingAssets.length > 0) {
    throw new Error(
        `[fingerprint] Missing required asset(s): ${missingAssets.join(', ')}`
    );
}

// Persist the manifest so other tools can read it if needed.
const manifestPath = path.join(PUBLIC, 'asset-manifest.json');
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
console.log('[fingerprint] Wrote asset-manifest.json');

// ── Rewrite HTML references ───────────────────────────────────────────────────

for (const htmlFile of HTML_FILES) {
    const htmlPath = path.join(PUBLIC, htmlFile);
    if (!fs.existsSync(htmlPath)) continue;

    let html = fs.readFileSync(htmlPath, 'utf8');
    let changed = false;

    for (const [original, fingerprinted] of Object.entries(manifest)) {
        const ext = path.extname(original);        // '.js'
        const stem = path.basename(original, ext); // 'theme'

        // Matches both unhashed and hashed names:
        //   src="(optional-path/)stem.ext"
        //   src="(optional-path/)stem.1234abcd.ext"
        const re = new RegExp(
            `(src=["'][^"']*)${escapeRegex(stem)}(?:\\.[0-9a-f]{8})?${escapeRegex(ext)}(["'])`,
            'g'
        );

        const updated = html.replace(re, `$1${fingerprinted}$2`);
        if (updated !== html) {
            html = updated;
            changed = true;
        }
    }

    if (changed) {
        fs.writeFileSync(htmlPath, html, 'utf8');
        console.log(`[fingerprint] Updated: ${htmlFile}`);
    } else {
        console.log(`[fingerprint] No changes: ${htmlFile}`);
    }
}
