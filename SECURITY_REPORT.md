# Security & Code Analysis Report - v1.1.11

**Generated:** 2026-02-09
**Analyzed:** poster-display v1.1.11
**Total Lines:** ~6,780 across 13 files

---

## 🔴 HIGH Priority

### 1. No Authentication/Authorization
- **Location:** `backend/server.py` (all endpoints)
- **Issue:** All API endpoints are publicly accessible without authentication
- **Risk:** Anyone on the network can modify config, trigger scans, restart services
- **Fix:** Add basic auth or API key for admin endpoints

### 2. Plex Token Exposed in API Response
- **Location:** `backend/server.py:634` - `/api/config` endpoint
- **Issue:** Full config including Plex token returned to frontend
- **Risk:** Token exposure to any client
- **Fix:** Filter sensitive fields before returning config

### 3. XSS via innerHTML with User Data
- **Location:** `frontend/admin.html` (multiple locations)
- **Issue:** Device names, integration names inserted via innerHTML without escaping
- **Risk:** Malicious device names could inject JavaScript
- **Fix:** Escape HTML entities before insertion

---

## 🟠 MEDIUM Priority

### 4. No Input Validation on API Endpoints
- **Location:** `backend/server.py` - config handlers
- **Issue:** IP addresses, port numbers, names not validated
- **Risk:** Invalid data could cause crashes or unexpected behavior
- **Fix:** Add validation for IP format, port ranges, string lengths

### 5. Missing CORS Headers
- **Location:** `backend/server.py`
- **Issue:** No CORS policy defined
- **Risk:** API accessible from any origin
- **Fix:** Add CORS middleware with appropriate restrictions

### 6. No Rate Limiting
- **Location:** `backend/server.py`
- **Issue:** No rate limiting on any endpoints
- **Risk:** DoS via rapid requests, especially on discovery/scan endpoints
- **Fix:** Add rate limiting middleware

### 7. Broad Exception Handling
- **Location:** `backend/server.py` (15+ locations)
- **Issue:** Generic `except Exception` catches all errors
- **Risk:** May hide bugs, inconsistent error responses
- **Fix:** Catch specific exceptions, log appropriately

### 8. httpx Version Pinned to Old Version
- **Location:** `requirements.txt`
- **Issue:** `httpx==0.23.0` is outdated (current is 0.27+)
- **Risk:** May contain known vulnerabilities
- **Fix:** Update to latest stable version

---

## 🟡 LOW Priority

### 9. Debug Information in Error Responses
- **Location:** `backend/server.py` - exception handlers
- **Issue:** Some error messages include internal details
- **Risk:** Information disclosure
- **Fix:** Return generic error messages, log details server-side

### 10. No Content-Security-Policy Header
- **Location:** `backend/server.py`
- **Issue:** Missing CSP header for frontend
- **Risk:** Reduced XSS protection
- **Fix:** Add CSP header

### 11. Hardcoded Default Subnet
- **Location:** `backend/discovery.py:408`
- **Issue:** Falls back to `192.168.0.x` if detection fails
- **Risk:** May scan wrong subnet
- **Fix:** Require explicit subnet or better detection

### 12. File Path Construction
- **Location:** `backend/server.py:731,739`, `backend/config_manager.py`
- **Issue:** Using Path() with relative paths
- **Risk:** Low - paths are hardcoded relative to script
- **Fix:** Validate paths don't escape intended directory

---

## ✅ Positive Findings

- No command injection (no os.system/subprocess/shell=True)
- No SQL injection (no database)
- No eval()/exec() usage
- Credentials stored in separate pyatv storage, not in main config
- ADB keys stored securely with proper permissions
- No hardcoded credentials in source

---

## Recommended Fixes for v1.1.12

1. **Add HTML escaping utility for XSS prevention**
2. **Filter Plex token from /api/config response**
3. **Add input validation for IP addresses and ports**
4. **Update httpx dependency**
5. **Add security headers (CORS, CSP)**

---

*Note: This is a local network application. Many "vulnerabilities" assume trusted network. Authentication is recommended if exposed beyond local network.*
