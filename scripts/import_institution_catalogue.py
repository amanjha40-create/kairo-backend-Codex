"""Reproducibly ingest only the supplied CSV; never execute the archive's code/SQL."""

import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from app.catalogues.institutions import DATA_PATH, clean_text


def build(archive: Path) -> dict:
    with ZipFile(archive) as bundle:
        member = bundle.getinfo("colleges-api-master/data/colleges.csv")
        if member.file_size > 20_000_000:
            raise ValueError("Catalogue exceeds bounded input size")
        raw = bundle.read(member)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    fields = ("name", "state", "district", "city", "address_line1", "address_line2", "pin_code")
    if set(reader.fieldnames or []) != {"id", *fields}:
        raise ValueError("Unexpected CSV schema")
    unique = {}
    count = rejected = 0
    for row in reader:
        count += 1
        if None in row or any(row[k] is None for k in ("id", *fields)):
            raise ValueError("Malformed CSV row")
        values = tuple(clean_text(row[k]) for k in fields)
        if not values[0] or not row["id"].strip():
            rejected += 1
            continue
        # Require equivalence across all location/address fields, not name alone.
        key = tuple(v.casefold() for v in values)
        if key not in unique:
            ident = hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()
            unique[key] = {"id": "in-he-v1-" + ident,
                           **dict(zip(fields[:4], values[:4], strict=True)), "source_ids": []}
        unique[key]["source_ids"].append(row["id"].strip())
    rows = sorted(unique.values(), key=lambda r: r["id"])
    for row in rows:
        row["source_ids"] = sorted(set(row["source_ids"]))
    return {"version": "india-he-v1", "provenance": {
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "csv_sha256": hashlib.sha256(raw).hexdigest(),
        "member": "colleges-api-master/data/colleges.csv",
        "source_claim": "Archive README attributes data to data.gov.in AISHE survey",
        "archive_csv_timestamp": "2023-02-05; survey year not verified",
        "input_rows": count, "rejected_rows": rejected,
        "equivalent_rows_removed": count - rejected - len(rows),
        "licence_status": "No explicit licence file supplied; redistribution review required",
    }, "institutions": rows}


if __name__ == "__main__":
    data = build(Path(sys.argv[1]))
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(json.dumps({**data["provenance"], "output_rows": len(data["institutions"])}))
