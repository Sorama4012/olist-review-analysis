"""Загрузка CSV датасета Olist в SQLite (olist.db)."""
import sqlite3
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
DB = Path(__file__).parent / "olist.db"

TABLES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

with sqlite3.connect(DB) as con:
    for table, file in TABLES.items():
        df = pd.read_csv(DATA / file)
        df.to_sql(table, con, if_exists="replace", index=False)
        print(f"{table:22s} {len(df):>8,} строк")
    con.executescript("""
        CREATE INDEX IF NOT EXISTS ix_orders_id   ON orders(order_id);
        CREATE INDEX IF NOT EXISTS ix_items_order ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS ix_items_prod  ON order_items(product_id);
        CREATE INDEX IF NOT EXISTS ix_rev_order   ON order_reviews(order_id);
        CREATE INDEX IF NOT EXISTS ix_prod_id     ON products(product_id);
        CREATE INDEX IF NOT EXISTS ix_cust_id     ON customers(customer_id);
    """)
