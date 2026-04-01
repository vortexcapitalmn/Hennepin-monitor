import requests
import json
import os
import smtplib
import time
import schedule
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from bs4 import BeautifulSoup

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_TO = os.environ.get("EMAIL_TO")
SEEN_FILE = "seen_records.json"

API_URL = "https://api.hennepincounty.gov/hcso-public-services-api/v1/Foreclosure/Search"
DETAIL_URL = "https://api.hennepincounty.gov/hcso-public-services-api/v1/Foreclosure/"
HENNEPIN_SEARCH_URL = "https://www16.co.hennepin.mn.us/pins/addresssearch"
ECRV_SEARCH_URL = "https://www.mndor.state.mn.us/ecrv_search/app/findEcrvByParcelId"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://foreclosure.hennepin.us",
    "Referer": "https://foreclosure.hennepin.us/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Ocp-Apim-Subscription-Key": "e522a816143443189f09de85c4288b98",
}

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BASE_PAYLOAD = {
    "address": None,
    "city": None,
    "dateOfSale": None,
    "mortgagorName": None,
    "pagination": {"activePage": 1, "pageSize": 100}
}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(list(seen)), f)


def fetch_sales():
    all_records = []
    page = 1
    while True:
        try:
            payload = dict(BASE_PAYLOAD)
            payload["pagination"] = {"activePage": page, "pageSize": 100}
            resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            records = None
            if isinstance(data, list):
                records = data
            else:
                for key in ["data", "items", "results", "records", "foreclosures", "value"]:
                    if key in data:
                        records = data[key]
                        break
            if not records:
                print(f"No more records found on page {page}")
                break
            print(f"Fetched page {page} with {len(records)} records")
            all_records.extend(records)
            if len(records) < 100:
                break
            page += 1
            time.sleep(0.5)
        except Exception as e:
            print("ERROR fetching sales: " + str(e))
            break
    return all_records


