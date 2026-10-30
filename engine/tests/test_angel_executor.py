"""The live order path, against a fake SmartConnect client (no network)."""
from conftest import at
from tradebot.broker.angelone import AngelExecutor, _to_tick
from tradebot.models import OrderStatus, Side


class FakeClient:
    def __init__(self, fill_on_attempt=1):
        self.orders, self.n, self.fill_on = {}, 0, fill_on_attempt

    def placeOrder(self, p):
        self.n += 1
        oid = f"O{self.n}"
        filled = self.n >= self.fill_on
        self.orders[oid] = {"orderid": oid, "status": "complete" if filled else "open",
                            "filledshares": p["quantity"] if filled else "0", "averageprice": p["price"],
                            "params": p}
        return oid

    def orderBook(self):
        return {"data": list(self.orders.values())}

    def cancelOrder(self, oid, variety):
        self.orders[oid]["status"] = "cancelled"

    def ltpData(self, *a):
        return {"data": {"ltp": 100.0}}


class FakeSession:
    def __init__(self, client):
        self.client = client
        self.instruments = type("I", (), {"get": lambda self, s: {"token": "1", "tradingsymbol": s + "-EQ", "tick": 0.05}})()

    def ensure(self):
        return self.client


def test_marketable_limit_order_fills(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c = FakeClient()
    ex = AngelExecutor(FakeSession(c), max_orders_per_second=1000)
    f = ex.place("SBIN", Side.BUY, 3, 100.0, at(10, 0))
    assert f.status is OrderStatus.FILLED and f.qty == 3
    p = c.orders["O1"]["params"]
    assert p["ordertype"] == "LIMIT" and p["producttype"] == "INTRADAY" and p["ordertag"] == "tradebot"
    assert float(p["price"]) >= 100.15     # buffer above the last price for a buy


def test_unfilled_order_is_cancelled_and_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(AngelExecutor, "WAIT_SECONDS", 0.01)
    c = FakeClient(fill_on_attempt=2)
    ex = AngelExecutor(FakeSession(c), max_orders_per_second=1000)
    f = ex.place("SBIN", Side.SELL, 2, 100.0, at(10, 0))
    assert c.orders["O1"]["status"] == "cancelled"
    assert f.qty == 2 and f.status is OrderStatus.FILLED


def test_tick_rounding():
    assert _to_tick(100.123, 0.05, up=True) == 100.15
    assert _to_tick(100.123, 0.05, up=False) == 100.10
