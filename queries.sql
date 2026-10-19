-- =====================================================================
-- Olist: анализ отзывов и доставки. СУБД: SQLite (olist.db, см. load_data.py)
--
-- Общие договорённости:
--   * Выручка = сумма price из order_items (без стоимости доставки)
--     по доставленным заказам (order_status = 'delivered').
--   * Месяц заказа = месяц order_purchase_timestamp.
--   * Опоздание = дата доставки клиенту > обещанной даты
--     (сравниваем по дням: обещанная дата хранится как 00:00:00).
--   * У части заказов несколько отзывов, поэтому оценку сначала
--     усредняем до уровня заказа, иначе такие заказы весят больше.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1. Выручка и количество заказов по месяцам
-- ---------------------------------------------------------------------
SELECT
    strftime('%Y-%m', o.order_purchase_timestamp) AS month,
    COUNT(DISTINCT o.order_id)                    AS orders,
    ROUND(SUM(oi.price), 2)                       AS revenue,
    ROUND(SUM(oi.price) / COUNT(DISTINCT o.order_id), 2) AS avg_check
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status = 'delivered'
GROUP BY month
ORDER BY month;


-- ---------------------------------------------------------------------
-- 2. Топ-10 категорий товаров по выручке
-- ---------------------------------------------------------------------
SELECT
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
    COUNT(DISTINCT o.order_id) AS orders,
    ROUND(SUM(oi.price), 2)    AS revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p     ON p.product_id = oi.product_id
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered'
GROUP BY category
ORDER BY revenue DESC
LIMIT 10;


-- ---------------------------------------------------------------------
-- 3. Средняя оценка отзыва по категориям (JOIN заказов, товаров и отзывов)
--    Заказ с товарами из двух категорий учитывается в обеих.
--    Отсекаем категории с < 100 оценёнными заказами.
-- ---------------------------------------------------------------------
WITH order_review AS (
    SELECT order_id, AVG(review_score) AS score
    FROM order_reviews
    GROUP BY order_id
),
order_category AS (
    SELECT DISTINCT
        oi.order_id,
        COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category
    FROM order_items oi
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
)
SELECT
    oc.category,
    COUNT(*)               AS reviewed_orders,
    ROUND(AVG(r.score), 2) AS avg_score
FROM orders o
JOIN order_category oc ON oc.order_id = o.order_id
JOIN order_review r    ON r.order_id  = o.order_id
GROUP BY oc.category
HAVING COUNT(*) >= 100
ORDER BY avg_score ASC;


-- ---------------------------------------------------------------------
-- 4. Доля заказов, доставленных позже обещанной даты, по штатам
-- ---------------------------------------------------------------------
SELECT
    c.customer_state AS state,
    COUNT(*)         AS delivered_orders,
    SUM(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)) AS late_orders,
    ROUND(100.0 * AVG(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)), 1) AS late_pct
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY c.customer_state
ORDER BY late_pct DESC;


-- ---------------------------------------------------------------------
-- 5. ГЛАВНЫЙ ЗАПРОС: средняя оценка для заказов, доставленных вовремя
--    и с опозданием (+ доля плохих оценок 1–2 в каждой группе)
-- ---------------------------------------------------------------------
WITH order_review AS (
    SELECT order_id, AVG(review_score) AS score
    FROM order_reviews
    GROUP BY order_id
)
SELECT
    CASE WHEN date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)
         THEN 'late' ELSE 'on_time' END        AS delivery,
    COUNT(*)                                   AS orders,
    ROUND(AVG(r.score), 2)                     AS avg_score,
    ROUND(100.0 * AVG(r.score <= 2), 1)        AS bad_review_pct
FROM orders o
JOIN order_review r ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY delivery
ORDER BY delivery DESC;


-- ---------------------------------------------------------------------
-- 6. Продавцы с наибольшей долей оценок 1–2
--    (минимум 30 оценённых заказов, чтобы не ловить шум)
-- ---------------------------------------------------------------------
WITH order_review AS (
    SELECT order_id, AVG(review_score) AS score
    FROM order_reviews
    GROUP BY order_id
),
seller_orders AS (
    SELECT DISTINCT oi.seller_id, oi.order_id
    FROM order_items oi
)
SELECT
    so.seller_id,
    s.seller_state,
    COUNT(*)                                AS reviewed_orders,
    ROUND(AVG(r.score), 2)                  AS avg_score,
    ROUND(100.0 * AVG(r.score <= 2), 1)     AS bad_review_pct,
    ROUND(100.0 * AVG(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)), 1) AS late_pct
