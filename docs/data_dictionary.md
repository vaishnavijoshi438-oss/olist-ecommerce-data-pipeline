# Data dictionary (warehouse)

## warehouse.fact_sales
| Column | Meaning |
|---|---|
| order_id | Olist order identifier |
| order_item_id | Item sequence within an order; part of fact primary key |
| product_id | Product dimension key |
| seller_id | Seller dimension key |
| customer_id | Customer dimension key |
| date_key | Purchase date in YYYYMMDD format |
| price | Item price from source |
| freight_value | Shipping charge from source |

## Dimensions
- `dim_customers`: customer identifier, unique customer identifier, ZIP prefix, city, state.
- `dim_products`: product identifier, category, and available product attributes.
- `dim_sellers`: seller identifier, ZIP prefix, city, state.
- `dim_date`: date key, date, year, quarter, month, month name, day, weekday.

The source dataset contains additional columns in raw tables. This dictionary documents the mini warehouse model only.
