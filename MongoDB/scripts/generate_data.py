#!/usr/bin/env python3
"""Keeps feeding an Amazon DocumentDB / MongoDB collection with fake "orders".

Usage:
  export DOCDB_URI="mongodb://<user>:<password>@<cluster-endpoint>:27017/?tls=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false"
  export DOCDB_TLS_CA_FILE=./global-bundle.pem      # DocumentDB only
  python generate_data.py                           # continuous, ~1 batch every 5s
  python generate_data.py --backfill 200 --once     # just create 200 documents and exit

Document shape (flat on purpose, so the JDBC driver maps it to a single SQL table "orders"):
  orderId, customer, country, status, paymentMethod, items, amount, createdAt (BSON Date)
"""
import argparse
import os
import random
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from pymongo import ASCENDING, MongoClient

CUSTOMERS = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi", "ivan", "judy"]
COUNTRIES = ["BR", "US", "DE", "PT", "JP", "AU"]
PAYMENTS = ["credit_card", "debit_card", "pix", "paypal", "boleto"]
# Weighted so there is always a mix of statuses
STATUSES = ["CREATED", "PAID", "SHIPPED", "DELIVERED", "CANCELLED", "FAILED"]
WEIGHTS = [30, 30, 15, 10, 8, 7]


def make_order(created_at: datetime) -> dict:
    items = random.randint(1, 6)
    return {
        "orderId": uuid.uuid4().hex[:12],
        "customer": random.choice(CUSTOMERS),
        "country": random.choice(COUNTRIES),
        "status": random.choices(STATUSES, WEIGHTS)[0],
        "paymentMethod": random.choice(PAYMENTS),
        "items": items,
        "amount": round(random.uniform(5, 120) * items, 2),
        "createdAt": created_at,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uri", default=os.getenv("DOCDB_URI"), help="connection URI (or env DOCDB_URI)")
    ap.add_argument("--ca-file", default=os.getenv("DOCDB_TLS_CA_FILE"), help="global-bundle.pem (or env DOCDB_TLS_CA_FILE)")
    ap.add_argument("--db", default=os.getenv("DOCDB_DATABASE", "shop"))
    ap.add_argument("--collection", default=os.getenv("DOCDB_COLLECTION", "orders"))
    ap.add_argument("--interval", type=float, default=5, help="seconds between batches (default 5)")
    ap.add_argument("--min-batch", type=int, default=1)
    ap.add_argument("--max-batch", type=int, default=5)
    ap.add_argument("--backfill", type=int, default=0, help="insert N documents spread over the last 10 minutes first")
    ap.add_argument("--once", action="store_true", help="exit after the backfill / one batch")
    args = ap.parse_args()

    if not args.uri:
        print("Set DOCDB_URI or pass --uri", file=sys.stderr)
        return 2

    kwargs = {"retryWrites": False}  # DocumentDB does not support retryable writes
    if args.ca_file:
        kwargs["tlsCAFile"] = args.ca_file
    client = MongoClient(args.uri, serverSelectionTimeoutMS=10000, **kwargs)
    client.admin.command("ping")
    coll = client[args.db][args.collection]
    coll.create_index([("createdAt", ASCENDING)])
    print(f"Connected. Writing to {args.db}.{args.collection}")

    stop = False

    def handle(_sig, _frm):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)

    if args.backfill:
        now = datetime.now(timezone.utc)
        docs = [make_order(now - timedelta(seconds=random.uniform(0, 600))) for _ in range(args.backfill)]
        coll.insert_many(docs)
        print(f"Backfilled {len(docs)} documents")
        if args.once:
            return 0

    while not stop:
        n = random.randint(args.min_batch, args.max_batch)
        coll.insert_many([make_order(datetime.now(timezone.utc)) for _ in range(n)])
        print(f"{datetime.now().strftime('%H:%M:%S')} inserted {n} orders (total {coll.estimated_document_count()})", flush=True)
        if args.once:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
