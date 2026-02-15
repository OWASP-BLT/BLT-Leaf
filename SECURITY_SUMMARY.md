# Security Summary: Authentication and History Tracking

This document provides a security analysis of the authentication and PR history tracking features implemented in BLT-Leaf.

## Feature Overview

The authentication system allows users to:
- Log in with a GitHub username (stored in localStorage)
- Refresh PRs (requires authentication)
- Track who performed which actions

The history tracking system records:
- All PR refreshes with actor attribution
- Automatic detection of state changes
- Review status changes
- CI/CD check changes
- When PRs are added to the system

## Security Model

### Threat Model

**Assumptions**:
- Users are trusted team members working on the same project
- The primary goal is activity tracking and attribution, not access control
- The system operates in a controlled environment (internal tools, trusted networks)

**Out of Scope**:
- Preventing malicious users from impersonating others
- Protecting sensitive data from unauthorized access
- Compliance with strict authentication standards (SOC 2, HIPAA, etc.)

### Authentication Mechanism

#### Current Implementation: Username-Only

**How It Works**:
1. User provides their GitHub username via a browser prompt
2. Username is validated for format (1-39 chars, alphanumeric + hyphens)
3. Username is stored in browser's localStorage
4. Username is sent in the `Authorization` header on refresh requests
5. Backend validates format but **does not verify** against GitHub's API

**Security Properties**:
- ✅ Format validation prevents injection attacks
- ✅ No passwords stored or transmitted
- ✅ No credential leakage risk
- ⚠️ Username can be easily spoofed
- ⚠️ No verification that user owns the GitHub account
- ❌ Not suitable for access control

#### Trust Assumptions

This model assumes:
1. **Honest Users**: Users will provide their real GitHub username
2. **Cooperative Environment**: Team members want accurate attribution
3. **Low Stakes**: The cost of spoofing is negligible (no access control impact)
4. **Audit Trail**: History provides visibility even if attribution is imperfect

## Vulnerability Analysis

### 1. Username Spoofing

**Severity**: Low  
**Impact**: Activity attribution could be incorrect

**Attack Scenario**:
```javascript
// Attacker could manually set localStorage
localStorage.setItem('github_username', 'someone_else');
// Or modify Authorization header in browser dev tools
```

**Mitigation**:
- Accept this as a limitation of the current model
- For production: Implement OAuth flow (see recommendations below)
- Use audit logs to detect anomalies (e.g., same IP with multiple usernames)

**Risk Assessment**: Acceptable for internal tools where users are trusted

### 2. Lack of Session Expiry

**Severity**: Low  
**Impact**: Username persists indefinitely in localStorage

**Attack Scenario**:
- User logs in on a shared computer
- Username remains available to anyone using that browser
- Subsequent actions attributed to that user

**Mitigation**:
- Add logout functionality (✅ Already implemented)
- Consider adding session expiry (e.g., 24 hours)
- Clear localStorage on browser close (using sessionStorage instead)

**Recommendation**:
```javascript
// Option 1: Add expiry timestamp
function setUsername(username) {
    const session = {
        username,
        expires: Date.now() + (24 * 60 * 60 * 1000) // 24 hours
    };
    localStorage.setItem('github_session', JSON.stringify(session));
}

// Option 2: Use sessionStorage for automatic cleanup
function setUsername(username) {
    sessionStorage.setItem('github_username', username);
}
```

### 3. XSS Risk via Username Display

**Severity**: Low  
**Impact**: Stored XSS if username contains malicious scripts

**Current Protection**:
- Username validated with regex: `/^[a-zA-Z0-9]([a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$/`
- Only alphanumeric and hyphens allowed
- HTML escaping used when displaying: `escapeHtml(entry.actor)`

**Status**: ✅ Protected

### 4. Injection Attacks

**Severity**: Low (protected)  
**Impact**: Could manipulate database queries if unprotected

**Protection Mechanisms**:

1. **Username Validation**: Regex prevents special characters
2. **Parameterized Queries**: All SQL uses prepared statements
   ```python
   stmt = db.prepare('SELECT * FROM pr_history WHERE pr_id = ?').bind(pr_id)
   ```
