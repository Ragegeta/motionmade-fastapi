#!/bin/bash
# Delete test/demo tenants. KEEP: sparkys_electrical, brissy_cleaners, motionmade_demo
# Requires: ADMIN_TOKEN in .env, server running (or use API base URL).
# Usage: ./cleanup_test_tenants.sh [BASE_URL]
# Example: ./cleanup_test_tenants.sh
#          ./cleanup_test_tenants.sh https://api.motionmadebne.com.au

set -e
BASE="${1:-http://localhost:8000}"
if [ -f .env ]; then
  export $(grep -v '^#' .env | grep ADMIN_TOKEN | xargs)
fi
if [ -z "$ADMIN_TOKEN" ]; then
  echo "ADMIN_TOKEN not set. Add it to .env or export it."
  exit 1
fi

TO_DELETE=(
  test_plumber
  stress_test_50
  test_airbnb_cleaner
  final_test_tenant
  scale_test_plumber
  test_rollback_tenant
  test_staging_tenant
  test_admin_ui_tenant
  biz9_bench100
  biz9_real biz8_real biz7_real biz6_real biz5_real biz4_real biz3_real
  tenant2
  newbiz_demo1
  autodetail_demo1
  brightclean_demo
  sparkleclean_demo2 sparkleclean_demo
  sparkleclean
  motionmade
  default
  verify_test_biz
  motionmadebne
  motionmadebne.com.au
)

echo "Deleting ${#TO_DELETE[@]} test tenants (keeping sparkys_electrical, brissy_cleaners, motionmade_demo)..."
for id in "${TO_DELETE[@]}"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/admin/api/tenant/$id" -H "Authorization: Bearer $ADMIN_TOKEN")
  if [ "$code" = "200" ]; then
    echo "  Deleted: $id"
  elif [ "$code" = "404" ]; then
    echo "  Skip (not found): $id"
  else
    echo "  HTTP $code: $id"
  fi
done
echo "Done."