def fetch_detail(record_id):
    try:
        resp = requests.get(DETAIL_URL + str(record_id), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print("ERROR fetching detail for " + str(record_id) + ": " + str(e))
        return {}


def get_record_id(record):
    for key in ["saleRecordNumber", "id", "recordNumber", "saleId"]:
        if key in record and record[key]:
            return str(record[key])
    return None


def g(detail, *keys):
    for k in keys:
        v = detail.get(k)
        if not v:
            continue
        if isinstance(v, list):
            values = []
            for item in v:
                if isinstance(item, dict):
                    if item.get("display"):
                        values.append(str(item["display"]))
                    elif item.get("name"):
                        values.append(str(item["name"]))
                else:
                    values.append(str(item))
            return "<br>".join(values) if values else "N/A"
        if isinstance(v, dict):
            if v.get("display"):
                return str(v["display"])
            if v.get("name"):
                return str(v["name"])
        return str(v)
    return "N/A"


def is_2026_sale(detail):
    sale_date_str = g(detail, "saleDate", "dateOfSale")
    if sale_date_str == "N/A":
        return False
    skip_months = ["Jan 2026", "January 2026", "Feb 2026", "February 2026", "01/2026", "02/2026"]
    for month in skip_months:
        if month.lower() in sale_date_str.lower():
            return False
    return "2026" in sale_date_str


def get_parcel_id(address_str):
    try:
        parts = address_str.strip().split(" ")
        house_num = parts[0]
        street_name = " ".join(parts[1:])
        cities = ["Minneapolis", "Robbinsdale", "Brooklyn Park", "Brooklyn Center",
                  "Golden Valley", "Eden Prairie", "Edina", "Bloomington", "Plymouth",
                  "Maple Grove", "Minnetonka", "Richfield", "Crystal", "New Hope",
                  "Hopkins", "St Louis Park", "Saint Louis Park"]
        for city in cities:
            street_name = re.sub(r'\b' + city + r'\b', '', street_name, flags=re.IGNORECASE).strip()
        params = {
            "houseNumber": house_num,
            "streetName": street_name,
            "recordsPerPage": 20
        }
        resp = requests.get(HENNEPIN_SEARCH_URL, params=params, headers=WEB_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for elem in soup.find_all(string=re.compile(r'\d{2}-\d{3}-\d{2}-\d{2}-\d{4}')):
            pid = elem.strip()
            print("Found PID: " + pid)
            return pid
        print("No PID found for: " + address_str)
        return None
    except Exception as e:
        print("ERROR getting parcel ID: " + str(e))
        return None


def get_ecrv_info(parcel_id):
    try:
        parcel_id_clean = parcel_id.replace("-", "")
        params = {
            "searchType": "completed",
            "county": "27",
            "parcelId": parcel_id_clean
        }
        resp = requests.get(ECRV_SEARCH_URL, params=params, headers=WEB_HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        ecrv_link = None
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "ecrv" in href.lower() or link.get_text(strip=True).isdigit():
                ecrv_link = href
                if not ecrv_link.startswith("http"):
                    ecrv_link = "https://www.mndor.state.mn.us" + ecrv_link
                break
        if not ecrv_link:
            print("No eCRV link found for parcel: " + parcel_id)
            return None
        print("Found eCRV: " + ecrv_link)
        resp2 = requests.get(ecrv_link, headers=WEB_HEADERS, timeout=30)
        resp2.raise_for_status()
        soup2 = BeautifulSoup(resp2.text, "html.parser")
        text = soup2.get_text()
        info = {"ecrv_url": ecrv_link}
        name_match = re.search(r"Person name:\s*\n\s*(.+)", text)
        if name_match:
            info["owner_name"] = name_match.group(1).strip()
        phone_match = re.search(r"Phone number:\s*([\(\d\)\s\-]+)", text)
        if phone_match:
            info["owner_phone"] = phone_match.group(1).strip()
        addr_match = re.search(r"Address:\s*\n\s*(.+)", text)
        if addr_match:
            info["owner_address"] = addr_match.group(1).strip()
        return info
    except Exception as e:
        print("ERROR getting eCRV info: " + str(e))
        return None


def format_email(detail, parcel_id=None, ecrv_info=None):
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

    if parcel_id:
        html += "<p><b>Parcel ID:</b> " + parcel_id + "</p>"

    if ecrv_info:
        html += "<div style='margin-top:20px;padding:15px;background:#e8f4e8;border-left:4px solid green;border-radius:4px;'>"
        html += "<h3 style='color:green;margin-top:0;'>Current Owner Contact Info</h3>"
        if ecrv_info.get("owner_name"):
            html += "<p><b>Name:</b> " + ecrv_info["owner_name"] + "</p>"
        if ecrv_info.get("owner_phone"):
            html += "<p><b>Phone:</b> <span style='font-size:18px;color:green;'>" + ecrv_info["owner_phone"] + "</span></p>"
        if ecrv_info.get("owner_address"):
            html += "<p><b>Address:</b> " + ecrv_info["owner_address"] + "</p>"
        if ecrv_info.get("ecrv_url"):
            html += "<p><a href='" + ecrv_info["ecrv_url"] + "'>View Full eCRV Document</a></p>"
        html += "</div>"
    elif parcel_id:
        html += "<div style='margin-top:20px;padding:15px;background:#fff3cd;border-left:4px solid orange;border-radius:4px;'>"
        html += "<p><b>No eCRV found</b> — property likely purchased before 2014.</p>"
        html += "</div>"

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
            print(f"Email attempt {attempt} failed for {subject}: {e}")
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
    print("Loaded seen records: " + str(len(seen)))
    sales = fetch_sales()
    if not sales:
        print("No records returned")
        return
    print("Found " + str(len(sales)) + " total records across all pages")
    new_count = 0
    skipped_non_2026 = 0
    for record in sales:
        record_id = get_record_id(record)
        if not record_id:
            continue
        if record_id in seen:
            continue
        print("NEW record candidate: " + record_id)
        detail = fetch_detail(record_id)
        if not detail:
            detail = record
        if not is_2026_sale(detail):
            skipped_non_2026 += 1
            print("Skipping non-2026 record: " + record_id)
            seen.add(record_id)
            continue
        address = g(detail, "address", "unverifiedCommonAddress", "propertyAddress")
        parcel_id = None
        ecrv_info = None
        if address and address != "N/A":
            print("Looking up parcel ID for: " + address)
            parcel_id = get_parcel_id(address)
            if parcel_id:
                time.sleep(1)
                print("Looking up eCRV for: " + parcel_id)
                ecrv_info = get_ecrv_info(parcel_id)
        try:
            subject, html = format_email(detail, parcel_id, ecrv_info)
            success = send_email(subject, html)
            if success:
                seen.add(record_id)
                new_count += 1
                print("Marked seen: " + record_id)
            else:
                print("FAILED permanently, will retry next run: " + record_id)
        except Exception as e:
            print("ERROR sending email for " + record_id + ": " + str(e))
        time.sleep(1.5)
    save_seen(seen)
    print("Done. " + str(new_count) + " new 2026 leads emailed.")
    print("Skipped non-2026 leads: " + str(skipped_non_2026))
    print("Total tracked: " + str(len(seen)))


if __name__ == "__main__":
    print("Hennepin Foreclosure Monitor starting...")
    check_for_new_sales()
    schedule.every(1).hours.do(check_for_new_sales)
    while True:
        schedule.run_pending()
        time.sleep(60)
