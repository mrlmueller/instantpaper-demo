# InstantPaper FastAPI Backend

FastAPI backend server for processing papers with OpenAI. This service authenticates users via Firebase tokens, fetches papers from Firestore, processes them with OpenAI, and stores results back in Firestore.

## Features

- Firebase Authentication (token verification)
- Firestore integration for papers and results
- OpenAI API integration (GPT-4o-mini, GPT-4o, O1)
- Async/await architecture for performance
- CORS support for Next.js frontend
- Comprehensive logging

## Requirements

- **Python 3.10+** (recommended)
- Python 3.8+ will work but with deprecation warnings from Google libraries

**Note**: If you see warnings about Python 3.8 being unsupported, the server will still function correctly. However, for the best experience and to avoid deprecation warnings, upgrade to Python 3.10 or later.

## Setup

### 1. Create Virtual Environment

```bash
cd fastapi
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required environment variables:

#### Firebase Admin SDK
Get these from Firebase Console → Project Settings → Service Accounts → Generate New Private Key

```env
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
FIREBASE_CLIENT_EMAIL=firebase-adminsdk-xxxxx@your-project.iam.gserviceaccount.com
```

**Important**: The private key must include the escaped newlines (`\n`). When copying from the JSON file, make sure to preserve them.

#### OpenAI API
Get your API key from https://platform.openai.com/api-keys

```env
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxx
```

#### User key encryption
Base64-encoded AES key used to encrypt per-user OpenAI keys. Generate one (32 bytes recommended) and keep it secret.

```bash
python - <<'PY'
import base64, os
print(base64.b64encode(os.urandom(32)).decode())
PY
```

```env
USER_KEY_ENCRYPTION_KEY=base64-encoded-aes-key
```

#### Server Configuration

```env
PORT=8000
ALLOWED_ORIGINS=http://localhost:3000,https://instantpaper.vercel.app,https://www.instantpaper.de
DEBUG=true
```

## Running the Server

### Development Mode (with auto-reload)

```bash
python -m uvicorn main:app --reload --port 8000
```

Or simply:

```bash
python main.py
```

### Production Mode

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

The server will start on `http://localhost:8000`

## API Endpoints

### Health Check

```
GET /health
```

Returns server status and configuration check.

**Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "firebase": "connected",
  "openai": "connected"
}
```

### Test Authentication

```
GET /test/auth
Authorization: Bearer <firebase-id-token>
```

Test endpoint to verify Firebase token verification works.

**Response**:
```json
{
  "message": "Authentication successful",
  "user_id": "abc123xyz"
}
```

### Process Paper

```
POST /api/process
Authorization: Bearer <firebase-id-token>
Content-Type: application/json
```

Process a paper with OpenAI based on user instructions.

**Request Body**:
```json
{
  "paper_id": "paper123",
  "user_input": "Summarize the main points in bullet format",
  "model": "gpt-4o-mini"
}
```

**Models**: `gpt-4o-mini` (default), `gpt-4o`, `o1`

**Response**:
```json
{
  "result_id": "result456",
  "paper_id": "paper123",
  "result_content": "Summary of the paper...",
  "model_used": "gpt-4o-mini",
  "tokens_used": 1523,
  "created_at": "2025-01-15T10:30:00Z"
}
```

**Errors**:
- `401`: Invalid or missing Firebase token
- `404`: Paper not found or user doesn't own it
- `500`: OpenAI API error or server error

## Architecture

### Directory Structure

```
fastapi/
├── main.py                    # FastAPI app entry point
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (not in git)
├── .env.example              # Environment template
├── .gitignore                # Python gitignore
├── README.md                 # This file
├── models/
│   ├── __init__.py
│   ├── request.py            # Pydantic request models
│   └── response.py           # Pydantic response models
├── services/
│   ├── __init__.py
│   ├── firebase_service.py   # Firebase Admin SDK
│   ├── openai_service.py     # OpenAI API client
│   └── paper_service.py      # Business logic
├── middleware/
│   ├── __init__.py
│   └── auth.py               # Token verification
└── utils/
    ├── __init__.py
    └── config.py             # Configuration loader
```

### Data Flow

```
Next.js Frontend
    ↓ POST /api/process (with Firebase token)
FastAPI Backend
    ↓ Verify token with Firebase Admin
    ↓ Fetch paper from Firestore (verify ownership)
    ↓ Process with OpenAI API
    ↓ Save result to Firestore
    ↑ Return result
Next.js Frontend
    ↓ Display result to user
