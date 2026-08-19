# Lexi: MVP Draft

**Date:** August 13, 2026
**Author:** Nally AI
**Status:** Draft v1
**Source:** Built from RESEARCH.md (competitive analysis)

---

## 1. Vision (one line)

The ChatGPT for Nigerian law — conversational, cited, and free for students.

We do not out-LEXIS LexisNexis. We out-user-friendly it.

## 2. Target User

- **Primary:** Nigerian law students, NYSC corpers, junior associates
- **Secondary:** solo practitioners who cannot afford LawPavilion or LexisNexis
- **Pain we solve:** existing tools are expensive, database-style, and not conversational. Students get 100-credit caps (LawPal) or contact-sales pricing (LawPavilion).

## 3. MVP Scope

### In Scope (v1)
1. Telegram chat bot — ask any Nigerian law question, get a plain-English answer with a source citation
2. RAG over a curated Nigerian law corpus (Constitution + top 10 acts)
3. Source attribution — every answer names the statute and section it drew from
4. `/sources` command — lists exactly what Lexi currently knows
5. `/help` command — explains usage and limits
6. Free, unlimited chat. No credits, no paywall on core Q&A

### Out of Scope (v1)
- Document generation (premium, v2)
- Case management, billing, CRM (that is ModulawAI's game, not ours)
- LexisNexis-level comprehensiveness
- Web app / mobile app
- Languages other than English

## 4. Architecture

```
User (Telegram)
    |
    v
Telegram Bot (python-telegram-bot)
    |
    v
Query -> Embedding -> Vector Store (Chroma, local)
    |                        |
    v                        v
LLM (Groq / Llama)  <---  Retrieved law chunks
    |
    v
Answer + citations -> Telegram
```

The bot never answers from model memory alone. It retrieves first, then generates grounded in the retrieved text. This is what keeps citations real instead of hallucinated.

## 5. Tech Stack

- **Language:** Python 3.12
- **Bot framework:** python-telegram-bot (matches the existing Lexi import skeleton)
- **LLM:** Groq (llama-3.3-70b) or opencode — config-driven, same pattern as Nally's `.env`
- **Embeddings:** sentence-transformers (local, zero cost) for MVP
- **Vector store:** Chroma (local file-backed, no hosted bill)
- **Hosting:** same VPS as Nally, or Railway/Render free tier
- **Data ingest:** OpenLawsNig public statutes + Nigerian Constitution (full text is public)

Telegram bot token is already provisioned (stored in memory as Lexi bot token).

## 6. Data Strategy (BLOCKER — decide before build)

From RESEARCH.md: ModulawAI's LexisNexis access is a real moat, but we do not need it to ship v1.

MVP data plan:
1. Nigerian Constitution — full public text
2. Curate top 10 most-asked statutes:
   - Criminal Code
   - Companies and Allied Matters Act (CAMA)
   - Evidence Act
   - Labour Act
   - Land Use Act
   - Marriage Act
   - Electoral Act
   - Child Rights Act
   - Federal High Court Act
   - Administration of Criminal Justice Act
3. Build a scrape/ingest script: fetch -> clean -> chunk (512 tokens) -> embed -> store in Chroma
4. v2: pursue a law-firm partnership for case-law depth

Open decision: does OpenLawsNig expose a usable API, or do we scrape? This gates Phase 0.

## 7. Pricing Model

- **Free:** unlimited chat on Nigerian law. This is the wedge that beats LawPal's 100-credit cap.
- **v2 Premium (planned):** document generation (10 templates: contracts, affidavits, pleadings), PDF export, priority answers.
- No credits on core chat, ever.

## 8. Build Phases

- **Phase 0:** Data ingestion script + Chroma index (1-2 days)
- **Phase 1:** Bot skeleton + `/help` + `/sources` (half day)
- **Phase 2:** RAG pipeline wired to LLM (1 day)
- **Phase 3:** Legal-tone prompt engineering + strict citation format (1 day)
- **Phase 4:** Deploy to VPS, beta test with 5 law students (2 days)
- **Total:** ~1 week solo

## 9. Open Questions

1. Data sourcing — OpenLawsNig API vs scrape?
2. LLM cost at scale — Groq free-tier rate limits?
3. Liability — need a "not a substitute for a licensed lawyer" disclaimer on every response
4. Accuracy bar — what is the tolerance for a wrong section citation?

## 10. Risks

- **Hallucinated citations** — mitigate with strict "only cite retrieved text" prompt + show raw source snippet
- **Data gaps vs LexisNexis** — mitigate by being honest about coverage in `/sources`
- **Free LLM rate limits** — mitigate by caching common queries

---

## Next Step

Resolve the OpenLawsNig API vs scrape question (Section 6), then start Phase 0.
