import csv

CSV_PATH = "production_batch_today.csv"

with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    print("HEADERS:", reader.fieldnames)
    for row in reader:
        print("ROW:", row)
