import sys; sys.path.insert(0, "apps/api")
from app.services import formula_engine as bfl

def test_basic():
    assert bfl.evaluate("1 + 2*3", {}) == 7
    assert bfl.evaluate("MIN(5, 10/2)", {}) == 5
    assert bfl.evaluate("MAX(0, 3-5)", {}) == 0
    assert bfl.evaluate("IF(1, 10, 20)", {}) == 10
    assert bfl.evaluate("ROUND(3.14159, 2)", {}) == 3.14
    assert bfl.evaluate("RATE(50, 200)", {}) == 0.25
    assert bfl.evaluate("DELTA(10, 4)", {}) == 6

def test_refs():
    ctx = {"Inventory.available": 5000, "Order.material_required": 10, "Production.daily_capacity": 400}
    v = bfl.evaluate("MIN(Inventory.available / Order.material_required, Production.daily_capacity)", ctx)
    assert v == 400
    assert set(bfl.dependencies_of("MIN(Inventory.available / Order.material_required, Production.daily_capacity)")) == {"Inventory.available","Order.material_required","Production.daily_capacity"}

def test_reject_code():
    try:
        bfl.evaluate("__import__('os').system('x')", {}); assert False
    except ValueError: pass
    try:
        bfl.evaluate("EVAL(1)", {}); assert False
    except ValueError: pass
