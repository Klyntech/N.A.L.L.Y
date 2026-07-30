---
name: research
description: Web research, synthesis, summarization. Search multiple sources, cross-reference, cite sources, summarize documents/code/conversations. Use for research tasks, content synthesis, or summarization.
allowed-tools: web_search read_file
---

# Research

Web research, synthesis, and summarization in one skill.

## Research Workflow

### Step 1: Understand the Goal

**Research:**
- Restate the question to confirm understanding
- Identify type: factual, comparative, exploratory, technical
- Note constraints (recency, specificity, source quality)

**Summarization:**
- What's being summarized? (document, code, conversation, article)
- What level of detail? (TL;DR, key points, full summary)
- Who's the audience? (executive, developer, beginner)
- What format? (bullet points, paragraph, structured)

### Step 2: Search Strategy (Research)

1. Start with 2-3 search queries covering different angles:
   - Direct query: exact topic
   - Broader query: related context
   - Technical query: implementation specifics (if applicable)
2. For each query, examine top 5-8 results
3. Prioritize:
   - Official documentation (over blog posts)
   - Recent results (last 12 months for fast-moving topics)
   - Primary sources (over secondhand summaries)
   - Technical depth over surface-level overviews

### Step 3: Cross-Reference

1. Facts appearing in 2+ independent sources — reliable
2. Contradictions — investigate further
3. Check dates — information may be outdated
4. Look for author expertise or source authority
5. Dismiss SEO content with no substance

### Step 4: Summarize Content

**For Documents/Code:**
1. Read the full content (don't skim)
2. Identify the main purpose/argument
3. Extract key points (3-7 for most content)
4. Note important details that support each point
5. Identify any action items or next steps

**For Conversations:**
1. What was discussed? (topics covered)
2. What was decided? (decisions made)
3. What are the action items? (who does what)
4. What's unresolved? (parking lot items)

**For Code:**
1. What does this code do? (one sentence)
2. How does it work? (key mechanisms)
3. What are the dependencies? (imports, services)
4. What are the edge cases? (error handling, limits)

### Step 5: Output Formats

**Research Output:**
```
## Research: [Topic]

### Summary
[2-3 sentence answer to the question]

### Key Findings
1. **[Finding 1]** — [evidence and context]
2. **[Finding 2]** — [evidence and context]
3. **[Finding 3]** — [evidence and context]

### Details
[Deeper explanation organized by subtopic]

### Caveats
- [Limitation or caveat 1]
- [Limitation or caveat 2]

### Sources
1. [Title](URL) — [brief note on relevance]
2. [Title](URL) — [brief note on relevance]
```

**TL;DR Summary:**
```
**TL;DR:** [One sentence summary]

**Key points:**
- [Point 1]
- [Point 2]
- [Point 3]

**Action items:**
- [ ] [Action 1]
- [ ] [Action 2]
```

**Structured Summary:**
```
## Summary: [Document/Topic]

### Purpose
[What this is about, why it exists]

### Key Information
| Category | Details |
|----------|---------|
| [Category 1] | [Key info] |
| [Category 2] | [Key info] |

### Important Details
[Supporting information, examples, context]

### Action Items
[What needs to be done, if any]

### Related
[Links to related topics, if relevant]
```

**Code Summary:**
```
## Code Summary: [file/module]

**What it does:** [One sentence]

**Key components:**
- `function/class` — [purpose]
- `function/class` — [purpose]

**Dependencies:** [list of external deps]

**Edge cases:** [known limitations]
```

## Quality Standards

- Always cite sources — never present unsourced claims
- Distinguish between facts and opinions
- Note when information may be outdated
- If no good answer exists, say so clearly
- Provide actionable takeaways, not just raw information
- Keep response focused — don't wander off-topic
- For summaries: preserve original meaning, don't add interpretation
- For long documents: use progressive disclosure (TL;DR first, details after)
