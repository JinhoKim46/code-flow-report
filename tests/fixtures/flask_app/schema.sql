-- invented schema
CREATE TABLE IF NOT EXISTS orders (id serial PRIMARY KEY, customer_id int, total int);
CREATE TABLE customers (id serial PRIMARY KEY, name text);
CREATE OR REPLACE VIEW order_totals AS SELECT customer_id, sum(total) FROM orders GROUP BY 1;
