"""Read-only public release probes; never logs credentials or response bodies."""
import argparse
import json
from urllib.parse import urlsplit

import httpx


def run(api, origin, expected_revision):
    if urlsplit(api).scheme != "https" or urlsplit(origin).scheme != "https":
        raise ValueError("Use HTTPS deployment and frontend URLs.")
    results = {}
    with httpx.Client(base_url=api.rstrip("/"), timeout=60, follow_redirects=False) as client:
        live = client.get("/health/live")
        results["live"] = live.status_code == 200
        results["expected_revision"] = live.status_code == 200 and live.json().get("revision") == expected_revision
        results["ready"] = client.get("/health/ready").status_code == 200
        capabilities = client.get("/api/v1/capabilities")
        results["vector_enabled"] = capabilities.status_code == 200 and capabilities.json().get("embedding_provider") == "fastembed"
        results["anonymous_rejected"] = client.get("/api/v1/account/export").status_code == 401
        results["development_token_rejected"] = client.get("/api/v1/account/export", headers={"Authorization": "Bearer dev:release-probe:synthetic@example.com"}).status_code == 401
        cors = client.options("/api/v1/account/export", headers={"Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
        results["frontend_cors"] = cors.headers.get("access-control-allow-origin") == origin
    return {"passed": all(results.values()), "checks": results, "limits": "Read-only probes cannot verify actual sign-in, worker processing or end-user completion."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    try:
        result = run(args.api, args.frontend, args.revision)
    except Exception as exc:
        result = {"passed": False, "error_type": type(exc).__name__}
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
