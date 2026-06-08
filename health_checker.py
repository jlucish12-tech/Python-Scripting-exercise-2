import os
import json
import time
import smtplib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


TIMEOUT_SECONDS = 5
SLOW_THRESHOLD_MS = 500
MAX_RETRIES = 2

ALERT_EMAIL = {
    "enabled": False,          
    "from":    "you@gmail.com",
    "to":      "you@gmail.com",
    "smtp":    "smtp.gmail.com",
    "port":    587,
    "password": "your_app_password", 
}



def load_servers():
    
    # Option A: environment variable
    env_val = os.environ.get("SERVERS")
    if env_val:
        urls = [u.strip() for u in env_val.split(",") if u.strip()]
        print(f"Loaded {len(urls)} servers from environment variable")
        return urls

    # Option B: config file
    if os.path.exists("servers.json"):
        with open("servers.json") as f:
            data = json.load(f)
        urls = data.get("servers", [])
        print(f"Loaded {len(urls)} servers from servers.json")
        return urls

    # Neither found
    raise RuntimeError(
        "No servers found. Set the SERVERS env variable or create servers.json"
    )



def check_server(url):
    
    attempt = 0
    last_error = None

    while attempt <= MAX_RETRIES:
        attempt += 1
        try:
            # Feature 3: measure response time
            start = time.time()
            response = requests.get(url, timeout=TIMEOUT_SECONDS)
            elapsed_ms = int((time.time() - start) * 1000)

            status_code = response.status_code

            # Feature 4: healthy = 200-299, unhealthy = 400+
            if 200 <= status_code <= 299:
                health = "OK"
            else:
                health = "DOWN"

            # Feature 5: validate JSON body for {"status": "ok"}
            note = ""
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("status") == "ok":
                    note = "status:ok"
            except Exception:
                pass

            # Feature 6: detect slow responses
            slow = elapsed_ms > SLOW_THRESHOLD_MS

            return {
                "url":         url,
                "status":      health,
                "status_code": status_code,
                "response_ms": elapsed_ms,
                "slow":        slow,
                "note":        note,
            }

        except requests.exceptions.Timeout:
            last_error = "TIMEOUT"
        except requests.exceptions.RequestException as e:
            last_error = f"ERROR: {e}"

    # All retries exhausted
    return {
        "url":         url,
        "status":      last_error or "TIMEOUT",
        "status_code": None,
        "response_ms": None,
        "slow":        False,
        "note":        f"Failed after {MAX_RETRIES + 1} attempts",
    }



def format_result(result):
    """Turns a result dict into a human-readable status line."""
    url   = result["url"]
    st    = result["status"]
    code  = result["status_code"]
    ms    = result["response_ms"]
    slow  = result["slow"]
    note  = result["note"]

    # Build status part
    if code is not None:
        status_str = f"{st} ({code})"
    else:
        status_str = st

    # Build time part
    time_str = f"— {ms}ms" if ms is not None else ""

    # Build tags
    tags = []
    if slow:
        tags.append("[slow]")
    if note:
        tags.append(f"[{note}]")
    tag_str = " ".join(tags)

    return f"{url:<45} — {status_str:<12} {time_str:<12} {tag_str}".rstrip()


def check_all_servers(servers):
   
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(check_server, url): url for url in servers}
        for future in as_completed(future_to_url):
            results.append(future.result())
    return results



def send_alert(failed_urls):
    
    if not ALERT_EMAIL["enabled"] or not failed_urls:
        return

    subject = f"[ALERT] {len(failed_urls)} service(s) down"
    body    = "Failed services:\n" + "\n".join(failed_urls)
    message = f"Subject: {subject}\n\n{body}"

    try:
        with smtplib.SMTP(ALERT_EMAIL["smtp"], ALERT_EMAIL["port"]) as server:
            server.starttls()
            server.login(ALERT_EMAIL["from"], ALERT_EMAIL["password"])
            server.sendmail(ALERT_EMAIL["from"], ALERT_EMAIL["to"], message)
        print("\n✓ Alert email sent")
    except Exception as e:
        print(f"\n✗ Failed to send alert: {e}")



if __name__ == "__main__":
    # Step 1: load servers
    servers = load_servers()

    # Step 2: check all servers in parallel
    print("\nChecking servers...\n")
    results = check_all_servers(servers)

    # Sort results so output is consistent
    results.sort(key=lambda r: r["url"])

    # Step 3: print each result
    for result in results:
        print(format_result(result))

    # Step 4: collect failed services (Feature 8)
    failed_services = [
        r["url"] for r in results
        if r["status"] not in ("OK",)
    ]

    # Step 5: print summary
    if failed_services:
        print(f"\nFailed services: {', '.join(failed_services)}")
    else:
        print("\nAll services are healthy ✓")

    # Step 6: send alerts if any failures
    send_alert(failed_services)
