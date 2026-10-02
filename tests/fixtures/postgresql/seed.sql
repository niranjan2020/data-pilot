INSERT INTO customers (customer_id, customer_name, country, segment, created_at) VALUES
(1, 'Acme Corp', 'India', 'Enterprise', '2024-01-15'),
(2, 'Contoso Ltd', 'United States', 'Enterprise', '2024-03-10'),
(3, 'Northwind Retail', 'India', 'Retail', '2025-02-05'),
(4, 'Globex', 'Germany', 'SMB', '2025-05-20'),
(5, 'Initech', 'Singapore', 'Enterprise', '2026-01-12');

INSERT INTO products (product_id, product_name, category, unit_price) VALUES
(1, 'Analytics Pro', 'Software', 1000.00),
(2, 'Data Connect', 'Software', 500.00),
(3, 'Edge Gateway', 'Hardware', 2000.00),
(4, 'Support Plus', 'Services', 250.00);

INSERT INTO orders (order_id, customer_id, product_id, quantity, order_date, amount) VALUES
(101, 1, 1, 2, '2026-01-10', 2000.00),
(102, 1, 2, 4, '2026-02-12', 2000.00),
(103, 2, 3, 1, '2026-02-20', 2000.00),
(104, 3, 4, 4, '2026-03-05', 1000.00),
(105, 2, 1, 3, '2026-04-15', 3000.00),
(106, 4, 2, 2, '2026-05-01', 1000.00),
(107, 1, 3, 1, '2026-06-18', 2000.00),
(108, 5, 1, 5, '2026-07-22', 5000.00);

SELECT setval(pg_get_serial_sequence('customers', 'customer_id'), (SELECT MAX(customer_id) FROM customers));
SELECT setval(pg_get_serial_sequence('products', 'product_id'), (SELECT MAX(product_id) FROM products));
SELECT setval(pg_get_serial_sequence('orders', 'order_id'), (SELECT MAX(order_id) FROM orders));
