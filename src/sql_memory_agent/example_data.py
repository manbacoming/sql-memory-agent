"""Generate tiny SQLite databases for the no-GPU toy experiment."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .models import DatabaseVersion, TaskRecord

DEFAULT_DATA_ROOT = Path("/root/autodl-tmp/sql-memory-agent-data/toy")

def _reset(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    return sqlite3.connect(path)

def create_v1(path: Path) -> None:
    with _reset(path) as con:
        con.executescript("""
        CREATE TABLE cities (city_id INTEGER PRIMARY KEY, city_name TEXT NOT NULL);
        CREATE TABLE stores (store_id INTEGER PRIMARY KEY, city_id INTEGER NOT NULL REFERENCES cities(city_id), store_name TEXT NOT NULL);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(store_id), order_amount INTEGER NOT NULL);
        CREATE TABLE refunds (refund_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(order_id), refund_amount INTEGER NOT NULL);
        INSERT INTO cities VALUES (1, 'Metropolis'), (2, 'Gotham');
        INSERT INTO stores VALUES (1, 1, 'Metro Center'), (2, 2, 'Gotham Market');
        INSERT INTO orders VALUES (1, 1, 300), (2, 2, 250);
        INSERT INTO refunds VALUES (1, 1, 260);
        """)

def create_v2(path: Path) -> None:
    with _reset(path) as con:
        con.executescript("""
        CREATE TABLE cities (city_id INTEGER PRIMARY KEY, city_name TEXT NOT NULL);
        CREATE TABLE stores (store_id INTEGER PRIMARY KEY, city_id INTEGER NOT NULL REFERENCES cities(city_id), store_name TEXT NOT NULL);
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(store_id), order_amount INTEGER NOT NULL);
        CREATE TABLE refund_events (event_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(order_id), returned_amount INTEGER NOT NULL, approved INTEGER NOT NULL);
        INSERT INTO cities VALUES (1, 'Metropolis'), (2, 'Gotham');
        INSERT INTO stores VALUES (1, 1, 'Metro Center'), (2, 2, 'Gotham Market');
        INSERT INTO orders VALUES (1, 1, 300), (2, 2, 250);
        INSERT INTO refund_events VALUES (1, 1, 260, 1);
        """)

def ensure_toy_databases(data_root: Path = DEFAULT_DATA_ROOT) -> dict[str, DatabaseVersion]:
    data_root.mkdir(parents=True, exist_ok=True)
    v1_path = data_root / "retail_v1.sqlite"
    v2_path = data_root / "retail_v2.sqlite"
    create_v1(v1_path)
    create_v2(v2_path)
    return {
        "retail_v1": DatabaseVersion("retail_v1", str(v1_path), "orders/stores/cities plus refunds.refund_amount", 1),
        "retail_v2": DatabaseVersion("retail_v2", str(v2_path), "orders/stores/cities plus refund_events.returned_amount", 2),
    }

def toy_tasks() -> list[TaskRecord]:
    v1_gold = """
    SELECT c.city_name FROM cities c
    JOIN stores s ON s.city_id = c.city_id
    JOIN orders o ON o.store_id = s.store_id
    LEFT JOIN refunds r ON r.order_id = o.order_id
    GROUP BY c.city_name
    ORDER BY SUM(o.order_amount - COALESCE(r.refund_amount, 0)) DESC
    LIMIT 1
    """
    v2_gold = """
    SELECT c.city_name FROM cities c
    JOIN stores s ON s.city_id = c.city_id
    JOIN orders o ON o.store_id = s.store_id
    LEFT JOIN refund_events r ON r.order_id = o.order_id AND r.approved = 1
    GROUP BY c.city_name
    ORDER BY SUM(o.order_amount - COALESCE(r.returned_amount, 0)) DESC
    LIMIT 1
    """
    return [
        TaskRecord("task_v1_learn_refund_rule", "retail_v1", "Which city has the highest net sales after refunds?", v1_gold, [("Gotham",)]),
        TaskRecord("task_v1_reuse_refund_rule", "retail_v1", "For the same database version, which city wins after deducting refunds?", v1_gold, [("Gotham",)]),
        TaskRecord("task_v2_refund_schema_changed", "retail_v2", "After the schema update, which city wins after approved returned amounts?", v2_gold, [("Gotham",)]),
    ]
