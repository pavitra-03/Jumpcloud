import os
import sys
import time
import logging
import requests

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("JumpCloudAutomation")

# ============================================================
# CONFIGURATION & PARAMETERS
# ============================================================
BASE_URL = os.getenv("JUMPCLOUD_BASE_URL", "https://console.in.jumpcloud.com")
API_KEY = os.getenv("JUMPCLOUD_API_KEY")

if not API_KEY:
    logger.error("JUMPCLOUD_API_KEY environment variable is missing!")
    sys.exit(1)

HEADERS = {
    "x-api-key": API_KEY,
    "Accept": "application/json",
    "Content-Type": "application/json"
}

USER_COUNT = int(os.getenv("JC_USER_COUNT", "50"))
POLICY_COUNT = int(os.getenv("JC_POLICY_COUNT", "10"))
POLICY_TEMPLATE_ID = os.getenv("JC_POLICY_TEMPLATE_ID", "69cda87f3d90b00001ab37d4")
ALERT_WAIT_SECONDS = int(os.getenv("JC_ALERT_WAIT_SECONDS", "15"))


# ============================================================
# HELPER: RETRY MECHANISM
# ============================================================
def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """
    Send an API request with automatic retry handling for HTTP 429 rate limits.
    """
    max_retries = 4
    for attempt in range(max_retries):
        try:
            response = requests.request(
                method,
                url,
                headers=HEADERS,
                timeout=30,
                **kwargs
            )

            if response.status_code != 429:
                return response

            retry_after = int(response.headers.get("Retry-After", "5"))
            logger.warning(f"Rate limited (429). Attempt {attempt + 1}/{max_retries}. Retrying in {retry_after}s...")
            time.sleep(retry_after)

        except requests.RequestException as err:
            logger.error(f"Network exception on request to {url}: {err}")
            if attempt == max_retries - 1:
                raise

    return response


# ============================================================
# 1. CREATE USERS
# ============================================================
def create_users() -> list:
    logger.info(f"--- Stage 1: Creating {USER_COUNT} users ---")
    created_users = []
    
    # Generate unique run ID using epoch timestamp to prevent email collisions
    run_id = int(time.time())

    for i in range(1, USER_COUNT + 1):
        username = f"api.auto.{run_id}.user{i:03d}"
        payload = {
            "username": username,
            "email": f"{username}@example.com",
            "firstname": "API",
            "lastname": f"User{i:03d}"
        }

        response = request_with_retry(
            "POST",
            f"{BASE_URL}/api/systemusers",
            json=payload
        )

        if response.status_code in (200, 201):
            user = response.json()
            user_id = user.get("_id") or user.get("id") or user.get("objectId")
            created_users.append({"id": user_id, "username": username})
            logger.info(f"[{i:02d}/{USER_COUNT}] Created: {username} | ID: {user_id}")
        else:
            logger.error(f"[{i:02d}/{USER_COUNT}] Failed: {username} | Status: {response.status_code} | {response.text}")

        time.sleep(0.2)

    logger.info(f"Successfully created {len(created_users)} / {USER_COUNT} users.")
    return created_users


# ============================================================
# 2. CREATE POLICIES
# ============================================================
def create_policies() -> list:
    logger.info(f"--- Stage 2: Creating {POLICY_COUNT} policies ---")
    created_policies = []

    for i in range(1, POLICY_COUNT + 1):
        payload = {
            "name": f"API Automation Policy {i}",
            "notes": "Created by Python API automation script",
            "template": {
                "id": POLICY_TEMPLATE_ID
            },
            "values": []
        }

        response = request_with_retry(
            "POST",
            f"{BASE_URL}/api/v2/policies",
            json=payload
        )

        if response.status_code in (200, 201):
            policy = response.json()
            policy_id = policy.get("id")
            created_policies.append(policy_id)
            logger.info(f"[{i:02d}/{POLICY_COUNT}] Created policy: {policy.get('name')} | ID: {policy_id}")
        else:
            logger.error(f"[{i:02d}/{POLICY_COUNT}] Failed policy creation | Status: {response.status_code} | {response.text}")

        time.sleep(0.2)

    logger.info(f"Successfully created {len(created_policies)} / {POLICY_COUNT} policies.")
    return created_policies


# ============================================================
# 3. DELETE USERS
# ============================================================
def delete_users(users: list) -> int:
    logger.info(f"--- Stage 3: Deleting all {len(users)} created users ---")
    deleted_count = 0

    for user in users:
        user_id = user.get("id")
        username = user.get("username")

        if not user_id:
            logger.warning(f"Skipping user {username}: ID missing")
            continue

        response = request_with_retry(
            "DELETE",
            f"{BASE_URL}/api/systemusers/{user_id}"
        )

        if response.status_code in (200, 204):
            deleted_count += 1
            logger.info(f"[{deleted_count:02d}/{len(users)}] Deleted user: {username}")
        else:
            logger.error(f"Failed to delete {username} | Status: {response.status_code} | {response.text}")

        time.sleep(0.2)

    logger.info(f"Successfully deleted {deleted_count} users.")
    return deleted_count


# ============================================================
# 4. FETCH ALERTS
# ============================================================
def list_alerts() -> None:
    logger.info("--- Stage 4: Fetching directory alerts ---")

    response = request_with_retry(
        "GET",
        f"{BASE_URL}/api/v2/alerts",
        params={"limit": 100}
    )

    if response.status_code != 200:
        logger.error(f"Failed to retrieve alerts | Status: {response.status_code} | Response: {response.text}")
        return

    data = response.json()

    if isinstance(data, list):
        alerts = data
    elif isinstance(data, dict):
        alerts = data.get("results") or data.get("alerts") or data.get("data") or []
    else:
        alerts = []

    logger.info(f"Total alerts returned: {len(alerts)}")
    for alert in alerts:
        alert_id = alert.get("objectId") or alert.get("id") or alert.get("_id")
        logger.info(f"Alert ID: {alert_id} | Details: {alert}")


# ============================================================
# ENTRYPOINT
# ============================================================
def main():
    logger.info("Starting JumpCloud API Automation Run")
    logger.info(f"Target Instance: {BASE_URL}")

    users = create_users()

    if not users:
        logger.error("No users created. Terminating sequence.")
        sys.exit(1)

    logger.info(f"Pausing {ALERT_WAIT_SECONDS}s to allow user creation events to propagate...")
    time.sleep(ALERT_WAIT_SECONDS)

    create_policies()
    delete_users(users)

    logger.info(f"Pausing {ALERT_WAIT_SECONDS}s to allow deletion event alerts to generate...")
    time.sleep(ALERT_WAIT_SECONDS)

    list_alerts()
    logger.info("JumpCloud API Automation completed successfully.")


if __name__ == "__main__":
    main()