3. **Type Validation**: PR ID converted to integer before use
   ```python
   pr_id = int(pr_id)  # Throws ValueError if not a number
   ```

**Status**: ✅ Protected

### 5. CORS Misconfiguration

**Current Setting**:
```python
'Access-Control-Allow-Origin': '*'
```

**Risk**: Allows any website to make requests to the API

**Mitigation Options**:

1. **For Production**: Restrict to specific domains
   ```python
   'Access-Control-Allow-Origin': 'https://leaf.owaspblt.org'
   ```

2. **For Development**: Keep wildcard but add authentication checks
   - Already required for refresh operations ✅
   - Consider requiring for other endpoints

3. **For Public API**: Keep wildcard but implement rate limiting
   - Already implemented for readiness endpoints ✅

**Current Status**: Acceptable for public tool, but production should restrict

### 6. Rate Limiting Bypass

**Current Implementation**:
- Rate limiting based on IP address
- 10 requests per minute for readiness endpoints

**Potential Issues**:
- NAT/proxy users share IP address
- Distributed attacks can bypass IP-based limits

**Recommendation**:
```python
# Combine IP + username for authenticated endpoints
rate_limit_key = f"{ip_address}:{username}"
```

### 7. History Manipulation

**Severity**: Low  
**Impact**: Attacker could delete or modify history records

**Current Protection**:
- No delete endpoint exposed
- No update endpoint exposed
- History can only be created via refresh operations

**Potential Risk**:
- Direct database access could modify history
- No cryptographic signatures on history entries

**Mitigation**:
- Implement database access controls (Cloudflare D1 handles this)
- Consider adding checksums for critical history entries
- Regular database backups

## Data Privacy

### Personal Information

**Data Collected**:
- GitHub username (self-reported)
- Timestamps of actions
- PR metadata (public GitHub data)

**Storage**:
- Username: Browser localStorage (client-side)
- History: Cloudflare D1 database (server-side)

**Privacy Properties**:
- No passwords or tokens stored
- No email addresses collected
- All PR data is already public on GitHub
- Username is voluntarily provided by user

**GDPR Considerations**:
- Username could be considered personal data
- Users can clear their localStorage to "forget" them
- Consider adding admin endpoint to purge user's history

### Data Retention

**Current Behavior**:
- History retained indefinitely
- No automatic cleanup

**Recommendation**:
```sql
-- Option 1: Archive old history
-- Keep last 90 days
DELETE FROM pr_history WHERE created_at < date('now', '-90 days');

-- Option 2: Aggregate old history
-- Replace old entries with summary
INSERT INTO pr_history_archive 
SELECT pr_id, COUNT(*) as refresh_count 
FROM pr_history 
WHERE created_at < date('now', '-90 days')
GROUP BY pr_id;
```

## Production Recommendations

### High-Priority Improvements

