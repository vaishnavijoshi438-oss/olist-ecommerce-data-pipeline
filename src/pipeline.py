import logging
import os
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.config import get_engine

DATA_DIR = Path(os.getenv("DATA_DIR", "data/raw"))
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(LOG_DIR / "pipeline.log", mode="a", encoding="utf-8")],
)
log = logging.getLogger("olist_pipeline")

FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
}

def wait_for_database(engine):
    for attempt in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            log.info("Waiting for PostgreSQL (%s/30): %s", attempt + 1, exc)
            time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready within 60 seconds.")

def load_raw(engine):
    counts = {}
    for table, filename in FILES.items():
        path = DATA_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Missing {path}. Download the five Olist CSV files and place them in data/raw/."
            )
        df = pd.read_csv(path)
        df.to_sql(table, engine, schema="raw", if_exists="replace", index=False, chunksize=5000, method="multi")
        counts[table] = len(df)
        log.info("RAW LOAD PASS | table=%s | rows=%s", table, len(df))
    return counts

def read_raw(engine, table):
    return pd.read_sql_table(table, engine, schema="raw")

def clean_and_build(engine, source_counts):
    orders = read_raw(engine, "orders")
    items = read_raw(engine, "order_items")
    customers = read_raw(engine, "customers")
    products = read_raw(engine, "products")
    sellers = read_raw(engine, "sellers")

    # Standardize timestamps and numeric fields.
    orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
    items["price"] = pd.to_numeric(items["price"], errors="coerce")
    items["freight_value"] = pd.to_numeric(items["freight_value"], errors="coerce")

    # Required keys must exist; optional descriptive fields can remain null.
    required = {
        "orders.order_id": orders["order_id"],
        "customers.customer_id": customers["customer_id"],
        "products.product_id": products["product_id"],
        "sellers.seller_id": sellers["seller_id"],
        "order_items.order_id": items["order_id"],
        "order_items.order_item_id": items["order_item_id"],
        "order_items.product_id": items["product_id"],
        "order_items.seller_id": items["seller_id"],
    }
    for label, series in required.items():
        if series.isna().any():
            raise ValueError(f"DATA QUALITY FAIL | {label} contains null values.")

    # Remove exact duplicate dimension rows; duplicate business keys are rejected below.
    customers = customers.drop_duplicates()
    products = products.drop_duplicates()
    sellers = sellers.drop_duplicates()
    orders = orders.drop_duplicates()
    items = items.drop_duplicates()

    if items.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("DATA QUALITY FAIL | duplicate (order_id, order_item_id) order items.")
    if (items["price"].dropna() < 0).any():
        raise ValueError("DATA QUALITY FAIL | negative product price found.")
    if (items["freight_value"].dropna() < 0).any():
        raise ValueError("DATA QUALITY FAIL | negative freight value found.")
    if orders["order_purchase_timestamp"].isna().any():
        raise ValueError("DATA QUALITY FAIL | invalid or missing order purchase timestamp.")

    for table, df, key in [
        ("orders", orders, "order_id"),
        ("customers", customers, "customer_id"),
        ("products", products, "product_id"),
        ("sellers", sellers, "seller_id"),
    ]:
        if df[key].duplicated().any():
            raise ValueError(f"DATA QUALITY FAIL | duplicate primary key in {table}.{key}.")

    # Replace missing category labels with an explicit unknown value.
    if "product_category_name" in products.columns:
        products["product_category_name"] = products["product_category_name"].fillna("unknown")

    # Build dimensions and fact rows. Keep only order items with matching parent records.
    customer_dim = customers[["customer_id", "customer_unique_id", "customer_zip_code_prefix",
                              "customer_city", "customer_state"]].copy()
    product_dim = products[["product_id", "product_category_name", "product_name_lenght",
                            "product_description_lenght", "product_photos_qty",
                            "product_weight_g", "product_length_cm", "product_height_cm",
                            "product_width_cm"]].copy()
    seller_dim = sellers[["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]].copy()

    dates = orders[["order_purchase_timestamp"]].drop_duplicates().copy()
    dates["date_key"] = dates["order_purchase_timestamp"].dt.strftime("%Y%m%d").astype(int)
    dates["date"] = dates["order_purchase_timestamp"].dt.date
    dates["year"] = dates["order_purchase_timestamp"].dt.year
    dates["quarter"] = dates["order_purchase_timestamp"].dt.quarter
    dates["month"] = dates["order_purchase_timestamp"].dt.month
    dates["month_name"] = dates["order_purchase_timestamp"].dt.month_name()
    dates["day"] = dates["order_purchase_timestamp"].dt.day
    dates["day_of_week"] = dates["order_purchase_timestamp"].dt.day_name()
    date_dim = dates[["date_key", "date", "year", "quarter", "month", "month_name", "day", "day_of_week"]].drop_duplicates("date_key")

    fact = items.merge(
        orders[["order_id", "customer_id", "order_purchase_timestamp"]],
        on="order_id", how="left", validate="many_to_one"
    )
    fact = fact.merge(products[["product_id"]], on="product_id", how="inner", validate="many_to_one")
    fact = fact.merge(sellers[["seller_id"]], on="seller_id", how="inner", validate="many_to_one")
    fact = fact.merge(customers[["customer_id"]], on="customer_id", how="inner", validate="many_to_one")
    fact["date_key"] = pd.to_datetime(fact["order_purchase_timestamp"]).dt.strftime("%Y%m%d").astype(int)
    fact_sales = fact[["order_id", "order_item_id", "product_id", "seller_id", "customer_id",
                       "date_key", "price", "freight_value"]].copy()

    # Validate source row counts against the raw tables before warehouse loading.
    for table, expected in source_counts.items():
        with engine.connect() as conn:
            actual = conn.execute(text(f'SELECT COUNT(*) FROM raw."{table}"')).scalar_one()
        if actual != expected:
            raise ValueError(f"DATA QUALITY FAIL | raw.{table}: CSV rows={expected}, DB rows={actual}.")
        log.info("QUALITY PASS | raw row count matches for %s (%s)", table, actual)

    # Validate referential integrity and fact grain.
    if fact_sales.duplicated(["order_id", "order_item_id"]).any():
        raise ValueError("DATA QUALITY FAIL | duplicate fact_sales order item grain.")
    if fact_sales[["order_id", "product_id", "seller_id", "customer_id", "date_key"]].isna().any().any():
        raise ValueError("DATA QUALITY FAIL | null foreign key in fact_sales.")
    if fact_sales.empty:
        raise ValueError("DATA QUALITY FAIL | fact_sales is empty.")

    # Re-runnable load: replace dimensions/fact tables on every run.
    tables = [
        ("dim_customers", customer_dim),
        ("dim_products", product_dim),
        ("dim_sellers", seller_dim),
        ("dim_date", date_dim),
        ("fact_sales", fact_sales),
    ]
    for table, df in tables:
        df.to_sql(table, engine, schema="warehouse", if_exists="replace", index=False, chunksize=5000, method="multi")
        log.info("WAREHOUSE LOAD PASS | table=%s | rows=%s", table, len(df))

def create_schemas(engine):
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS warehouse"))

def add_constraints(engine):
    # Constraints are added after pandas creates/replaces tables.
    statements = [
        'ALTER TABLE warehouse.dim_customers ADD PRIMARY KEY (customer_id)',
        'ALTER TABLE warehouse.dim_products ADD PRIMARY KEY (product_id)',
        'ALTER TABLE warehouse.dim_sellers ADD PRIMARY KEY (seller_id)',
        'ALTER TABLE warehouse.dim_date ADD PRIMARY KEY (date_key)',
        'ALTER TABLE warehouse.fact_sales ADD PRIMARY KEY (order_id, order_item_id)',
        'ALTER TABLE warehouse.fact_sales ADD CONSTRAINT fk_sales_customer FOREIGN KEY (customer_id) REFERENCES warehouse.dim_customers(customer_id)',
        'ALTER TABLE warehouse.fact_sales ADD CONSTRAINT fk_sales_product FOREIGN KEY (product_id) REFERENCES warehouse.dim_products(product_id)',
        'ALTER TABLE warehouse.fact_sales ADD CONSTRAINT fk_sales_seller FOREIGN KEY (seller_id) REFERENCES warehouse.dim_sellers(seller_id)',
        'ALTER TABLE warehouse.fact_sales ADD CONSTRAINT fk_sales_date FOREIGN KEY (date_key) REFERENCES warehouse.dim_date(date_key)',
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    log.info("QUALITY PASS | warehouse primary and foreign key constraints created")

def main():
    engine = get_engine()
    wait_for_database(engine)
    create_schemas(engine)
    log.info("PIPELINE START")
    counts = load_raw(engine)
    clean_and_build(engine, counts)
    add_constraints(engine)
    log.info("PIPELINE SUCCESS | all stages completed")

if __name__ == "__main__":
    main()