```

### Firestore Structure

```
users/{userId}/
  papers/{paperId}/
    title: string
    content: string
    createdAt: Timestamp
  results/{resultId}/
    paper_id: string
    user_input: string
    result_content: string
    model_used: string
    tokens_used: number
    created_at: Timestamp
```

## Testing

### 1. Test Server Startup

```bash
python main.py
```

Should see:
```
INFO:     Starting InstantPaper API server...
INFO:     Debug mode: True
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 2. Test Health Endpoint

```bash
curl http://localhost:8000/health
```

### 3. Test Authentication

Get your Firebase token from the browser:
- Open Next.js app and sign in
- Open browser DevTools → Application → Cookies
- Copy the `__session` cookie value

```bash
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" http://localhost:8000/test/auth
```

### 4. Test Paper Processing

```bash
curl -X POST http://localhost:8000/api/process \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": "YOUR_PAPER_ID",
    "user_input": "Summarize the main points",
    "model": "gpt-4o-mini"
  }'
```

## Troubleshooting

### Server won't start

**Problem**: Missing or invalid credentials

**Solution**:
1. Check `.env` file exists and has all required variables
2. Verify Firebase private key includes escaped newlines (`\n`)
3. Test with just health endpoint first (doesn't require credentials)

### "Unable to load PEM file" Error

**Problem**: Firebase private key is empty or malformed

**Solution**:
1. Download fresh credentials from Firebase Console
2. When copying private key, ensure it's in this format:
   ```
   "-----BEGIN PRIVATE KEY-----\nMIIE...\n...\n-----END PRIVATE KEY-----\n"
   ```
3. The `\n` characters are literal backslash-n, not actual newlines

### "Service account info not in expected format"

**Problem**: Missing required OAuth2 fields

**Solution**: This should be handled automatically. If you see this error, verify your `firebase_service.py` includes these fields in the credential dictionary:
- `token_uri`
- `auth_uri`
- `auth_provider_x509_cert_url`

### CORS Errors

**Problem**: Next.js frontend can't connect to FastAPI

**Solution**:
1. Verify `ALLOWED_ORIGINS` in `.env` matches your Next.js URL (default: `http://localhost:3000`)
2. Check both servers are running
3. Ensure Next.js is using the correct FastAPI URL in `ProcessPaperDialog.tsx`

### OpenAI API Errors

**Problem**: Rate limit or API key issues

**Solution**:
1. Verify `OPENAI_API_KEY` is correct
2. Check your OpenAI account has credits/quota
3. Review logs in `fastapi.log` for detailed error messages

### Authentication Fails

**Problem**: Token verification fails

**Solution**:
1. Ensure Firebase Admin SDK credentials match your Firebase project
2. Verify the token is from the same Firebase project
3. Check token hasn't expired (tokens expire after 1 hour)
4. Make sure to include `Bearer ` prefix in Authorization header

## Logging

Logs are written to:
- `fastapi.log` (file)
- Console output (stdout)

Log level is INFO in debug mode, WARNING in production.

View logs:
```bash
tail -f fastapi.log
```

## Development

### Code Structure

- **main.py**: FastAPI app initialization, CORS, endpoints
- **models/**: Pydantic models for request/response validation
- **services/firebase_service.py**: Singleton service for Firebase Admin SDK operations (lazy initialization)
- **services/openai_service.py**: Singleton service for OpenAI API calls
- **services/paper_service.py**: Business logic for paper processing
- **middleware/auth.py**: Firebase token verification dependency
- **utils/config.py**: Environment configuration loader

### Design Patterns

- **Singleton Pattern**: Firebase and OpenAI services use singleton to avoid multiple initializations
- **Lazy Initialization**: Firebase only initializes when first needed, allowing server to start without credentials
- **Dependency Injection**: Auth middleware uses FastAPI's `Depends()` for token verification
- **Async/Await**: All I/O operations are async for better performance

## Next Steps

### Immediate
1. Add your Firebase Admin SDK credentials to `.env`
2. Add your OpenAI API key to `.env`
3. Deploy Firestore security rules: `firebase deploy --only firestore:rules`
4. Test the complete flow from Next.js UI

### Future Enhancements
- Multi-paper concurrent processing (with `asyncio.Semaphore`)
- Additional endpoints: `GET /api/results`, `GET /api/results/{result_id}`
- Streaming responses from OpenAI
- Rate limiting middleware
- Caching for frequently accessed papers
- Background job processing
- Production deployment (Cloud Run, Lambda, etc.)

## Support

For issues or questions:
1. Check the logs in `fastapi.log`
2. Verify environment variables are set correctly
3. Test endpoints individually (health → auth → process)
4. Review Firebase Console for Firestore errors
5. Check OpenAI dashboard for API usage/errors