1. **Implement OAuth Flow**

   **Why**: Verify user identity, don't trust self-reported usernames

   **How**:
   ```javascript
   // Frontend: Redirect to GitHub OAuth
   const githubAuthUrl = `https://github.com/login/oauth/authorize?client_id=${clientId}&scope=user:email`;
   window.location.href = githubAuthUrl;

   // Backend: Exchange code for token
   const tokenResponse = await fetch('https://github.com/login/oauth/access_token', {
       method: 'POST',
       body: JSON.stringify({
           client_id: process.env.GITHUB_CLIENT_ID,
           client_secret: process.env.GITHUB_CLIENT_SECRET,
           code: authCode
       })
   });
   ```

2. **Add JWT Tokens**

   **Why**: Stateless authentication, harder to forge

   **How**:
   ```python
   import jwt
   
   def create_token(username):
       payload = {
           'username': username,
           'exp': datetime.utcnow() + timedelta(hours=24)
       }
       return jwt.encode(payload, SECRET_KEY, algorithm='HS256')
   
   def verify_token(token):
       try:
           payload = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
           return payload['username']
       except jwt.ExpiredSignatureError:
           return None
       except jwt.InvalidTokenError:
           return None
   ```

3. **Restrict CORS**

   **Why**: Prevent unauthorized websites from using the API

   **How**:
   ```python
   allowed_origins = ['https://leaf.owaspblt.org', 'https://staging.leaf.owaspblt.org']
   origin = request.headers.get('Origin')
   
   if origin in allowed_origins:
       cors_headers['Access-Control-Allow-Origin'] = origin
   ```

4. **Add Session Expiry**

   **Why**: Reduce risk from forgotten sessions

   **How**: Store expiry timestamp with username, check on each request

### Medium-Priority Improvements

1. **Implement CSRF Protection**
2. **Add Request Signing** for critical operations
3. **Enable HTTPS Only** (if not already)
4. **Add Audit Logging** for security events
5. **Implement Content Security Policy** headers

### Optional Enhancements

1. **Two-Factor Authentication** for high-risk operations
2. **Webhook Verification** if adding GitHub webhooks
3. **Encrypted History Storage** for sensitive environments
4. **Anomaly Detection** for unusual activity patterns

## Security Checklist

Use this checklist to verify security posture:

### Input Validation
- [x] Username format validation (regex)
- [x] PR ID type validation (integer conversion)
- [x] SQL injection prevention (parameterized queries)
- [x] XSS prevention (HTML escaping)

### Authentication
- [x] Username required for refresh
- [ ] OAuth integration (recommended for production)
- [ ] Token verification (recommended for production)
- [ ] Session expiry (optional)

### Authorization
- [ ] Role-based access control (not needed for current scope)
- [x] Rate limiting per IP
- [ ] Rate limiting per user (recommended)

### Data Protection
- [x] No passwords stored
- [x] History cascading deletes (ON DELETE CASCADE)
- [ ] Data retention policy (recommended)
- [ ] Encryption at rest (handled by D1)

### Network Security
- [x] CORS headers configured
- [ ] CORS restricted to specific domains (recommended for production)
- [x] HTTPS enforced (assumed in production)

### Monitoring
- [x] Error logging (console.log, print statements)
- [ ] Security event logging (recommended)
- [ ] Anomaly detection (optional)

## Incident Response

### If Username Spoofing Detected

1. **Identify**: Check logs for suspicious patterns (same IP, multiple usernames)
2. **Verify**: Contact users to confirm their activity
3. **Remediate**: If confirmed, manually correct history entries in database
4. **Prevent**: Implement OAuth flow to verify identities

### If Unauthorized Access Detected

1. **Block**: Add rate limiting or IP blocking if needed
2. **Audit**: Review all actions by suspicious actors
3. **Clean**: Remove or quarantine affected data
4. **Strengthen**: Implement stricter authentication

## Compliance Considerations

### General Data Protection Regulation (GDPR)

**Applicability**: If users are in EU and usernames are personal data

**Requirements**:
- [x] Lawful basis: Legitimate interest (activity tracking)
- [ ] Right to access: Implement user history export
- [ ] Right to erasure: Implement user history deletion
- [ ] Data minimization: Only collect necessary data ✅
- [ ] Privacy by design: No excessive data collection ✅

### California Consumer Privacy Act (CCPA)

**Applicability**: If users are in California and identifiable

**Requirements**:
- Similar to GDPR (access, deletion, disclosure)

### Recommendations for Compliance

1. Add privacy policy explaining data usage
2. Implement user data export endpoint
3. Implement user data deletion endpoint
4. Keep audit logs of data access/deletion

## Conclusion

The current authentication and history tracking implementation is:

✅ **Suitable for**:
- Internal team tools
- Trusted user environments
- Activity tracking and attribution
- Audit trails and analytics

⚠️ **Not suitable for**:
- Access control or authorization
- Protecting sensitive data
- Environments with untrusted users
- Regulatory compliance (without enhancements)

**Overall Risk Level**: **Low** for intended use case

**Recommendation**: Deploy as-is for internal tools, implement OAuth and JWT for production environments with broader user base.
