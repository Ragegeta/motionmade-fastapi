cd C:\MM\motionmade-fastapi

$token = (Get-Content .env | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""

# Generate 50 diverse FAQs covering different topics
$stressFaqs = @(
    # Pricing (10 FAQs)
    @{question="Basic pricing"; answer="Our basic service starts at $99. Final price depends on size and condition."; variants=@("prices","how much","cost","rates","pricing","what do you charge","basic cost")},
    @{question="Premium pricing"; answer="Premium service is $199-299 depending on requirements."; variants=@("premium cost","premium price","upgraded service cost","deluxe pricing")},
    @{question="Hourly rate"; answer="Our hourly rate is $45/hour with a 2-hour minimum."; variants=@("hourly","per hour","hourly charge","rate per hour")},
    @{question="Quote process"; answer="We provide free quotes. Tell us your requirements and we'll give you an accurate price within 24 hours."; variants=@("get a quote","free quote","estimate","how to get quoted")},
    @{question="Price match"; answer="We offer price matching on comparable services. Show us a competitor quote and we'll match or beat it."; variants=@("price match","beat competitor","match price","competitor pricing")},
    @{question="Deposit required"; answer="We require a 20% deposit to secure your booking. The balance is due on completion."; variants=@("deposit","upfront payment","advance payment","booking fee")},
    @{question="Payment methods"; answer="We accept card, bank transfer, PayID, and cash. Invoice available for businesses."; variants=@("how to pay","payment options","pay by card","accept cash","payid")},
    @{question="Cancellation fees"; answer="Cancellations within 24 hours may incur a $50 fee. Earlier cancellations are free."; variants=@("cancel fee","cancellation charge","cancel cost")},
    @{question="Weekend rates"; answer="Weekend bookings have a 15% surcharge. Public holidays are 25% extra."; variants=@("weekend price","saturday cost","sunday rate","public holiday")},
    @{question="Bulk discount"; answer="We offer 10% off for recurring bookings and 15% for bulk orders over $500."; variants=@("discount","bulk pricing","recurring discount","volume discount")},
    
    # Services (10 FAQs)
    @{question="Services offered"; answer="We offer standard cleaning, deep cleaning, end-of-lease, carpet cleaning, and window cleaning."; variants=@("what services","what do you do","services available","types of service")},
    @{question="Standard clean inclusions"; answer="Standard clean includes all rooms, bathrooms, kitchen surfaces, vacuuming, and mopping."; variants=@("standard clean","basic clean","what's included standard","regular clean")},
    @{question="Deep clean inclusions"; answer="Deep clean adds oven, fridge interior, inside cupboards, detailed bathroom scrub, and window tracks."; variants=@("deep clean","detailed clean","thorough clean","intensive clean")},
    @{question="End of lease clean"; answer="End-of-lease includes everything for bond return: full deep clean plus carpet steam if needed."; variants=@("bond clean","end of lease","moving out clean","vacate clean","lease clean")},
    @{question="Oven cleaning"; answer="Oven cleaning is $89 as an add-on or included in deep clean packages."; variants=@("oven","clean oven","oven add-on","oven service")},
    @{question="Fridge cleaning"; answer="Fridge cleaning (interior and exterior) is $49 as an add-on."; variants=@("fridge","clean fridge","fridge interior","refrigerator")},
    @{question="Window cleaning"; answer="Window cleaning is priced per window: $8 standard, $15 for large/hard-to-reach."; variants=@("windows","window cleaning","clean windows","glass cleaning")},
    @{question="Carpet cleaning"; answer="Carpet steam cleaning is $35 per room or $150 for whole house (up to 4 bedrooms)."; variants=@("carpet","steam clean","carpet cleaning","carpets")},
    @{question="What we don't do"; answer="We don't do external windows above ground floor, hazardous waste, or hoarding situations."; variants=@("don't do","not included","excluded","limitations")},
    @{question="Custom requests"; answer="We accommodate most custom requests. Just ask and we'll let you know if we can help."; variants=@("custom","special request","specific needs","unusual request")},
    
    # Booking & Availability (10 FAQs)
    @{question="How to book"; answer="Book online at our website, call us, or send a message through this chat."; variants=@("book","make booking","schedule","how to book","reserve")},
    @{question="Availability"; answer="We typically have availability within 2-5 business days. Urgent bookings sometimes possible."; variants=@("availability","when available","next available","soonest booking")},
    @{question="Same day booking"; answer="Same-day bookings are sometimes available for an additional $30 urgent fee. Call to check."; variants=@("same day","today","urgent","emergency booking","asap")},
    @{question="Booking confirmation"; answer="You'll receive email confirmation within 1 hour of booking with all details."; variants=@("confirmation","booking confirmed","receipt","booking email")},
    @{question="Reschedule policy"; answer="Reschedule free of charge with 48+ hours notice. Less notice may incur a fee."; variants=@("reschedule","change booking","move appointment","different date")},
    @{question="Cancellation policy"; answer="Free cancellation with 24+ hours notice. Late cancellations may incur a $50 fee."; variants=@("cancel","cancellation","cancel booking")},
    @{question="Operating hours"; answer="We operate Monday-Saturday 7am-6pm. Sunday by special arrangement."; variants=@("hours","opening hours","when open","operating times","working hours")},
    @{question="Public holidays"; answer="We work most public holidays with 25% surcharge. Closed Christmas and New Year's Day."; variants=@("public holiday","holiday booking","christmas","easter")},
    @{question="Booking lead time"; answer="We recommend booking 3-5 days ahead for best availability. Last-minute often possible."; variants=@("advance booking","how far ahead","lead time","notice needed")},
    @{question="Group bookings"; answer="Multiple properties or large jobs? Contact us for custom scheduling and bulk rates."; variants=@("multiple properties","group booking","several houses","bulk booking")},
    
    # Logistics (10 FAQs)
    @{question="Service area"; answer="We service Brisbane metro, from Redcliffe to Logan, and west to Ipswich."; variants=@("service area","where service","suburbs","locations","coverage area","do you come to")},
    @{question="Travel fee"; answer="No travel fee within 20km of Brisbane CBD. $1/km beyond that."; variants=@("travel fee","travel charge","distance fee","how far")},
    @{question="Parking"; answer="Please arrange parking if possible. We can use street parking but may need to factor in walking time."; variants=@("parking","where to park","visitor parking","parking spot")},
    @{question="Access requirements"; answer="We need access to power and water. Keys or access codes needed if you won't be home."; variants=@("access","entry","keys","lockbox","how to access")},
    @{question="Do I need to be home"; answer="You don't need to be home. Just arrange access and we'll lock up when done."; variants=@("need to be there","be home","present","attend")},
    @{question="Supplies provided"; answer="We bring all supplies and equipment. You don't need to provide anything."; variants=@("supplies","bring equipment","cleaning products","materials")},
    @{question="Pet policy"; answer="Pets are fine! Just let us know so we can take care around them. Secure aggressive pets please."; variants=@("pets","dogs","cats","animals")},
    @{question="Duration estimate"; answer="Standard clean: 2-3 hours. Deep clean: 4-6 hours. Varies by size and condition."; variants=@("how long","duration","time needed","hours")},
    @{question="Team size"; answer="Usually 1-2 cleaners depending on job size. Larger jobs may have 3-4."; variants=@("how many people","team","cleaners","staff")},
    @{question="Equipment noise"; answer="We use standard vacuums and equipment. Let us know if you need quiet hours."; variants=@("noise","loud","vacuum noise","disturb neighbours")},
    
    # Trust & Quality (10 FAQs)
    @{question="Insurance"; answer="Yes, we're fully insured for public liability and property damage up to $10M."; variants=@("insurance","insured","liability","covered")},
    @{question="Guarantee"; answer="100% satisfaction guarantee. If you're not happy, we'll re-clean for free within 48 hours."; variants=@("guarantee","warranty","satisfaction","not happy")},
    @{question="Background checks"; answer="All our staff have police checks and references verified."; variants=@("background check","police check","trusted","vetted","safe")},
    @{question="Experience"; answer="We've been operating for 5+ years with over 2000 happy customers."; variants=@("experience","how long","years","established")},
    @{question="Reviews"; answer="Check our Google reviews - we maintain 4.8+ stars. Happy to share testimonials."; variants=@("reviews","testimonials","ratings","feedback","google reviews")},
    @{question="Complaints process"; answer="Any issues, contact us within 48 hours and we'll make it right. Usually same-day resolution."; variants=@("complaint","problem","issue","not satisfied","wrong")},
    @{question="Quality check"; answer="We do a walkthrough checklist on every job. Photos available on request."; variants=@("quality","checklist","standards","quality control")},
    @{question="Training"; answer="All staff complete our training program and shadow experienced cleaners before solo work."; variants=@("training","qualified","skilled","professional")},
    @{question="Eco-friendly options"; answer="We offer eco-friendly products on request at no extra charge. Just ask when booking."; variants=@("eco","green","environmental","natural products","eco-friendly")},
    @{question="COVID safety"; answer="We follow all health guidelines. Staff stay home if unwell. Masks available on request."; variants=@("covid","health","safety","masks","sanitize")}
)

Write-Host "=== CREATING STRESS TEST FAQS ===" -ForegroundColor Cyan
Write-Host "Generated $($stressFaqs.Count) FAQs" -ForegroundColor Green

# Save to file
$stressFaqsPath = ".\tenants\stress_test_50"
if (-not (Test-Path $stressFaqsPath)) {
    New-Item -ItemType Directory -Path $stressFaqsPath -Force | Out-Null
}
$stressFaqs | ConvertTo-Json -Depth 10 | Set-Content "$stressFaqsPath\faqs.json" -Encoding UTF8
Write-Host "Saved to $stressFaqsPath\faqs.json" -ForegroundColor Green

Write-Host "`n=== UPLOADING STRESS TEST FAQS ===" -ForegroundColor Cyan

# Upload to biz9_real (we'll use existing tenant to avoid domain setup)
$uploadBody = $stressFaqs | ConvertTo-Json -Depth 10 -Compress
$tmpFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmpFile, $uploadBody, [System.Text.Encoding]::UTF8)

try {
    $uploadResult = curl.exe -s -X PUT "https://motionmade-fastapi.onrender.com/admin/api/tenant/biz9_real/faqs/staged" `
        -H "Authorization: Bearer $token" `
        -H "Content-Type: application/json" `
        --data-binary "@$tmpFile" | ConvertFrom-Json
    Remove-Item $tmpFile -Force
    Write-Host "Upload successful: $($uploadResult.staged_count) FAQs staged" -ForegroundColor Green
} catch {
    Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue
    Write-Host "Upload failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Response: $($_.Exception.Response)" -ForegroundColor Yellow
}

Write-Host "`nWaiting 10 seconds for embeddings to generate..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

