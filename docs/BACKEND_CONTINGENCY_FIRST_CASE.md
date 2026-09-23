# Connected first contingency case (synthetic demo)

The Backend now activates `policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:4` only for the
exact 16 February 2026 10:00 Singapore-time fixture. The frozen run must match
the versioned catalogue, opening stock, previously recorded delivery and approved
synthetic market quote. Any missing or changed active authority fails closed. Normal
runs continue using the existing `NORMAL_ONLY` procurement policy.

The manager records the physical count, the 6 kg receipt, zero-sales coverage
intervals and the original supplier delay through the ordinary APIs. A zero-sales
interval is retained as inventory evidence but does not request a sales-materiality
assessment. A correction removing real sales still does. The queued assessment
freezes the version-4 case and the original delivery commitment. Procurement uses
the bounded contingency search and a separate validator; Inventory uses that same
frozen multi-day forecast and commitment. Only validated **new** purchase lines go
to the pending plan. The old 4 kg outstanding delivery remains fixed supply, not
a new line or a second charge.

For the approved first case, the pending line is 4 kg of vegetables from `market`,
an `EMERGENCY` order placed at 10:00 for 11:00 arrival, expiring 17 February. The
new-purchase cash cost is S$8 stock + S$3 delivery + S$4 emergency = **S$15**.
Expected waste, stockout and total economic costs are unavailable and stay null.
The manager must approve the exact plan version, then record the external purchase
through `POST /api/v1/deliveries` using the returned plan-line ID. ReStock does not
place or pay for that order.

Run `alembic upgrade head` and `python -m src.seed` before exercising the case;
the seed is insert-only and adds version 4. The acceptance path is
`tests/test_contingency_first_case_backend.py` with a disposable PostgreSQL test
database. The staged version-3 preview/artifact remains non-actionable for diagnosis.
This first case does not certify live model behavior or the other numerical
contingency scenarios (on-time, short, cancelled, infeasible); those still need
connected Agent/API acceptance before issue #11 can close.
