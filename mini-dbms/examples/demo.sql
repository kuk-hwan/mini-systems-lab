-- Run this file with mini_dbms.cli, then inspect the .jsonl table file.
INSERT INTO products (name, price) VALUES ('우유', 3000);
INSERT INTO products (name, price) VALUES ('빵', 2500);
SELECT * FROM products WHERE id = 2;
SELECT name, price FROM products WHERE name = '빵';
