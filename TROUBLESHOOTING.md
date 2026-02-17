# Troubleshooting Guide for BLT-Leaf

This guide addresses common issues and their solutions when developing or deploying BLT-Leaf.

## Table of Contents
- [Local Development Issues](#local-development-issues)
- [Deployment Issues](#deployment-issues)
- [API and Rate Limiting](#api-and-rate-limiting)
- [Database Issues](#database-issues)

---

## Local Development Issues

### DNS Lookup Failed When Running `wrangler dev`

**Error Message:**
```
*** Fatal uncaught kj::Exception: kj/async-io-unix.c++:1298: failed: DNS lookup failed.
params.host = pyodide-capnp-bin.edgeworker.net
params.service = ; gai_strerror(status) = No address associated with hostname
```

**Cause:**
BLT-Leaf is a Python Worker, which uses Pyodide (Python compiled to WebAssembly). When you run `wrangler dev` locally, the runtime needs to download Pyodide dependencies from the internet on first run. This fails when:
- You're behind a firewall or corporate proxy
- Running in a restricted CI/CD environment
- Network doesn't allow DNS resolution to Cloudflare's edge network
- Offline or with limited internet connectivity

**Solutions:**

#### Solution 1: Use Remote Mode (Recommended)
Remote mode runs your worker on Cloudflare's infrastructure, bypassing local Python runtime issues:

```bash
# First, ensure you're logged in
wrangler login

# Run in remote mode
wrangler dev --remote
```

Or use the npm script:
```bash
npm run dev:remote
```

**Pros:**
- No local Python runtime downloads needed
- Matches production environment exactly
- Access to all Cloudflare resources (D1, KV, etc.)

**Cons:**
- Requires internet connection and Cloudflare login
- Slightly slower iteration compared to fully local mode

#### Solution 2: Fix Network Access
Ensure your network allows access to these domains:
- `pyodide-capnp-bin.edgeworker.net` - Pyodide runtime files
- `workers.cloudflare.com` - Worker metadata and configuration

If you're behind a corporate proxy, configure your proxy settings or ask your network admin to whitelist these domains.

#### Solution 3: Update Wrangler
Newer versions of Wrangler may have improved caching and offline support:

```bash
npm install -g wrangler@latest
```

Check your current version:
```bash
wrangler --version
```

#### Solution 4: Deploy and Test Remotely
If local development isn't critical for your workflow, deploy directly and test in production:

```bash
# Deploy your changes
wrangler deploy

# Test at your worker URL
# https://your-worker.workers.dev
```

#### Solution 5: Use Different DNS Resolver
Sometimes the issue is with your local DNS configuration. Try using a public DNS resolver:

**On Linux/macOS:**
```bash
# Temporarily use Cloudflare DNS
sudo bash -c 'echo "nameserver 1.1.1.1" > /etc/resolv.conf'

# Or Google DNS
sudo bash -c 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'
```

**On Windows:**
Change DNS in Network Settings to:
- Primary: 1.1.1.1 (Cloudflare)
- Secondary: 8.8.8.8 (Google)

---

### Unable to Fetch `Request.cf` Object

**Warning Message:**
```
[wrangler:warn] Unable to fetch the `Request.cf` object! Falling back to a default placeholder...
Error: getaddrinfo ENOTFOUND workers.cloudflare.com
```

**Cause:**
Wrangler tries to fetch Cloudflare-specific request metadata from the internet. This is just a warning and doesn't prevent the worker from running.

**Solution:**
- This warning is safe to ignore in local development
- To eliminate it, use remote mode: `wrangler dev --remote`
- Ensure network access to `workers.cloudflare.com`

---

### Port Already in Use

**Error:**
```
Error: listen EADDRINUSE: address already in use :::8787
```

**Solution:**
Another process is using port 8787. Either stop it or use a different port:

```bash
# Use a different port
wrangler dev --port 8788

# Or find and kill the process using port 8787
lsof -ti:8787 | xargs kill -9  # Linux/macOS
```

---

## Deployment Issues

### Authentication Required

**Error:**
```
✘ [ERROR] You must be logged in to deploy.
```

**Solution:**
```bash
wrangler login
```

This opens a browser for you to authenticate with Cloudflare.

---

### Database ID Not Found

**Error:**
```
✘ [ERROR] Could not find D1 database with ID: xxxx
```

**Cause:**
The database specified in `wrangler.toml` doesn't exist or you don't have access to it.

**Solution:**

1. Check if database exists:
```bash
wrangler d1 list
```

2. Create the database if missing:
```bash
wrangler d1 create pr_tracker
```

3. Update `wrangler.toml` with the correct database ID from the output.

4. Initialize the schema:
```bash
wrangler d1 execute pr_tracker --file=./schema.sql
```

---

## API and Rate Limiting

### GitHub API Rate Limit Exceeded

**Error (in logs):**
```
GitHub API rate limit exceeded
Status: 403
Rate Limit: 0/60 remaining
```

**Cause:**
Unauthenticated GitHub API requests are limited to 60 requests per hour per IP.

**Solution:**

1. Create a GitHub Personal Access Token:
   - Go to: https://github.com/settings/tokens
   - Click "Generate new token (classic)"
   - Select scopes: `repo` (or `public_repo` for public repos only)
   - Generate and copy the token

2. Add the token to your worker:
```bash
wrangler secret put GITHUB_TOKEN
# Paste your token when prompted
```

3. Verify it's working:
```bash
# Check rate limit via your worker
curl https://your-worker.workers.dev/api/rate-limit
```

**Note:** With a token, you get 5,000 requests per hour instead of 60.

---

### Worker Execution Time Exceeded

**Error:**
```
Error: Worker exceeded CPU time limit
```

**Cause:**
Free tier workers have a 10ms CPU time limit per request. Making multiple GitHub API calls in sequence can exceed this.

**Solution:**
- Use caching to reduce API calls (already implemented in BLT-Leaf)
- Optimize API call sequences
- Consider upgrading to a paid plan for higher limits (50ms CPU time)

---

## Database Issues

### Schema Not Initialized

**Error:**
```
SQLITE_ERROR: no such table: tracked_prs
```

**Solution:**
Initialize the database schema:

```bash
wrangler d1 execute pr_tracker --file=./schema.sql
```

---

### Database Locked

**Error:**
```
SQLITE_BUSY: database is locked
```

**Cause:**
Another process or request is writing to the database.

**Solution:**
- This is usually temporary and resolves automatically
- If persistent, check for long-running queries or concurrent writes
- D1 databases handle concurrent reads well but serialize writes

---

## Getting More Help

If you're still experiencing issues:

1. **Check the logs:**
   ```bash
   wrangler tail
   ```
   This shows real-time logs from your deployed worker.

2. **Enable verbose logging:**
   ```bash
   wrangler dev --log-level debug
   ```

3. **Search existing issues:**
   - [BLT-Leaf Issues](https://github.com/OWASP-BLT/BLT-Leaf/issues)
   - [Wrangler Issues](https://github.com/cloudflare/workers-sdk/issues)

4. **Create a new issue:**
   - Include the full error message
   - Specify your environment (OS, Wrangler version, Node version)
   - Provide steps to reproduce

5. **Cloudflare Community:**
   - [Cloudflare Developer Discord](https://discord.gg/cloudflaredev)
   - [Cloudflare Community Forums](https://community.cloudflare.com/)

---

## Quick Reference

### Essential Commands

```bash
# Development (local)
wrangler dev

# Development (remote - bypasses Python runtime issues)
wrangler dev --remote

# Deploy to production
wrangler deploy

# View live logs
wrangler tail

# Manage secrets
wrangler secret put SECRET_NAME
wrangler secret list

# Database management
wrangler d1 list
wrangler d1 execute pr_tracker --file=./schema.sql
wrangler d1 execute pr_tracker --command="SELECT * FROM tracked_prs"
```

### Useful npm Scripts

```bash
npm run dev          # Local development
npm run dev:remote   # Remote development (recommended for Python Workers)
npm run deploy       # Deploy to production
```
