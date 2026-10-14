# BFL — Business Formula Language

Deterministic expression language for the operational graph. **No arbitrary
Python/JavaScript is ever executed.** User formulas are parsed by a custom
recursive-descent parser over a whitelisted function set.

## Grammar

```text
expr        := comparison
comparison  := add (('>'|'<'|'>='|'<='|'='|'=='|'!=') add)?
add         := mul (('+'|'-') mul)*
mul         := unary (('*'|'/') unary)*
unary       := ('-'|'+') unary | atom
atom        := NUMBER | ref | FN '(' args ')' | '(' expr ')'
ref         := ['prev.'] TYPE '.' PROPERTY
args        := expr (',' expr)*
```

## References

| Form | Meaning |
| --- | --- |
| `Inventory.available` | Live value of that property in the current state |
| `prev.Inventory.available` | Value at the end of the **previous** simulated day (stocks only) |

A reference is always `Type.property`. Bare identifiers are rejected. Missing
references resolve to `0.0` and emit an explicit warning — they are never
silently invented.

## Functions

`SUM AVG MIN MAX IF ABS ROUND COUNT RATE DELTA CLAMP`

```
CLAMP(x, lo, hi)   # bound x into [lo, hi]; swaps bounds if reversed
RATE(a, b)         # a / b, 0 when b == 0
DELTA(a, b)        # a - b
```

## Evaluation contract

`evaluate_detailed()` returns `{value, dependencies, trace, errors, warnings, error}`.
Syntax errors, unknown functions and disallowed characters produce an explicit
`error`; they never execute anything and never raise into a request handler.

## Solver semantics

Formulas are split into two layers by `simulation._order_and_split`:

- **Flow** — no self-reference. Topologically ordered (Kahn) and evaluated once
  per day, so results are order-independent and deterministic.
- **Stock** — self-referential via `prev.`, e.g. inventory that depletes daily.
  Reads the previous day's close, so one day of change is applied exactly once.
  This avoids the oscillation that a naive fixpoint loop produces.

## Examples

```text
Production.capacity = MIN(Supplier.capacity, Machine.capacity, Material.available / Material.required)
Order.fulfillable    = MIN(Production.capacity, Demand.quantity)
Order.backlog        = MAX(0, Demand.quantity - Order.fulfillable)
Revenue.total        = Order.fulfillable * Order.avg_value
Inventory.available  = MAX(0, prev.Inventory.available - Order.fulfillable + Order.backlog)
Inventory.days_of_cover = RATE(Inventory.available, Demand.quantity)
```

## Approval lifecycle

`pending → approved | rejected`. Editing an approved formula returns it to
`pending`. AI-generated formulas are always created as `pending` and are never
auto-approved.