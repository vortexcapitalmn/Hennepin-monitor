import requests
import json
import os
import smtplib
import time
import schedule
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ─────────────────────────────────────────

# CONFIG  (set these in Railway environment variables)

# ─────────────────────────────────────────

EMAIL_SENDER   = os.environ.get(“EMAIL_SENDER”)    # your Gmail address
EMAIL_PASSWORD = os.environ.get(“EMAIL_PASSWORD”)  # Gmail App Password
EMAIL_TO       = os.environ.get(“EMAIL_TO”)        # where to send alerts
SEEN_FILE      = “seen_records.json”

# Hennepin foreclosure API endpoints (discovered from site network calls)

BASE_URL  = “https://foreclosure.hennepin.us”
LIST_URL  = f”{BASE_URL}/api/sales”
DETAIL_URL = f”{BASE_URL}/api/sales/{{sale_id}}”

HEADERS = {
“Accept”: “application/json”,
“User-Agent”: “Mozilla/5.0 (compatible; ForeclosureMonitor/1.0)”,
}

# ─────────────────────────────────────────

# HELPERS

# ─────────────────────────────────────────

def load_seen():
if os.path.exists(SEEN_FILE):
with open(SEEN_FILE) as f:
return set(json.load(f))
return set()

def save_seen(seen: set):
with open(SEEN_FILE, “w”) as f:
json.dump(list(seen), f)

def fetch_all_sales():
“”“Fetch the full listing from Hennepin’s API.”””
try:
params = {
“page”: 1,
“pageSize”: 100,
“sortField”: “saleDate”,
“sortDirection”: “desc”,
}
resp = requests.get(LIST_URL, headers=HEADERS, params=params, timeout=30)
resp.raise_for_status()
data = resp.json()
# Handle both list and dict with ‘data’ key responses
if isinstance(data, list):
return data
return data.get(“data”, data.get(“items”, data.get(“results”, [])))
except Exception as e:
print(f”[{now()}] ERROR fetching sales list: {e}”)
# Fallback: try scraping the HTML page
return fetch_sales_html_fallback()

def fetch_sales_html_fallback():
“”“Fallback HTML scraper if JSON API is unavailable.”””
try:
from bs4 import BeautifulSoup
resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, “html.parser”)
records = []
# Parse sale record cards from the page
for card in soup.select(”[class*=‘sale’], [class*=‘record’], tr[data-id]”):
record_id = card.get(“data-id”) or card.get(“id”, “”)
if record_id:
records.append({“id”: record_id, “_html_element”: str(card)})
return records
except Exception as e:
print(f”[{now()}] ERROR in HTML fallback: {e}”)
return []

def fetch_detail(sale_id):
“”“Fetch full detail for a single sale.”””
try:
url = DETAIL_URL.format(sale_id=sale_id)
resp = requests.get(url, headers=HEADERS, timeout=30)
resp.raise_for_status()
return resp.json()
except Exception as e:
print(f”[{now()}] ERROR fetching detail for {sale_id}: {e}”)
return {}

def get_record_id(record):
“”“Extract the unique ID from a record dict.”””
for key in [“id”, “saleRecordNumber”, “saleId”, “recordNumber”, “sale_record_number”]:
if key in record:
return str(record[key])
return None

def format_email(detail: dict) -> tuple[str, str]:
“”“Return (subject, html_body) for a new lead email.”””

```
# Normalize field names (API may use camelCase or snake_case)
def g(*keys):
    for k in keys:
        v = detail.get(k)
        if v: return str(v)
    return "—"

address      = g("address", "unverifiedCommonAddress", "propertyAddress", "streetAddress")
sale_date    = g("saleDate", "dateOfSale", "sale_date", "date_of_sale")
sale_type    = g("saleType", "typeOfSale", "sale_type")
mortgagor    = g("mortgagors", "mortgagor", "borrower", "owner")
mortgagee    = g("mortgagee", "lender")
sold_to      = g("toWhomSold", "soldTo", "purchaser", "buyer")
bid          = g("finalBidAmount", "bidAmount", "salePrice", "final_bid_amount")
redemption   = g("redemptionExpirationDate", "redemptionDate", "redemption_date")
law_firm     = g("lawFirm", "attorney", "law_firm")
record_num   = g("saleRecordNumber", "id", "recordNumber")
doc_num      = g("mortgageDocumentNumber", "documentNumber")
notice       = g("noticeOfIntentToRedeem", "noticeIntent", "notice_of_intent")

subject = f"🚨 NEW Foreclosure Lead: {address}"

html = f"""
```

