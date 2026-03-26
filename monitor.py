import requests
import json
import os
import smtplib
import time
import schedule
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from bs4 import BeautifulSoup

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")
SEEN_FILE = "seen_records.json"
BASE_URL = "https://foreclosure.hennepin.us"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
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
        resp = requests.get(BASE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        records = []
        for row in soup.find_all(["tr", "div", "li"], attrs={"data-id": True}):
            records.append({"id": row.get("data-id"), "html": str(row)})
        if not records:
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                if "sale" in href.lower() or "record" in href.lower():
                    record_id = href.split("/")[-1]
                    if record_id.isdigit():
                        records.append({"id": record_id, "href": href, "text": link.get_text()})
        print("Found " + str(len(records)) + " records on page")
        return records
    except Exception as e:
        print("ERROR fetching page: " + str(e))
        return []

def fetch_detail(record_id):
    try:
        url = BASE_URL + "/sale/" + str(record_id)
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        detail = {"id": record_id}
        for row in soup.find_all(["tr", "div"]):
            text = row.get_text(separator="|").strip()
            if "|" in text:
                parts = text.split("|")
                if len(parts) == 2:
                    detail[parts[0].strip()] = parts[1].strip()
        return detail
    except Exception as e:
        print("ERROR fetching detail: " + str(e))
        return {}

def send_email(subject, body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_TO
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_TO, msg.as_string())
    print("Email sent: " + subject)

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def check_for_new_sales():
    print("[" + now() + "] Checking Hennepin County...")
    seen = load_seen()
    sales = fetch_sales()
    if not sales:
        print("No records found - site may be down or structure changed")
        return
    new_count = 0
    for record in sales:
        record_id = str(record.get("id", ""))
        if not record_id:
            continue
        if record_id not in seen:
            print("NEW record: " + record_id)
            detail = fetch_detail(record_id)
            subject = "NEW Foreclosure Lead #" + record_id
            body = "<html><body style='font-family:Arial;padding:20px;'>"
            body += "<h2 style='color:#4a0e7a;'>New Foreclosure Lead</h2>"
            body += "<p><b>Record ID:</b> " + record_id + "</p>"
            for k, v in detail.items():
                if k != "id":
                    body += "<p><b>" + str(k) + ":</b> " + str(v) + "</p>"
            body += "<br><a href='" + BASE_URL + "'>View on Hennepin County Site</a>"
            body += "</body></html>"
            try:
                send_email(subject, body)
            except Exception as e:
                print("ERROR sending email: " + str(e))
            seen.add(record_id)
            new_count += 1
    save_seen(seen)
    print("Done. " + str(new_count) + " new leads. Total: " + str(len(seen)))

if __name__ == "__main__":
    print("Hennepin Foreclosure Monitor starting...")
    check_for_new_sales()
    schedule.every(1).hours.do(check_for_new_sales)
    while True:
        schedule.run_pending()
        time.sleep(60)
