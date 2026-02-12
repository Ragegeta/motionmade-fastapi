# CURSOR AGENT TASK: Build MotionMade Business Owner Dashboard

## YOUR ROLE
You are building a new feature for MotionMade AI — a chat widget SaaS for local service businesses (cleaners, tradies, electricians). You are adding a **business owner dashboard** so each tenant's owner can log in and see how their chat widget is performing.

**IMPORTANT: Test everything yourself. Run the server locally, hit the endpoints, check the UI renders. Fix bugs automatically. Do NOT declare done until it works end-to-end.**

---

## FULL PROJECT CONTEXT

### What MotionMade Is
A chat widget that auto-answers customer questions for local service businesses. Customer visits a tradie's website → chat bubble appears → customer asks "how much for bond cleaning?" → bot answers from the business's FAQ database.

### Tech Stack
- **Backend:** FastAPI (Python) on Render — main file is `main.py` (~3,970 lines)
- **Database:** Neon PostgreSQL (async via asyncpg)
- **Routing:** Cloudflare Worker handles domain→tenant mapping, CORS, rate limiting
- **AI:** OpenAI embeddings (text-embedding-3-small) + GPT-4o-mini for answer generation
- **Frontend:** Currently just a simple admin page served by FastAPI at `/admin`

### Current Authentication
- Single `ADMIN_TOKEN` environment variable
- Used for all admin operations (create tenant, upload FAQs, etc.)
- **No per-tenant auth exists yet** — this is what we're building

### Database Tables (Relevant)
```sql
-- Existing tables you'll find:
tenants (id, tenant_id TEXT UNIQUE, display_name, created_at, config JSONB)
faq_items (id, tenant_id, question, answer, category, ...)
faq_variants (id, faq_item_id, variant_text, embedding vector, ...)
retrieval_cache (...)

-- Existing telemetry table:
-- Logs every query with: tenant_id, query_hash, response_hash, timestamps, timing data
-- Privacy-safe (hashes, not raw text)
-- CHECK the actual schema in main.py — column names may vary
```

### Current Admin UI (at /admin)
- Single page, protected by shared ADMIN_TOKEN
- Can: create tenants, upload FAQs as JSON, promote staged→live, view tenant list
- This is the SUPER ADMIN panel — only Abbed uses it
- **Do NOT break or modify the existing admin functionality**

---

## WHAT TO BUILD

### 1. Tenant Owner Authentication System

Create a simple, secure auth system so each business owner can log in to see THEIR data only.

**Implementation:**

a) **New database table: `tenant_owners`**
```sql
CREATE TABLE IF NOT EXISTS tenant_owners (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ
);
```

b) **Auth endpoints:**
- `POST /owner/login` — email + password → returns JWT token
- `POST /owner/logout` — invalidates session (optional, JWT is stateless)
- `GET /owner/me` — returns owner profile + tenant info

c) **Super admin endpoint to create owner accounts:**
- `POST /admin/create-owner` — (protected by ADMIN_TOKEN) creates an owner account for a tenant
- Body: `{ "tenant_id": "sparkys_electrical", "email": "mike@sparkyselec.com.au", "password": "temp123", "display_name": "Mike" }`
- Hash password with bcrypt
- This is how Abbed onboards new customers — he creates their account

d) **JWT middleware:**
- Use `python-jose` for JWT tokens
- Token contains: `tenant_id`, `owner_id`, `exp`
- All `/owner/*` dashboard endpoints require valid JWT
- Owners can ONLY see data for their own tenant_id

**Dependencies to add:** `bcrypt`, `python-jose[cryptography]`
**New env var:** `JWT_SECRET` — generate a random 64-char hex string, add to .env

---

### 2. Analytics Endpoints (Data Layer)

Build endpoints that pull stats from the telemetry table. **Read the actual telemetry table schema in main.py first** — adapt field names to match what exists.

**Endpoints (all under `/owner/` prefix, all JWT-protected):**

a) **`GET /owner/dashboard`** — Main stats
Returns:
```json
{
    "tenant_id": "sparkys_electrical",
    "display_name": "Sparky's Electrical",
    "period": "last_7_days",
    "total_queries": 142,
    "queries_today": 18,
    "queries_this_week": 142,
    "queries_this_month": 580,
    "avg_per_day": 20.3,
    "busiest_day": "Monday",
    "busiest_hour": 14,
    "trend": "up",
    "trend_pct": 12.5
}
```
- Support `?period=7d|30d|90d` query param
- `trend` compares current period to previous period (e.g., this week vs last week)

