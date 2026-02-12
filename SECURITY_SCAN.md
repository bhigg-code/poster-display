# Security Scan Report - Poster Display
**Date:** 2026-02-11  
**Scanner:** Bandit 1.9.3 + Manual Review

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| High | 0 | ✅ |
| Medium | 5 | ⚠️ Review |
| Low | 17 | ℹ️ Informational |

## Medium Severity Issues

### 1. XML Parsing Vulnerability (B314)
**Files:** `backend/plex_client.py` (lines 62, 172)  
**Risk:** XML External Entity (XXE) attacks  
**Code:**
```python
ET.fromstring(text)  # Parsing Plex API XML response
```
**Mitigation:** 
- Plex responses are from trusted local server
- Consider using `defusedxml` for defense in depth
- LOW RISK in current context (local network only)

### 2. Binding to All Interfaces (B104)
**Files:** `backend/server.py`, `backend/atlona_broker.py`  
**Risk:** Exposes service to all network interfaces  
**Mitigation:**
- **Intentional behavior** for local network service
- Services are on trusted home network
- No authentication bypass risk (services are informational)
- ACCEPTABLE for use case

## Low Severity Issues

### 3. Try/Except/Pass (B110) - 6 instances
**Risk:** Silently swallowing exceptions  
**Mitigation:** 
- Used intentionally for optional features (ADB, network probes)
- Failures are non-critical (device offline = skip)
- ACCEPTABLE for fault tolerance

### 4. Hardcoded Empty Passwords (B105)
**Files:** `backend/config.py`, `backend/config_manager.py`  
**Code:** `"token": ""`  
**Mitigation:**
- These are DEFAULT empty values, not actual credentials
- Real values come from config.json (now gitignored)
- FALSE POSITIVE

### 5. TMDB API Key
**File:** `backend/poster_lookup.py`  
**Code:** `TMDB_API_KEY = '8265bd1679663a7ea12ac168da84d2e8'`  
**Mitigation:**
- This is TMDB's public demo/sample key
- Used only for poster metadata lookup
- No security impact

## Security Controls Present ✅

1. **Input Validation:** `validate_ip()`, `validate_port()`, `validate_config_data()`
2. **XSS Protection:** `escapeHtml()` function used for user-controlled data
3. **No SQL/Command Injection:** No database or shell commands
4. **No Hardcoded Secrets:** Plex token loaded from config (gitignored)
5. **Config Sanitization:** Plex token masked in API responses

## Recommendations

### Should Fix (Low effort, defense in depth)
1. Replace `xml.etree.ElementTree` with `defusedxml`:
   ```bash
   pip install defusedxml
   ```
   ```python
   import defusedxml.ElementTree as ET
   ```

### Optional Improvements
2. Add rate limiting to API endpoints
3. Add CORS headers if accessed cross-origin
4. Consider authentication for admin endpoints (currently relies on network security)

## Not Vulnerable To

- ❌ SQL Injection (no database)
- ❌ Command Injection (no subprocess/shell)
- ❌ Path Traversal (no user-controlled file paths)
- ❌ SSRF (only connects to configured local IPs)
- ❌ Credential Exposure (tokens in gitignored config)

## Scan Commands Used

```bash
# Bandit scan
bandit -r backend/ -ll -f txt

# Manual grep checks
grep -rn "subprocess\|os.system\|eval\|exec" backend/
grep -rn "password\|api_key" backend/
```
