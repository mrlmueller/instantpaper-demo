# Admin Endpoints 500 Error Fix

## Problem Summary

**Live version**: Admin user management pages return 500 errors

- List users endpoint: `GET /api/admin/users` returns "Failed to list users."
- Individual user detail: `GET /api/admin/users/{uid}` returns 500
- **Local version**: Both endpoints work perfectly

## Root Cause Analysis

The admin endpoints had **overly broad exception handling** that caught all errors without logging details, making it impossible to diagnose live server issues.

### Issues Found and Fixed

#### 1. **Inadequate Error Logging** ❌

- **Before**: `except Exception: logger.exception("message")` with no error details
- **After**: `except Exception as e: logger.exception(f"message: {str(e)}", exc_info=True)`
- **Impact**: Can now see the actual error that's causing failures

#### 2. **HTTPException Not Re-raised** ❌

- **Before**: HTTPExceptions caught by outer try-except and converted to 500 errors
- **After**: HTTPExceptions are explicitly re-raised before other exceptions
- **Impact**: Auth and validation errors now return correct HTTP status codes

#### 3. **Potential Async/Sync Issues** ❌

- **Before**: `async def _read_subscription_summary_for_user()` used sync `.stream()` calls
- **After**: Now properly logged when Firestore operations fail
- **Impact**: Blocking operations are logged, making timeouts visible

## Changes Made to `fastapi/main.py`

### 1. Admin Users List Endpoint (lines 1447-1590)

```python
# IMPROVED ERROR HANDLING
try:
    # Firebase initialization
    try:
        _ = firebase_service.db
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {str(e)}")
        raise HTTPException(status_code=500, detail="Firebase initialization failed.") from e

    # Firebase Auth user listing
    try:
        page = auth.list_users(...)
    except Exception as e:
        logger.error(f"Failed to list Firebase Auth users: {str(e)}")
        raise HTTPException(...) from e

    # Loop through users with better error logging
    for user in page.users:
        try:
            user_doc = await firebase_service.get_user_doc(user.uid)
            # ... process doc
        except Exception as e:
            logger.warning(f"Failed to fetch user doc for {user.uid}: {str(e)}")
            # Continue gracefully

    return {"users": users_out, ...}

except HTTPException:
    # Re-raise HTTP exceptions (auth, validation, etc.)
    raise
except Exception as e:
    logger.exception(f"Failed to list admin users: error details below", exc_info=True)
    raise HTTPException(status_code=500, detail="Failed to list users.") from e
```

### 2. Admin User Detail Endpoint (lines 2889-3000+)

- Added detailed logging for user document fetching
- Added detailed logging for billing balance fetching
- Added detailed logging for subscription summary fetching
- Added detailed logging for credits config fetching
- All structured to log actual error messages

### 3. Helper Function Improvements

- `_read_subscription_summary_for_user()`: Now logs when subscription fetch fails

## Expected Behavior After Fix

### When functioning normally:

- ✅ Log: "Successfully listed X admin users"
- ✅ Returns 200 with user list

### When an error occurs:

The server logs will now show the ACTUAL error, such as:

- "Failed to initialize Firebase: {specific error message}"
- "Failed to list Firebase Auth users: {specific error message}"
- "Failed to fetch user doc for {uid}: {specific error message}"
- "Failed to fetch billing balance for {uid}: {specific error message}"
- "Failed to fetch subscription for {uid}: {specific error message}"

## How to Debug in Production

1. **Redeploy** the updated `fastapi/main.py` to production
2. **Reproduce** the error in the live admin UI
3. **Check the FastAPI server logs** for the specific error message
4. **Address the root cause** based on the actual error

Common causes might be:

- Firebase Admin SDK initialization failure
- Firestore read permissions issue
- Network timeout on Firestore queries
- Missing/incorrect environment variables

## Environment Variables to Verify

On the live deployment, ensure:

- ✅ `FIREBASE_PROJECT_ID` is set correctly
- ✅ `FIREBASE_PRIVATE_KEY` contains the full private key with proper newlines
- ✅ `FIREBASE_CLIENT_EMAIL` matches the service account
- ✅ `ADMIN_UIDS` includes the admin user's UID
- ✅ `NEXT_PUBLIC_FASTAPI_URL` points to the correct FastAPI server
- ✅ Network connectivity to Firestore

## Code Review Notes

The fix maintains backward compatibility while greatly improving observability. The log messages now provide enough detail to identify whether the problem is:

- 🔴 Authentication/Authorization
- 🔴 Firebase/Firestore connectivity
- 🔴 Data fetching/permissions
- 🔴 Third-party service (e.g., billing, subscriptions)

All improvements follow FastAPI/Python best practices for error handling and logging.
