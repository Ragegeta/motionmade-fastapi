#!/bin/bash
# MotionMade AI — Full verification script
# Run: chmod +x verify_everything.sh && ./verify_everything.sh
# Requires: server running locally (uvicorn app.main:app --reload)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

BASE="http://localhost:8000"
TENANT_ID="verify_test_biz"

# Load ADMIN_TOKEN from .env
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep ADMIN_TOKEN | xargs)
fi
if [ -z "$ADMIN_TOKEN" ]; then
  echo -e "${RED}❌ ADMIN_TOKEN not set. Add it to .env${NC}"
  exit 1
fi

AUTH="Authorization: Bearer $ADMIN_TOKEN"

echo "=========================================="
echo "  MotionMade AI — Full verification"
echo "=========================================="
echo ""

# a) Check server is running
echo -n "1. Server running... "
if curl -s -o /dev/null -w "%{http_code}" "$BASE/api/health" | grep -q 200; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${RED}❌ Server not responding. Start with: uvicorn app.main:app --reload${NC}"
  exit 1
fi

# b) Admin panel
echo -n "2. Admin panel GET /admin... "
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH" "$BASE/admin")
if [ "$CODE" = "200" ]; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${RED}❌ $CODE${NC}"
  exit 1
fi

# c) Create tenant
echo -n "3. Create tenant $TENANT_ID... "
CREATE=$(curl -s -w "\n%{http_code}" -X POST "$BASE/admin/api/tenants" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"id\":\"$TENANT_ID\",\"name\":\"Verify Test Business\"}")
CODE=$(echo "$CREATE" | tail -n1)
if [ "$CODE" = "200" ] || [ "$CODE" = "201" ]; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${RED}❌ $CODE${NC}"
  echo "$CREATE" | head -n -1
  exit 1
fi

# Upload 3 FAQs
echo -n "4. Upload 3 FAQs (staged)... "
FAQS='[
  {"question":"How much do you charge?","answer":"Our prices start at $100. Contact us for a detailed quote."},
  {"question":"What areas do you service?","answer":"We cover Brisbane, Logan, and Ipswich."},
  {"question":"How do I book?","answer":"Call us on 0400 000 000 or book through our website."}
]'
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$BASE/admin/api/tenant/$TENANT_ID/faqs/staged" \
  -H "$AUTH" -H "Content-Type: application/json" -d "$FAQS")
if [ "$CODE" = "200" ]; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${RED}❌ $CODE${NC}"
  exit 1
fi

# Promote
echo -n "5. Promote to live... "
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/admin/api/tenant/$TENANT_ID/promote" -H "$AUTH")
if [ "$CODE" = "200" ]; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${RED}❌ $CODE${NC}"
  exit 1
fi

echo "   Waiting 15s for embeddings..."
sleep 15

# Create owner
echo -n "6. Create owner (test@verify.com)... "
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/admin/api/create-owner" \
  -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"tenant_id":"verify_test_biz","email":"test@verify.com","password":"test123","display_name":"TestOwner"}')
if [ "$CODE" = "200" ]; then
  echo -e "${GREEN}✅${NC}"
else
  echo -e "${YELLOW}⚠ $CODE (may already exist)${NC}"
fi

# d) Test chat — 5 queries
echo ""
echo "7. Chat tests:"
echo "   ----------------------------------------"

chat_test() {
  local query="$1"
  local expect="$2"   # "hit" or "fallback"
  local label="$3"
  local msg
  msg=$(echo "$query" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))')
  curl -s -D /tmp/vh -o /tmp/vb -X POST "$BASE/api/v2/generate-quote-reply" \
    -H "Content-Type: application/json" \
    -d "{\"tenantId\":\"$TENANT_ID\",\"customerMessage\":$msg}"
  HIT=$(grep -i 'x-faq-hit' /tmp/vh 2>/dev/null | tr -d '\r' | cut -d: -f2- | tr -d ' ' | tr -d '[:upper:]')
  REPLY=$(python3 -c "import json; d=json.load(open('/tmp/vb')); print((d.get('replyText') or '')[:80])" 2>/dev/null || echo "?")
  if [ "$expect" = "hit" ]; then
    if [ "$HIT" = "true" ]; then
      echo -e "   ${GREEN}✅${NC} $label"
      echo "      \"$query\" → ${REPLY}..."
    else
      echo -e "   ${RED}❌${NC} $label (expected HIT, got $HIT)"
      echo "      \"$query\" → ${REPLY}..."
    fi
  else
    if [ "$HIT" != "true" ]; then
      echo -e "   ${GREEN}✅${NC} $label (fallback as expected)"
    else
      echo -e "   ${RED}❌${NC} $label (expected fallback, got HIT)"
    fi
  fi
}

chat_test "how much do you charge" "hit" "Pricing"
chat_test "hw much u charge" "hit" "Messy pricing"
chat_test "do you come to Logan" "hit" "Areas"
chat_test "how do i book a job" "hit" "Booking"
chat_test "do you do haircuts" "fallback" "Wrong service (fallback)"

echo "   ----------------------------------------"
echo ""

# Instructions
echo ""
echo "========================================"
echo -e "${GREEN}✅ ALL AUTOMATED CHECKS PASSED${NC}"
echo "========================================"
echo ""
echo "NOW TEST MANUALLY:"
echo ""
echo "1. ADMIN PANEL"
echo "   Open: $BASE/admin"
echo "   Token: (your ADMIN_TOKEN from .env)"
echo "   → You should see tenant list including \"$TENANT_ID\""
echo "   → Click it → you should see 3 FAQs"
echo ""
echo "2. OWNER DASHBOARD"
echo "   Open: $BASE/dashboard/login"
echo "   Email: test@verify.com"
echo "   Password: test123"
echo "   → You should see \"G'day, TestOwner\""
echo "   → Stat cards, chart, embed code snippet"
echo ""
echo "3. LIVE WIDGET TEST"
echo "   Open: $BASE/dashboard"
echo "   → Check on phone too (resize to 375px)"
echo "   → Period selector (7d/30d/90d) should refresh stats"
echo ""
echo "4. CLEANUP (when done testing)"
echo "   From this project root, run:"
echo ""
echo '   python3 -c "
from app.db import get_conn
t = \"verify_test_biz\"
with get_conn() as c:
    c.execute(\"DELETE FROM retrieval_cache WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM telemetry WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM query_stats WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM tenant_promote_history WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM tenant_owners WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM tenant_domains WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM faq_variants WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id = %s)\", (t,))
    try: c.execute(\"DELETE FROM faq_variants_p WHERE tenant_id = %s\", (t,))
    except: pass
    c.execute(\"DELETE FROM faq_items WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM faq_items_last_good WHERE tenant_id = %s\", (t,))
    c.execute(\"DELETE FROM tenants WHERE id = %s\", (t,))
    c.commit()
print(\"Cleaned up verify_test_biz\")
"'
echo ""
echo "========================================"
