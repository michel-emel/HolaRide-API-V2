# Patch hrskills_pay.py — get_payment_status returns full dict not just status
import sys
path = sys.argv[1]
with open(path) as f:
    content = f.read()

old = '''def get_payment_status(reference: str) -> dict:
    """
    Returns full payment data dict with at least:
      status: PENDING | SUCCESS | FAILED
      error_code: e.g. "703108"
      error_message: human-readable failure reason
      failure_reason_category: e.g. "operator_balance" | "user_cancelled"
    """
    headers = {
        "Authorization": f"Bearer {settings.hrskills_key_a}",
        "X-Transaction-Token": _get_transaction_token(),
    }
    resp = _get(f"{BASE_URL}/v1/payments/{reference}", headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]'''

new = '''def get_payment_status(reference: str) -> dict:
    """
    Returns full payment data dict with at least:
      status: PENDING | SUCCESS | FAILED
      error_code: e.g. "703108"
      error_message: human-readable failure reason
      failure_reason_category: e.g. "operator_balance" | "user_cancelled"
    """
    headers = {
        "Authorization": f"Bearer {settings.hrskills_key_a}",
        "X-Transaction-Token": _get_transaction_token(),
    }
    resp = _get(f"{BASE_URL}/v1/payments/{reference}", headers=headers)
    resp.raise_for_status()
    return resp.json()["data"]'''

content = content.replace(old, new)
with open(path, "w") as f:
    f.write(content)
print("✓ get_payment_status returns dict")