<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:auto;">
  <div style="background:#4a0e7a;color:white;padding:20px;border-radius:8px 8px 0 0;">
    <h1 style="margin:0;font-size:22px;">🚨 New Foreclosure Lead</h1>
    <p style="margin:5px 0 0;opacity:0.85;">Hennepin County Sheriff's Sale</p>
  </div>
  <div style="background:#f9f9f9;padding:20px;border:1px solid #ddd;border-top:none;border-radius:0 0 8px 8px;">

```
<h2 style="color:#4a0e7a;margin-top:0;">{address}</h2>

<table style="width:100%;border-collapse:collapse;">
  <tr style="background:#eee;"><td colspan="2" style="padding:8px;font-weight:bold;color:#555;">SALE INFO</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;width:45%;color:#777;">Record #</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{record_num}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Sale Date</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;">{sale_date}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Type</td><td style="padding:8px;border-bottom:1px solid #eee;">{sale_type}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Mortgage Doc #</td><td style="padding:8px;border-bottom:1px solid #eee;">{doc_num}</td></tr>

  <tr style="background:#eee;"><td colspan="2" style="padding:8px;font-weight:bold;color:#555;">PARTIES</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Mortgagor (Owner)</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;color:#c0392b;">{mortgagor}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Mortgagee (Lender)</td><td style="padding:8px;border-bottom:1px solid #eee;">{mortgagee}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Sold To</td><td style="padding:8px;border-bottom:1px solid #eee;">{sold_to}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Law Firm</td><td style="padding:8px;border-bottom:1px solid #eee;">{law_firm}</td></tr>

  <tr style="background:#eee;"><td colspan="2" style="padding:8px;font-weight:bold;color:#555;">FINANCIALS</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Final Bid</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;font-size:18px;color:#27ae60;">{bid}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;color:#777;">Redemption Expires</td><td style="padding:8px;border-bottom:1px solid #eee;font-weight:bold;color:#e67e22;">{redemption}</td></tr>
  <tr><td style="padding:8px;color:#777;">Notice of Intent to Redeem</td><td style="padding:8px;">{notice}</td></tr>
</table>

<div style="margin-top:20px;padding:12px;background:#fff3cd;border-radius:6px;border-left:4px solid #f39c12;">
  <strong>⏰ Redemption Window:</strong> Owner has until <strong>{redemption}</strong> to redeem this property.
</div>

<div style="margin-top:15px;text-align:center;">
  <a href="{BASE_URL}" style="background:#4a0e7a;color:white;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;">
    View on Hennepin County Site →
  </a>
</div>

<p style="margin-top:20px;font-size:12px;color:#aaa;text-align:center;">
  Sent by your Hennepin Foreclosure Monitor · {now()}
</p>
```

  </div>
</body></html>
"""
    return subject, html

def send_email(subject: str, html_body: str):
msg = MIMEMultipart(“alternative”)
msg[“Subject”] = subject
msg[“From”]    = EMAIL_SENDER
msg[“To”]      = EMAIL_TO
msg.attach(MIMEText(html_body, “html”))

```
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(EMAIL_SENDER, EMAIL_PASSWORD)
    server.sendmail(EMAIL_SENDER, EMAIL_TO, msg.as_string())
print(f"[{now()}] ✅ Email sent: {subject}")
```

def now():
return datetime.now().strftime(”%Y-%m-%d %H:%M:%S”)

# ─────────────────────────────────────────

# MAIN CHECK LOOP

# ─────────────────────────────────────────

def check_for_new_sales():
print(f”[{now()}] 🔍 Checking Hennepin County foreclosure site…”)
seen = load_seen()
sales = fetch_all_sales()

```
if not sales:
    print(f"[{now()}] ⚠️  No records returned (site may be down). Will retry next hour.")
    return

new_count = 0
for record in sales:
    record_id = get_record_id(record)
    if not record_id:
        continue
    if record_id not in seen:
        print(f"[{now()}] 🆕 NEW record found: {record_id}")
        # Fetch full detail
        detail = fetch_detail(record_id)
        if not detail:
            detail = record  # use what we have from list
        try:
            subject, html = format_email(detail)
            send_email(subject, html)
        except Exception as e:
            print(f"[{now()}] ERROR sending email for {record_id}: {e}")
        seen.add(record_id)
        new_count += 1

save_seen(seen)
print(f"[{now()}] ✅ Done. {new_count} new lead(s) found. Total tracked: {len(seen)}")
```

# ─────────────────────────────────────────

# ENTRY POINT

# ─────────────────────────────────────────

if **name** == “**main**”:
print(f”[{now()}] 🚀 Hennepin Foreclosure Monitor starting…”)
# Run immediately on startup
check_for_new_sales()
# Then every hour
schedule.every(1).hours.do(check_for_new_sales)
while True:
schedule.run_pending()
time.sleep(60)
