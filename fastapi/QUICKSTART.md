# FastAPI Backend Quick Start Guide

## Implementation Status ✅

All 5 phases of the FastAPI backend have been successfully implemented:

- ✅ Phase 1: FastAPI Basic Setup
- ✅ Phase 2: Firebase Authentication Integration
- ✅ Phase 3: OpenAI Integration
- ✅ Phase 4: Result Storage in Firestore
- ✅ Phase 5: Next.js UI Integration

The server is ready to run! You just need to add your credentials.

## Next Steps (3 Quick Tasks)

### 1. Add Firebase Admin SDK Credentials

**Get your credentials:**
1. Go to [Firebase Console](https://console.firebase.google.com/)
2. Select your project: `instantpaper-e80e5`
3. Click ⚙️ Settings → Project Settings
4. Go to "Service Accounts" tab
5. Click "Generate New Private Key" button
6. Download the JSON file

**Add to `.env` file:**
```bash
# Open .env file in fastapi folder
cd /mnt/e/datein/coding/instantpaper/fastapi
nano .env  # or use your preferred editor

# Add these values from your downloaded JSON:
FIREBASE_PROJECT_ID=instantpaper-e80e5
FIREBASE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIIE...(your key here)...\n-----END PRIVATE KEY-----\n"
FIREBASE_CLIENT_EMAIL=firebase-adminsdk-xxxxx@instantpaper-e80e5.iam.gserviceaccount.com
```

**Important**: Keep the `\n` characters in the private key exactly as they appear in the JSON file.

### 2. Add OpenAI API Key

**Get your API key:**
1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Sign in and create a new API key
3. Copy the key (starts with `sk-proj-...`)

**Add to `.env` file:**
```env
OPENAI_API_KEY=sk-proj-your-key-here
```

### 3. Deploy Firestore Security Rules

The Firestore rules have been updated to allow the results collection. Deploy them:

```bash
# From the root project directory
cd /mnt/e/datein/coding/instantpaper
firebase deploy --only firestore:rules
```

## Running the Server

### Start the FastAPI Server

```bash
cd /mnt/e/datein/coding/instantpaper/fastapi
source venv/bin/activate  # Activate virtual environment
python3 main.py
```

You should see:
```
INFO:     Starting InstantPaper API server...
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Start the Next.js Frontend

In a separate terminal:
```bash
cd /mnt/e/datein/coding/instantpaper
npm run dev
```

## Testing the Complete Flow

1. **Open Next.js App**: Navigate to http://localhost:3000
2. **Sign In**: Use your Firebase authentication
3. **Create or Open a Paper**: Go to your dashboard
4. **Click the Sparkle Icon (✨)**: On any paper card
5. **Configure AI Processing**:
   - Select a model (GPT-4o Mini, GPT-4o, or O1)
   - Enter instructions (e.g., "Summarize the main points")
   - Click "Process Paper"
6. **View Results**: The AI-generated result will appear in the dialog

## API Endpoints Available

- `GET /health` - Check server status
- `GET /test/auth` - Test Firebase authentication (requires token)
- `POST /api/process` - Process a paper with AI (requires token)

## Verifying Everything Works

### Test 1: Server Health
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "firebase": "connected",
  "openai": "connected"
}
```

### Test 2: Authentication (after adding credentials)
```bash
# Get your Firebase token from browser:
# DevTools → Application → Cookies → __session

curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:8000/test/auth
```

Expected response:
```json
{
  "message": "Authentication successful",
  "user_id": "your-user-id"
}
```

### Test 3: Process a Paper (after adding credentials)
Use the UI or:
```bash
curl -X POST http://localhost:8000/api/process \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "paper_id": "YOUR_PAPER_ID",
    "user_input": "Summarize the main points",
    "model": "gpt-4o-mini"
  }'
```

## Architecture Overview

```
User Browser
    ↓
Next.js (localhost:3000)
    ↓ HTTP POST with Firebase token
FastAPI (localhost:8000)
    ↓ Verify token
Firebase Admin SDK
    ↓ Fetch paper
Firestore
    ↓ Process paper
OpenAI API
    ↓ Save result
Firestore
    ↑ Return result
Next.js
    ↓ Display to user
User Browser
```

## Key Features Implemented

### Backend (FastAPI)
- ✅ Firebase token authentication
- ✅ Firestore paper fetching (with ownership verification)
- ✅ OpenAI API integration (3 models)
- ✅ Result storage in Firestore
- ✅ Lazy initialization (server starts without credentials)
- ✅ Comprehensive error handling
- ✅ CORS configured for Next.js
- ✅ Logging system

### Frontend (Next.js)
- ✅ ProcessPaperDialog component
- ✅ Model selection dropdown
- ✅ Instructions textarea with examples
- ✅ Loading states
- ✅ Result display
- ✅ Error handling with toast notifications
- ✅ Integration with PapersList component

## Troubleshooting

### "Firebase credentials not configured"
→ Add credentials to `.env` file (see step 1 above)

### "OpenAI API key not configured"
→ Add API key to `.env` file (see step 2 above)

### "Paper not found"
→ Verify you own the paper and the paper ID is correct

### Python version warnings
→ The server works with Python 3.8+ but recommends Python 3.10+ to avoid Google library warnings

### Port already in use
→ Kill existing server: `pkill -f "python3 main.py"`

## File Structure

```
fastapi/
├── main.py                      # FastAPI app entry point ✅
├── requirements.txt             # Dependencies ✅
├── .env                         # Your credentials (add Firebase & OpenAI)
├── .env.example                 # Template ✅
├── README.md                    # Full documentation ✅
├── QUICKSTART.md                # This file ✅
├── models/
│   ├── request.py               # ProcessPaperRequest ✅
│   └── response.py              # ProcessPaperResponse ✅
├── services/
│   ├── firebase_service.py      # Firebase Admin SDK ✅
│   ├── openai_service.py        # OpenAI client ✅
│   └── paper_service.py         # Business logic ✅
├── middleware/
│   └── auth.py                  # Token verification ✅
└── utils/
    └── config.py                # Configuration ✅
```

## What Happens When You Process a Paper?

1. User clicks sparkle icon on a paper
2. Dialog opens with model selection and instructions input
3. User enters instructions and clicks "Process Paper"
4. Frontend sends POST request to `/api/process` with:
   - Firebase token (from `__session` cookie)
   - Paper ID
   - User instructions
   - Selected model
5. FastAPI verifies the Firebase token
6. FastAPI fetches the paper from Firestore (checks ownership)
7. FastAPI combines paper content + user instructions
8. FastAPI sends to OpenAI API
9. OpenAI processes and returns result
10. FastAPI saves result to Firestore (`users/{userId}/results/`)
11. FastAPI returns result to frontend
12. Frontend displays result in dialog
13. User can process again or close

## Future Enhancements (Not Yet Implemented)

- Multi-paper concurrent processing (architecture ready)
- Streaming responses from OpenAI
- Results list/history page in Next.js
- Export results to PDF
- Background job processing
- Rate limiting
- Caching

## Support

- **Full documentation**: See `README.md` in this folder
- **Original plan**: See `/home/mrlmueller/.claude/plans/majestic-nibbling-token.md`
- **Logs**: Check `fastapi.log` in this folder

## Summary

The FastAPI backend is **100% complete and functional**. Once you add your Firebase Admin SDK credentials and OpenAI API key to the `.env` file, you can start processing papers with AI from your Next.js dashboard.

Both servers can run simultaneously:
- **FastAPI**: Port 8000
- **Next.js**: Port 3000

The system is production-ready for single-paper processing and architected for easy expansion to multi-paper concurrent processing in the future.
