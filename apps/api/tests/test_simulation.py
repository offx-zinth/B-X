import sys; sys.path.insert(0, "apps/api")
from app.services import simulation as sim
from app.services import compiler as comp

def test_chain_propagation():
    nodes = [
        {"id":"s1","type":"Supplier","name":"ABC","properties":{"capacity":5000}},
        {"id":"m1","type":"Material","name":"X","properties":{"available":5000,"required":10}},
        {"id":"p1","type":"Production","name":"A","properties":{"capacity":400}},
        {"id":"o1","type":"Order","name":"O","properties":{"material_required":10,"daily_capacity":400,"fulfilled":100,"avg_value":50}},
    ]
    edges = [
        {"source_node":"s1","target_node":"m1","type":"supplies"},
        {"source_node":"m1","target_node":"p1","type":"feeds"},
        {"source_node":"p1","target_node":"o1","type":"fulfills"},
    ]
    formulas = [
        {"target":"Production.capacity","expression":"MIN(Machine.capacity, Material.available / Material.required)"},
        {"target":"Revenue.total","expression":"Order.fulfilled * Order.avg_value"},
    ]
    # need machine cap + material in ctx: add machine node
    nodes.append({"id":"mc","type":"Machine","name":"M","properties":{"capacity":400}})
    r = sim.run(nodes, edges, formulas, [{"target":"Supplier.capacity","value":0}], steps=3)
    assert "changes" in r and r["scenario"] is not None
    c = comp.dependency_closure("s1", edges)
    assert c["affected_count"] == 3 and len(c["direct"]) == 1

def test_tenant_isolation():
    from app.core.store import insert, list_all, clear
    clear()
    a = {"tenant_id":"A","user_id":"u1"}; b = {"tenant_id":"B","user_id":"u2"}
    insert("nodes", a, {"type":"Supplier","name":"A-Sup"})
    insert("nodes", b, {"type":"Supplier","name":"B-Sup"})
    assert len(list_all("nodes", a))==1 and list_all("nodes", a)[0]["name"]=="A-Sup"
    assert len(list_all("nodes", b))==1
