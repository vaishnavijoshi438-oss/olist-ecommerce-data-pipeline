-- 1. Monthly revenue and running total
SELECT
    d.year,
    d.month,
    d.month_name,
    ROUND(SUM(f.price + f.freight_value)::numeric, 2) AS monthly_revenue,
    ROUND(SUM(SUM(f.price + f.freight_value)) OVER (
        ORDER BY d.year, d.month
    )::numeric, 2) AS running_revenue
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON f.date_key = d.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;

-- 2. Top product categories by revenue
SELECT
    p.product_category_name,
    ROUND(SUM(f.price + f.freight_value)::numeric, 2) AS revenue
FROM warehouse.fact_sales f
JOIN warehouse.dim_products p ON f.product_id = p.product_id
GROUP BY p.product_category_name
ORDER BY revenue DESC
LIMIT 10;

-- 3. Seller revenue ranking
SELECT
    s.seller_id,
    s.seller_city,
    ROUND(SUM(f.price + f.freight_value)::numeric, 2) AS revenue,
    DENSE_RANK() OVER (ORDER BY SUM(f.price + f.freight_value) DESC) AS seller_rank
FROM warehouse.fact_sales f
JOIN warehouse.dim_sellers s ON f.seller_id = s.seller_id
GROUP BY s.seller_id, s.seller_city
ORDER BY seller_rank
LIMIT 20;

-- 4. Top 3 products by revenue within each category
WITH product_revenue AS (
    SELECT
        p.product_category_name,
        f.product_id,
        SUM(f.price + f.freight_value) AS revenue
    FROM warehouse.fact_sales f
    JOIN warehouse.dim_products p ON f.product_id = p.product_id
    GROUP BY p.product_category_name, f.product_id
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY product_category_name
            ORDER BY revenue DESC
        ) AS category_rank
    FROM product_revenue
)
SELECT product_category_name, product_id, ROUND(revenue::numeric, 2) AS revenue, category_rank
FROM ranked
WHERE category_rank <= 3
ORDER BY product_category_name, category_rank;

-- 5. Customer lifetime value proxy and purchase ranking
SELECT
    f.customer_id,
    COUNT(DISTINCT f.order_id) AS orders_count,
    ROUND(SUM(f.price + f.freight_value)::numeric, 2) AS lifetime_revenue,
    DENSE_RANK() OVER (ORDER BY SUM(f.price + f.freight_value) DESC) AS customer_value_rank
FROM warehouse.fact_sales f
GROUP BY f.customer_id
ORDER BY customer_value_rank
LIMIT 20;
