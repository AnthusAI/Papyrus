#!/usr/bin/env bash
# E2E: PDF-only inbound email (synthetic MIME → S3 → receive → processor).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROFILE="${AWS_PROFILE:-Ryan}"
REGION="${AWS_REGION:-us-east-1}"
RECEIVE_FN="${PAPYRUS_INBOUND_RECEIVE_FUNCTION:-amplify-dbsyytcm9drqa-mai-papyrussesinboundreceive-vneS3Lzu34l2}"
PROCESSOR_FN="${PAPYRUS_EMAIL_PROCESSOR_FUNCTION:-amplify-dbsyytcm9drqa-mai-papyrusemailsubmissionpr-TP0Pll3fvbHs}"
SENDER="${PAPYRUS_INBOUND_TEST_SENDER:-ryan@anth.us}"
RECIPIENT="${PAPYRUS_INBOUND_TEST_RECIPIENT:-submissions@p.apyr.us}"
WAIT_SECONDS="${PAPYRUS_INBOUND_E2E_WAIT_SECONDS:-240}"

aws_cli() { aws --profile "$PROFILE" --region "$REGION" "$@"; }

BUCKET="${PAPYRUS_MEDIA_BUCKET_NAME:-}"
if [[ -z "$BUCKET" && -f amplify_outputs.json ]]; then
  BUCKET="$(python3 -c "import json; print(json.load(open('amplify_outputs.json')).get('storage',{}).get('bucket_name',''))")"
fi
if [[ -z "$BUCKET" ]]; then
  echo "ERROR: set PAPYRUS_MEDIA_BUCKET_NAME" >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RAND="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
REL_KEY="e2e-pdf-${STAMP}-${RAND}"
S3_KEY="inbound-email/${REL_KEY}"
ARCHIVE_KEY="inbound-email-archived/${REL_KEY}"
TEST_DOI="10.5555/papyrus.pdf.e2e.${STAMP}.${RAND}"
MIME_FILE="$(mktemp)"
trap 'rm -f "$MIME_FILE"' EXIT

export SENDER RECIPIENT STAMP TEST_DOI MIME_FILE
python3 <<'PY'
import os
import email.mime.application
import email.mime.multipart
import email.mime.text
from email.generator import BytesGenerator
from io import BytesIO

pdf = (
    b"%PDF-1.4\n"
    + f"DOI: {os.environ['TEST_DOI']}\n".encode()
    + b"%%EOF\n"
)
boundary = f"----PapyrusPdfE2E{os.environ['STAMP']}"
msg = email.mime.multipart.MIMEMultipart("mixed", boundary=boundary)
msg["From"] = os.environ["SENDER"]
msg["To"] = os.environ["RECIPIENT"]
msg["Subject"] = f"Papyrus E2E PDF-only {os.environ['STAMP']}"
msg.attach(email.mime.text.MIMEText("", "plain"))
pdf_part = email.mime.application.MIMEApplication(pdf, _subtype="pdf", Name="e2e-paper.pdf")
pdf_part.add_header("Content-Disposition", "attachment", filename="e2e-paper.pdf")
msg.attach(pdf_part)
buf = BytesIO()
BytesGenerator(buf).flatten(msg)
with open(os.environ["MIME_FILE"], "wb") as handle:
    handle.write(buf.getvalue())
PY

echo "Uploading PDF-only MIME to s3://${BUCKET}/${S3_KEY} (DOI ${TEST_DOI})"
aws_cli s3 cp "$MIME_FILE" "s3://${BUCKET}/${S3_KEY}"

RECEIVE_OUT="$(mktemp)"
trap 'rm -f "$MIME_FILE" "$RECEIVE_OUT"' EXIT
aws_cli lambda invoke \
  --function-name "$RECEIVE_FN" \
  --payload "{\"source\":\"aws.s3\",\"detail\":{\"bucket\":{\"name\":\"${BUCKET}\"},\"object\":{\"key\":\"${S3_KEY}\"}}}" \
  --cli-binary-format raw-in-base64-out \
  "$RECEIVE_OUT" >/dev/null
echo "=== Receive ==="
python3 -m json.tool "$RECEIVE_OUT"

MESSAGE_ID="$(python3 -c "import json; print(json.load(open('$RECEIVE_OUT')).get('messageId',''))")"

if [[ -z "$MESSAGE_ID" ]]; then
  echo "ERROR: no messageId from receive" >&2
  exit 1
fi

CITATIONS="$(python3 -c "import json; print(json.load(open('$RECEIVE_OUT')).get('directCitationCount', -1))")"
if [[ "$CITATIONS" != "0" ]]; then
  echo "ERROR: expected directCitationCount=0 for PDF-only MIME, got $CITATIONS" >&2
  exit 1
fi

echo "Waiting up to ${WAIT_SECONDS}s for archive..."
deadline=$(( $(date +%s) + WAIT_SECONDS ))
while [[ $(date +%s) -lt $deadline ]]; do
  if aws_cli s3api head-object --bucket "$BUCKET" --key "$ARCHIVE_KEY" >/dev/null 2>&1; then
    break
  fi
  sleep 10
done

if ! aws_cli s3api head-object --bucket "$BUCKET" --key "$ARCHIVE_KEY" >/dev/null 2>&1; then
  echo "WARN: archive not found; invoking processor directly" >&2
fi

PROC_OUT="$(mktemp)"
aws_cli lambda invoke \
  --function-name "$PROCESSOR_FN" \
  --payload "{\"messageId\":\"${MESSAGE_ID}\"}" \
  --cli-binary-format raw-in-base64-out \
  "$PROC_OUT" \
  --cli-read-timeout 600 >/dev/null
echo "=== Processor ==="
python3 -m json.tool "$PROC_OUT"

MODE="$(python3 -c "import json; print(json.load(open('$PROC_OUT')).get('mode',''))")"
OK="$(python3 -c "import json; print(json.load(open('$PROC_OUT')).get('ok', False))")"
if [[ "$OK" != "True" ]] || [[ "$MODE" != pdf_only* ]]; then
  echo "WARN: expected ok=True and mode pdf_only_intake*, got ok=$OK mode=$MODE" >&2
  exit 1
fi

echo "E2E PDF PASS messageId=${MESSAGE_ID} doi=${TEST_DOI} mode=${MODE}"