FROM seller_orders so
JOIN order_review r ON r.order_id  = so.order_id
JOIN orders o       ON o.order_id  = so.order_id
JOIN sellers s      ON s.seller_id = so.seller_id
GROUP BY so.seller_id, s.seller_state
HAVING COUNT(*) >= 30
ORDER BY bad_review_pct DESC
LIMIT 20;


-- ---------------------------------------------------------------------
-- 7*. Ранжирование категорий по выручке внутри каждого месяца (RANK())
--     Показываем топ-3 категории каждого месяца.
-- ---------------------------------------------------------------------
WITH monthly AS (
    SELECT
        strftime('%Y-%m', o.order_purchase_timestamp) AS month,
        COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
        ROUND(SUM(oi.price), 2) AS revenue
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p     ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
    WHERE o.order_status = 'delivered'
    GROUP BY month, category
),
ranked AS (
    SELECT
        month,
        category,
        revenue,
        RANK() OVER (PARTITION BY month ORDER BY revenue DESC) AS rank_in_month
    FROM monthly
)
SELECT month, rank_in_month, category, revenue
FROM ranked
WHERE rank_in_month <= 3
ORDER BY month, rank_in_month;


-- =====================================================================
-- Выгрузки для Excel-отчёта (report.xlsm, см. build_report.py)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 8. @export:facts — факт-таблица для сводных: доставленный заказ × категория.
--    Заказ с товарами из N категорий разбит на N строк с весом 1/N,
--    поэтому сумма orders_w = число заказов, а доли считаются как
--    late_w / orders_w и score_w / reviewed_w (вычисляемые поля в сводной).
-- ---------------------------------------------------------------------
WITH order_review AS (
    SELECT order_id, AVG(review_score) AS score
    FROM order_reviews
    GROUP BY order_id
),
order_category AS (
    SELECT
        oi.order_id,
        COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
        SUM(oi.price) AS revenue
    FROM order_items oi
    JOIN products p ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
    GROUP BY oi.order_id, category
),
weighted AS (
    SELECT *, 1.0 / COUNT(*) OVER (PARTITION BY order_id) AS w
    FROM order_category
)
SELECT
    strftime('%Y-%m', o.order_purchase_timestamp) AS month,
    c.customer_state                              AS state,
    wc.category,
    CASE WHEN date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)
         THEN 'С опозданием' ELSE 'Вовремя' END   AS delivery,
    ROUND(wc.revenue, 2)                          AS revenue,
    wc.w                                          AS orders_w,
    wc.w * (date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)) AS late_w,
    CASE WHEN r.score IS NOT NULL THEN wc.w ELSE 0 END AS reviewed_w,
    COALESCE(wc.w * r.score, 0)                   AS score_w,
    COALESCE(wc.w * (r.score <= 2), 0)            AS bad_w
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
JOIN weighted wc ON wc.order_id   = o.order_id
LEFT JOIN order_review r ON r.order_id = o.order_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  -- 2016 год — единичные тестовые заказы (1–265 в месяц), они искажают помесячные доли
  AND o.order_purchase_timestamp >= '2017-01-01';


-- ---------------------------------------------------------------------
-- 9. @export:sellers — карточки продавцов для VBA-письма
--    (все продавцы с >= 30 оценёнными доставленными заказами).
-- ---------------------------------------------------------------------
WITH order_review AS (
    SELECT order_id, AVG(review_score) AS score
    FROM order_reviews
    GROUP BY order_id
),
seller_orders AS (
    SELECT oi.seller_id, oi.order_id, SUM(oi.price) AS revenue
    FROM order_items oi
    GROUP BY oi.seller_id, oi.order_id
)
SELECT
    so.seller_id,
    s.seller_city,
    s.seller_state,
    COUNT(*)                         AS reviewed_orders,
    ROUND(SUM(so.revenue), 2)        AS revenue,
    ROUND(AVG(r.score), 2)           AS avg_score,
    AVG(r.score <= 2)                AS bad_share,
    AVG(date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)) AS late_share,
    ROUND(AVG(CASE WHEN date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date)
                   THEN julianday(date(o.order_delivered_customer_date)) - julianday(date(o.order_estimated_delivery_date))
              END), 1)               AS avg_delay_days
FROM seller_orders so
JOIN order_review r ON r.order_id  = so.order_id
JOIN orders o       ON o.order_id  = so.order_id
JOIN sellers s      ON s.seller_id = so.seller_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
GROUP BY so.seller_id, s.seller_city, s.seller_state
HAVING COUNT(*) >= 30
ORDER BY bad_share DESC;