b) **`GET /owner/dashboard/daily`** — Daily breakdown for charts
Returns array of `{ "date": "2026-02-10", "count": 23 }` for the selected period.

c) **`GET /owner/dashboard/top-questions`** — Most common queries
- Since we only store hashes, this might be limited
- **CHECK**: if there's ANY way to get human-readable query info from the telemetry data
- If not, we'll need to start logging sanitized/categorized query summaries (see section 4)
- At minimum, return query volume patterns even if we can't show exact questions

d) **`GET /owner/dashboard/fallbacks`** — Unanswered queries count
- Queries where the bot returned a fallback response
- This is the upsell hook: "12 questions your bot couldn't answer this week — want to add more FAQs?"

---

### 3. Business Owner Dashboard (Frontend)

**THIS IS THE MAIN DELIVERABLE.** A clean, mobile-first web page that business owners bookmark and check on their phone.

**Route:** `/dashboard` (served by FastAPI, like `/admin` is)
**Auth:** Redirect to `/dashboard/login` if no valid JWT in localStorage

**Design Principles:**
- **Tradie-friendly.** Big numbers, plain English. "42 questions answered this week" not "query volume metrics"
- **Mobile-first.** These people check on their phone between jobs
- **Fast.** No heavy frameworks. Vanilla JS + minimal CSS, or lightweight like Alpine.js if needed
- **Clean.** White background, one accent color (#2563EB blue), plenty of whitespace
- **Feels professional.** This is what justifies $100/month — it needs to look like it's worth it

**Pages/Views:**

#### Login Page (`/dashboard/login`)
- Clean centered card
- Email + password fields
- "MotionMade" logo/text at top
- Error handling for wrong credentials
- On success: store JWT in localStorage, redirect to `/dashboard`

#### Main Dashboard (`/dashboard`)
- **Header:** "G'day, Mike 👋" (use display_name) + tenant name + logout button
- **Hero stat cards (top row, 2-3 cards):**
  - "Questions Answered This Week" — BIG number (e.g., "142") with trend arrow ↑12%
  - "Answered Today" — today's count
  - "Couldn't Answer" — fallback count with subtle "Add more FAQs?" link
- **Chart:** Simple bar chart showing daily query volume for last 7 days
  - Use a lightweight chart lib (Chart.js via CDN) or pure CSS bars
  - Label axes clearly: days of week, number of questions
- **Period selector:** "Last 7 days | Last 30 days | Last 90 days" — simple tab/button toggle
- **Bottom section:** 
  - "Your Chat Widget" — shows the embed code snippet they can copy
  - "Need help? Text Abbed at 04XXXXXXXX" (placeholder, make it configurable)
- **Footer:** "Powered by MotionMade AI"

#### Mobile Considerations
- Cards stack vertically on mobile
- Touch-friendly buttons (min 44px tap targets)
- No tiny text — minimum 16px body
- Chart should be readable on 375px width

**Implementation Notes:**
- Serve as static HTML from FastAPI (like the admin page)
- Use fetch() to call the `/owner/*` API endpoints
- JWT stored in localStorage, sent as `Authorization: Bearer <token>` header
- If JWT expired/invalid, redirect to login
- Use CSS Grid or Flexbox for layout — no framework needed
- Chart.js CDN: `https://cdn.jsdelivr.net/npm/chart.js`

---

### 4. Query Logging Enhancement (If Needed)

**CHECK the telemetry table first.** If it only stores hashes (no human-readable data), we need to add optional aggregate logging for the dashboard to be useful.

If needed, create:
```sql
CREATE TABLE IF NOT EXISTS query_stats (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    query_date DATE NOT NULL DEFAULT CURRENT_DATE,
    hour_of_day INT,
    total_queries INT DEFAULT 0,
    successful_matches INT DEFAULT 0,
    fallback_count INT DEFAULT 0,
    avg_confidence FLOAT,
    -- NO raw query text for privacy
    UNIQUE(tenant_id, query_date, hour_of_day)
);
```

Then update the query processing pipeline to increment these counters on each request. Use `INSERT ... ON CONFLICT DO UPDATE` (upsert) to keep it efficient.

**This is the pragmatic middle ground:** useful stats without storing customer PII.

---

### 5. Super Admin Enhancements

Add to the EXISTING admin panel (don't break anything):

- **"Create Owner Account" form** — tenant dropdown + email + temp password
- **Per-tenant stats view** — so Abbed can see any tenant's stats from the admin panel
- **"Active tenants" indicator** — which tenants have had queries in the last 7 days

---

## FILE STRUCTURE

**Do NOT refactor main.py into modules yet.** Add new code to main.py following the existing patterns. Match the existing code style:
- Same async/await patterns
- Same error handling approach  
- Same database connection patterns (check how `get_db_connection()` or equivalent works)
- Same response format patterns

New files:
- `templates/dashboard.html` — owner dashboard (or serve inline like admin if that's the pattern)
- `templates/dashboard_login.html` — login page
- `static/dashboard.css` — styles (if not inline)
- `static/dashboard.js` — client-side logic (if not inline)

**OR** if the admin page is served as an inline HTML string in main.py, follow that same pattern for the dashboard.

---

## STEP-BY-STEP EXECUTION ORDER

1. **Read main.py thoroughly first.** Understand the existing patterns, database helpers, admin endpoints, telemetry table schema. Pay special attention to how the admin HTML page is served.

2. **Create the `tenant_owners` table** — add migration logic (CREATE TABLE IF NOT EXISTS) in the startup function alongside existing table creation.

3. **Create the `query_stats` table** — same approach.

4. **Build auth system** — bcrypt + JWT, login endpoint, middleware.

5. **Build analytics endpoints** — pull from telemetry + new query_stats table.

6. **Update query pipeline** — add query_stats counter increment to the main query processing flow.

7. **Build the dashboard frontend** — login page, then main dashboard.

8. **Add admin enhancements** — create-owner form in existing admin UI.

9. **Test the full flow:**
   - Create an owner account via admin
   - Log in as that owner at /dashboard/login
   - Verify stats show up
   - Verify mobile layout works
   - Verify JWT expiry/invalid redirects to login
   - Verify owners can ONLY see their own tenant data
   - Verify existing admin functionality still works
   - Verify the main chat query pipeline still works and now increments stats

10. **Fix any issues found in testing. Repeat until clean.**

---

## TESTING CHECKLIST (Verify ALL before declaring done)

- [ ] Server starts without errors
- [ ] Existing `/admin` page still works with ADMIN_TOKEN
- [ ] `POST /admin/create-owner` creates an owner account
- [ ] `POST /owner/login` returns JWT for valid credentials
- [ ] `POST /owner/login` returns 401 for invalid credentials
- [ ] `GET /owner/dashboard` returns stats (with valid JWT)
- [ ] `GET /owner/dashboard` returns 401 without JWT
- [ ] Owner can only see their own tenant's data
- [ ] `/dashboard/login` page renders and works
- [ ] `/dashboard` page renders with stats
- [ ] Dashboard is responsive (check at 375px width)
- [ ] Chart renders with real or mock data
- [ ] Existing query pipeline still works
- [ ] Query stats are being incremented on new queries
- [ ] No new errors in logs

---

## ENVIRONMENT VARIABLES NEEDED

Add to `.env`:
```
JWT_SECRET=<generate-random-64-char-hex>
```

Add to `requirements.txt`:
```
bcrypt
python-jose[cryptography]
```

---

## TONE & LANGUAGE FOR THE DASHBOARD UI

Use plain Australian English. Examples:
- "Questions answered" not "Queries processed"
- "Couldn't answer" not "Fallback rate"  
- "This week" not "Rolling 7-day period"
- "Your busiest day is Monday" not "Peak query day: Monday"
- "G'day, Mike" not "Welcome, Michael"
- "Add more FAQs" not "Expand knowledge base"

---

## CRITICAL REMINDERS

1. **Read main.py FIRST.** Don't assume the schema — verify it.
2. **Don't break existing functionality.** The admin panel, chat widget, and query pipeline must keep working.
3. **Match existing code patterns.** Don't introduce new patterns or frameworks into main.py.
4. **Test after each major step.** Don't build everything then test at the end.
5. **Mobile-first CSS.** Design for phone screens, then scale up.
6. **Security:** Owners must NEVER see other tenants' data. JWT must contain tenant_id. Always filter by it.
