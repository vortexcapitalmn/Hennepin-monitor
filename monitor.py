import requests
import json
import os
import smtplib
import time
import schedule
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")
SEEN_FILE = "seen_records.json"

API_URL = "https://api.hennepincounty.gov/hcso-public-services-api/v1/Foreclosure/Search"
DETAIL_URL = "https://api.hennepincounty.gov/hcso-public-services-api/v1/Foreclosure/"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://foreclosure.hennepin.us",
    "Referer": "https://foreclosure.hennepin.us/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Ocp-Apim-Subscription-Key": "e522a816143443189f09de85c4288b98",
}

PAYLOAD = {
    "address": None,
    "city": None,
    "dateOfSale": None,
    "mortgagorName": None,
    "pagination": {"activePage": 1, "pageSize": 100}
}

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)

def fetch_sales():
    try:
        resp = requests.post(API_URL, headers=HEADERS, json=PAYLOAD, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        for key in ["data", "items", "results", "records", "foreclosures", "value"]:
            if key in data:
                return data[key]
        return []
    except Exception as e:
        print("ERROR fetching sales: " + str(e))
        return []

def fetch_detail(record_id):
    try:
        resp = requests.get(DETAIL_URL + str(record_id), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("ERROR fetching detail: " + str(e))
        return {}

def get_record_id(record):
    for key in ["saleRecordNumber", "id", "recordNumber", "saleId"]:
        if key in record:
            return str(record[key])
    return None

def g(detail, *keys):
    for k in keys:
        v = detail.get(k)
        if v:
            return str(v)
    return "N/A"

def format_email(detail):
    address = g(detail, "address", "unverifiedCommonAddress", "propertyAddress")
    sale_date = g(detail, "saleDate", "dateOfSale")
    sale_type = g(detail, "saleType", "typeOfSale")
    mortgagor = g(detail, "mortgagors", "mortgagorName", "mortgagor", "borrower")
    mortgagee = g(detail, "mortgagee", "lender")
    sold_to = g(detail, "toWhomSold", "soldTo", "purchaser")
    bid = g(detail, "finalBidAmount", "bidAmount", "salePrice")
    redemption = g(detail, "redemptionExpirationDate", "redemptionDate")
    law_firm = g(detail, "lawFirm", "attorney")
    record_num = g(detail, "saleRecordNumber", "id", "recordNumber")
    doc_num = g(detail, "mortgageDocumentNumber", "documentNumber")

    subject = "NEW Foreclosure Lead: " + address

    html = "<html><body style='font-family:Arial,sans-serif;max-width:600px;margin:auto;'>"
    html += "<div style='background:#4a0e7a;color:white;padding:20px;'>"
    html += "<h1>New Foreclosure Lead</h1></div>"
    html += "<div style='padding:20px;border:1px solid #ddd;'>"
    html += "<h2 style='color:#4a0e7a;'>" + address + "</h2>"
    html += "<p><b>Record #:</b> " + record_num + "</p>"
    html += "<p><b>Sale Date:</b> " + sale_date + "</p>"
    html += "<p><b>Type:</b> " + sale_type + "</p>"
    html += "<p><b>Mortgage Doc #:</b> " + doc_num + "</p>"
    html += "<p><b>Owner (Mortgagor):</b> <span style='color:red;'>" + mortgagor + "</span></p>"
    html += "<p><b>Lender (Mortgagee):</b> " + mortgagee + "</p>"
    html += "<p><b>Sold To:</b> " + sold_to + "</p>"
    html += "<p><b>Law Firm:</b> " + law_firm + "</p>"
    html += "<p><b>Final Bid:</b> <span style='color:green;font-size:18px;'>" + bid + "</span></p>"
    html += "<p><b>Redemption Expires:</b> <span style='color:orange;'>" + redemption + "</span></p>"
    html += "<br><a href='https://foreclosure.hennepin.us' style='background:#4a0e7a;color:white;padding:10px 20px;text-decoration:none;'>View on Hennepin County Site</a>"
    html += "</div></body></html>"

    return subject, html

def send_email(subject, html_body, max_retries=3):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(html_body, "html"))

    for attempt in range(1, max_retries + 1):
        server = None
        try:
            server = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_TO], msg.as_string())
            print("Email sent: " + subject)
            return True
        except Exception as e:
            print(f"Email attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(5)
            else:
                return False
        finally:
            if server:
                try:
                    server.quit()
                except:
                    pass

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def check_for_new_sales():
    print("[" + now() + "] Checking Hennepin County...")
    seen = load_seen()
    sales = fetch_sales()

    if not sales:
        print("No records returned")
        return

    print("Found " + str(len(sales)) + " total records")
    new_count = 0

    for record in sales:
        record_id = get_record_id(record)
        if not record_id:
            continue

        if record_id not in seen:
            print("NEW record: " + record_id)
            detail = fetch_detail(record_id)
            if not detail:
                detail = record

            try:
                subject, html = format_email(detail)
                success = send_email(subject, html)

                if success:
                    seen.add(record_id)
                    new_count += 1
                    print("Marked seen: " + record_id)
                else:
                    print("FAILED permanently, will retry next run: " + record_id)

            except Exception as e:
                print("ERROR sending email: " + str(e))

            time.sleep(1.5)

    save_seen(seen)
    print("Done. " + str(new_count) + " new leads. Total tracked: " + str(len(seen)))

if __name__ == "__main__":
    print("Hennepin Foreclosure Monitor starting...")
    check_for_new_sales()
    schedule.every(1).hours.do(check_for_new_sales)
    while True:
        schedule.run_pending()
        time.sleep(60)
