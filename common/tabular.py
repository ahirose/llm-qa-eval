"""UTF-8 CSV input and spreadsheet-compatible result output."""
import csv
import io
import json


def read_records(raw):
    text = raw.decode("utf-8-sig")
    if text.lstrip().startswith("{"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    fields = reader.fieldnames
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("CSV requires unique column names")
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"CSV row {reader.line_num} has an unexpected number of columns")
        if row.get("group") == "":
            row.pop("group")
        rows.append(row)
    return rows


def csv_row(row):
    return {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
            else value for key, value in row.items()}


def write_csv(path, rows, fields):
    with path.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(csv_row(row))
