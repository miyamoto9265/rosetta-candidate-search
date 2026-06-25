"""Update CloudFront distribution alias to rcs.mymt.site."""
import json
import subprocess
import tempfile
from pathlib import Path

DIST_ID = "E103PFXH9IO864"
NEW_CERT = "arn:aws:acm:us-east-1:618703232062:certificate/f7cbc93e-59a2-4411-8272-14cb06378e8d"
NEW_ALIAS = "rcs.mymt.site"


def main() -> None:
    raw = subprocess.check_output(
        ["aws", "cloudfront", "get-distribution-config", "--id", DIST_ID],
        text=True,
    )
    payload = json.loads(raw)
    etag = payload["ETag"]
    config = payload["DistributionConfig"]

    config["Aliases"] = {"Quantity": 1, "Items": [NEW_ALIAS]}
    config["ViewerCertificate"] = {
        "CloudFrontDefaultCertificate": False,
        "ACMCertificateArn": NEW_CERT,
        "SSLSupportMethod": "sni-only",
        "MinimumProtocolVersion": "TLSv1.2_2021",
        "Certificate": NEW_CERT,
        "CertificateSource": "acm",
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(config, fh)
        config_path = fh.name

    subprocess.check_call(
        [
            "aws",
            "cloudfront",
            "update-distribution",
            "--id",
            DIST_ID,
            "--if-match",
            etag,
            "--distribution-config",
            f"file://{config_path}",
        ]
    )
    print(f"Updated CloudFront {DIST_ID} -> {NEW_ALIAS}")


if __name__ == "__main__":
    main()
