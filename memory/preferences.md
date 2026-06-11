# Project-Specific Preferences

### No paid AI APIs for analysis
- **Rule:** All content classification (niche, visual, transcript) must use local/free models — no Claude API, no OpenAI chat/vision, no paid classification services
- **Why:** Cost — 10k creators/week makes per-call LLM costs unsustainable
- **How to apply:** If a feature genuinely needs an LLM, flag the cost estimate and discuss before building. Transcription APIs (like Whisper API at $0.006/min) may be acceptable if local Whisper is too slow — ask first.

### Temp files must be cleaned up
- **Rule:** Video files downloaded to `temp/` must be deleted immediately after a creator is processed
- **Why:** At 10k/week, accumulating video files would fill disk quickly
- **How to apply:** Always wrap download → process → delete in a try/finally block
