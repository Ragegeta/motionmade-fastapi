$baseUrl = "https://api.motionmadebne.com.au/api/v2/generate-quote-reply"

function Test-One([string]$q) {
  $payload = @{
    tenantId="motionmade"; cleanType="standard"; bedrooms=2; bathrooms=1;
    condition="average"; pets="no"; addons=@(); preferredTiming="Friday morning";
    customerMessage=$q
  } | ConvertTo-Json -Depth 6 -Compress

  try {
    $r = Invoke-WebRequest -UseBasicParsing -Uri $baseUrl -Method POST -ContentType "application/json" -Body $payload -TimeoutSec 60
    $reply = ($r.Content | ConvertFrom-Json).replyText

    "{0}`n  x-debug-branch={1}  x-fact-gate-hit={2}  x-fact-domain={3}  x-faq-hit={4}  x-score={5}  x-delta={6}  x-top-faq={7}`n  replyText={8}`n" -f `
      $q, `
      $r.Headers['x-debug-branch'], `
      $r.Headers['x-fact-gate-hit'], `
      $r.Headers['x-fact-domain'], `
      $r.Headers['x-faq-hit'], `
      $r.Headers['x-retrieval-score'], `
      $r.Headers['x-retrieval-delta'], `
      $r.Headers['x-top-faq-id'], `
      $reply
  }
  catch {
    "{0}`n  ERROR={1}`n" -f $q, $_.Exception.Message
  }
}

$tests = @(
  "Oven cost?",
  "Can you steam clean carpets?",
  "What suburbs do you cover?",
  "u bring vacuum n products?",
  "What is the sun?",
  "Do you do pest control?"
)

foreach ($t in $tests) { Test-One $t }
