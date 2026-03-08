from __future__ import annotations

import os
import time
import hmac
import hashlib
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Optional, Dict, Any

import requests

from quant.config.presets import PortfolioBTConfig
from quant.config.settings import load_settings
from quant.core.events import OrderEvent, FillEvent
from quant.execution.broker_base import Broker
from quant.core.types import Side
from quant.util.logging import get_logger, jlog


@dataclass(frozen=True)
class SymbolRules:
    step_size: Decimal
    min_qty: Decimal
    max_qty: Optional[Decimal]
    min_notional: Optional[Decimal]  # USDT 기준 최소 주문 금액(있으면)

    def normalize_qty(self, qty: float) -> Decimal:
        q = Decimal(str(qty))
        if q <= 0:
            return Decimal("0")

        step = self.step_size
        n = (q / step).to_integral_value(rounding=ROUND_DOWN)
        qn = (n * step)

        # step 형태에 맞춰 소수점 정리
        try:
            qn = qn.quantize(step, rounding=ROUND_DOWN)
        except Exception:
            qn = qn.quantize(Decimal("1"), rounding=ROUND_DOWN)
        return qn


class BinanceFuturesREST:
    def __init__(self, api_key: str, api_secret: str, base_url: str, timeout: int = 10):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.sess = requests.Session()
        self.sess.headers.update({"X-MBX-APIKEY": self.api_key})

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        qs = urllib.parse.urlencode(params, doseq=True)
        sig = hmac.new(self.api_secret.encode("utf-8"), qs.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = sig
        return params

    def _request(self, method: str, path: str, params: Dict[str, Any], signed: bool = False) -> Any:
        url = self.base_url + path
        p = self._sign(params) if signed else params

        r = self.sess.request(method, url, params=p, timeout=self.timeout)
        if r.status_code >= 400:
            try:
                j = r.json()
                raise RuntimeError(f"Binance API error {r.status_code}: {j}")
            except Exception:
                raise RuntimeError(f"Binance API error {r.status_code}: {r.text}")
        return r.json()

    def exchange_info(self) -> Dict[str, Any]:
        return self._request("GET", "/fapi/v1/exchangeInfo", {}, signed=False)

    def position_risk(self) -> Any:
        return self._request("GET", "/fapi/v2/positionRisk", {}, signed=True)

    def account(self) -> Any:
        return self._request("GET", "/fapi/v2/account", {}, signed=True)

    def place_market_order(
        self,
        symbol: str,
        side: str,  # "BUY"/"SELL"
        quantity_str: str,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity_str,
            "reduceOnly": "true" if reduce_only else "false",
            "newOrderRespType": "RESULT",
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        return self._request("POST", "/fapi/v1/order", params, signed=True)


class BinanceBroker(Broker):
    """
    ✅ 목표: 주문 실패 원인 100% 로그화
    - minQty/stepSize/minNotional 검증 + 정규화 과정 기록
    - API 에러/응답값(executedQty=0 등) 모두 JSON 로그
    """

    def __init__(self, cfg: PortfolioBTConfig):
        self.cfg = cfg

        settings = load_settings()
        api_key = (getattr(cfg, "binance_api_key", "") or settings.binance_api_key or os.getenv("BINANCE_API_KEY", "")).strip()
        api_secret = (getattr(cfg, "binance_api_secret", "") or settings.binance_api_secret or os.getenv("BINANCE_API_SECRET", "")).strip()
        if not api_key or not api_secret:
            raise ValueError("Binance API key/secret not found. (.env 또는 cfg 주입 필요)")

        base_url = (
            getattr(cfg, "binance_fapi_base_url", "").strip()
            or os.getenv("BINANCE_FAPI_BASE_URL", "").strip()
            or "https://fapi.binance.com"
        )

        self.client = BinanceFuturesREST(api_key, api_secret, base_url=base_url, timeout=10)

        self._rules: Dict[str, SymbolRules] = {}
        self._rules_loaded_at: float = 0.0
        self._rules_ttl_sec: int = int(os.getenv("BINANCE_RULES_TTL_SEC", "3600"))

        # 자동 보정(기본 OFF: 안전)
        self._bump_to_min_qty: bool = os.getenv("BINANCE_BROKER_BUMP_MIN_QTY", "0") == "1"
        self._bump_to_min_notional: bool = os.getenv("BINANCE_BROKER_BUMP_MIN_NOTIONAL", "0") == "1"

        # logger
        log_dir = settings.log_dir
        self.log = get_logger("quant.binance", log_dir=log_dir, file_stem="binance_orders")

        jlog(self.log, "binance_broker_init", {"base_url": base_url, "rules_ttl_sec": self._rules_ttl_sec})

    def _ensure_rules(self) -> None:
        now = time.time()
        if self._rules and (now - self._rules_loaded_at) < self._rules_ttl_sec:
            return

        info = self.client.exchange_info()
        rules: Dict[str, SymbolRules] = {}

        for sym in info.get("symbols", []):
            symbol = sym.get("symbol")
            if not symbol:
                continue

            step: Optional[Decimal] = None
            minq: Optional[Decimal] = None
            maxq: Optional[Decimal] = None
            min_notional: Optional[Decimal] = None

            for f in sym.get("filters", []):
                ftype = f.get("filterType")

                # qty rules
                if ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                    if f.get("stepSize") is not None:
                        step = Decimal(str(f["stepSize"]))
                    if f.get("minQty") is not None:
                        minq = Decimal(str(f["minQty"]))
                    if f.get("maxQty") is not None:
                        try:
                            maxq = Decimal(str(f["maxQty"]))
                        except Exception:
                            maxq = None

                # notional rules (futures: MIN_NOTIONAL이 있는 심볼이 있음)
                if ftype == "MIN_NOTIONAL":
                    v = f.get("notional")
                    if v is not None:
                        try:
                            min_notional = Decimal(str(v))
                        except Exception:
                            min_notional = None

            if step is None or minq is None:
                continue

            rules[symbol] = SymbolRules(step_size=step, min_qty=minq, max_qty=maxq, min_notional=min_notional)

        self._rules = rules
        self._rules_loaded_at = now
        jlog(self.log, "exchange_rules_loaded", {"symbols": len(rules)})

    def _format_decimal(self, d: Decimal) -> str:
        return format(d, "f").rstrip("0").rstrip(".")

    def _normalize_and_validate_qty(self, symbol: str, raw_qty: float, ref_price: float, reduce_only: bool) -> str:
        self._ensure_rules()
        r = self._rules.get(symbol)
        if r is None:
            # 규칙을 못 얻었으면 최소한의 문자열만 (운영에서는 비추지만 fail-safe)
            return f"{raw_qty:.10f}".rstrip("0").rstrip(".")

        qn = r.normalize_qty(raw_qty)

        # normalize 결과가 0
        if qn <= 0:
            raise ValueError(f"normalized qty <= 0 ({symbol}) raw_qty={raw_qty}")

        # minQty
        if qn < r.min_qty:
            if self._bump_to_min_qty and not reduce_only:
                qn = r.min_qty
            else:
                raise ValueError(
                    f"qty below minQty ({symbol}) raw={raw_qty} normalized={qn} minQty={r.min_qty} step={r.step_size}"
                )

        # maxQty
        if r.max_qty is not None and qn > r.max_qty:
            raise ValueError(f"qty above maxQty ({symbol}) raw={raw_qty} normalized={qn} maxQty={r.max_qty}")

        # minNotional (있으면)
        if r.min_notional is not None:
            notional = qn * Decimal(str(ref_price))
            if notional < r.min_notional:
                if self._bump_to_min_notional and (not reduce_only):
                    # minNotional 만족하도록 qty를 올리는 건 stepSize 맞춰야 하므로 ceil이 필요하지만,
                    # 안전 우선: 기본은 OFF. ON일 때만 간단 보정.
                    # ceil(minNotional/ref_price/step)*step
                    need = (r.min_notional / Decimal(str(ref_price)))
                    step = r.step_size
                    n = (need / step).to_integral_value(rounding=ROUND_DOWN)
                    if (n * step) < need:
                        n = n + 1
                    qn2 = (n * step)
                    try:
                        qn2 = qn2.quantize(step)
                    except Exception:
                        pass
                    qn = qn2
                else:
                    raise ValueError(
                        f"notional below minNotional ({symbol}) "
                        f"raw_qty={raw_qty} normalized={qn} ref_price={ref_price} "
                        f"notional={notional} minNotional={r.min_notional}"
                    )

        return self._format_decimal(qn)

    def get_open_positions(self) -> Dict[str, float]:
        data = self.client.position_risk()
        out: Dict[str, float] = {}
        for row in data:
            sym = row.get("symbol")
            amt = float(row.get("positionAmt") or 0.0)
            if sym and abs(amt) > 0:
                out[sym] = amt
        return out

    def get_usdt_wallet_balance(self) -> float:
        acc = self.client.account()
        for a in acc.get("assets", []):
            if a.get("asset") == "USDT":
                return float(a.get("walletBalance") or 0.0)
        return 0.0

    def execute(self, order: OrderEvent, ts: datetime, ref_price: float) -> Optional[FillEvent]:
        if order is None or float(order.qty) <= 0:
            return None

        side_str = "BUY" if order.side == Side.BUY else "SELL"
        reduce_only = bool(getattr(order, "reduce_only", False))
        client_id = self._make_client_order_id(order, ts)

        # 1) 정규화/검증 + 상세 로그
        try:
            qty_str = self._normalize_and_validate_qty(
                symbol=order.symbol,
                raw_qty=float(order.qty),
                ref_price=float(ref_price),
                reduce_only=reduce_only,
            )

            # 성공 로그(전송 직전)
            self._log_order_attempt(
                status="attempt",
                order=order,
                ts=ts,
                ref_price=ref_price,
                reduce_only=reduce_only,
                client_order_id=client_id,
                qty_str=qty_str,
                error=None,
                resp=None,
            )
        except Exception as e:
            # 정규화/최소주문/최소금액 단계에서 실패해도 100% 로그
            self._log_order_attempt(
                status="reject_precheck",
                order=order,
                ts=ts,
                ref_price=ref_price,
                reduce_only=reduce_only,
                client_order_id=client_id,
                qty_str=None,
                error=repr(e),
                resp=None,
            )
            raise

        # 2) 주문 전송 + 응답/실패 로그
        try:
            resp = self.client.place_market_order(
                symbol=order.symbol,
                side=side_str,
                quantity_str=qty_str,
                reduce_only=reduce_only,
                client_order_id=client_id,
            )
            self._log_order_attempt(
                status="sent",
                order=order,
                ts=ts,
                ref_price=ref_price,
                reduce_only=reduce_only,
                client_order_id=client_id,
                qty_str=qty_str,
                error=None,
                resp=resp,
            )
        except Exception as e:
            self._log_order_attempt(
                status="api_error",
                order=order,
                ts=ts,
                ref_price=ref_price,
                reduce_only=reduce_only,
                client_order_id=client_id,
                qty_str=qty_str,
                error=repr(e),
                resp=None,
            )
            raise

        executed_qty = float(resp.get("executedQty") or 0.0)
        if executed_qty <= 0:
            self._log_order_attempt(
                status="not_filled",
                order=order,
                ts=ts,
                ref_price=ref_price,
                reduce_only=reduce_only,
                client_order_id=client_id,
                qty_str=qty_str,
                error="executedQty=0",
                resp=resp,
            )
            raise RuntimeError(f"Order not filled (executedQty=0). resp={resp}")

        avg_price = resp.get("avgPrice")
        if avg_price is None or avg_price == "" or float(avg_price) == 0.0:
            cum_quote = float(resp.get("cumQuote") or 0.0)
            px = (cum_quote / executed_qty) if (cum_quote > 0 and executed_qty > 0) else float(ref_price)
        else:
            px = float(avg_price)

        notional = abs(px * executed_qty)
        fee = notional * float(self.cfg.fee_rate)

        self._log_order_attempt(
            status="filled",
            order=order,
            ts=ts,
            ref_price=ref_price,
            reduce_only=reduce_only,
            client_order_id=client_id,
            qty_str=qty_str,
            error=None,
            resp={
                "executedQty": executed_qty,
                "avgPrice": px,
                "notional": notional,
                "fee_est": fee,
            },
        )

        return FillEvent(
            symbol=order.symbol,
            ts=ts,
            side=order.side,
            qty=executed_qty,
            price=px,
            fee=fee,
            reason=order.reason,
        )

    def _rules_snapshot(self, symbol: str) -> Dict[str, Any]:
        self._ensure_rules()
        r = self._rules.get(symbol)
        if r is None:
            return {}
        return {
            "stepSize": self._format_decimal(r.step_size),
            "minQty": self._format_decimal(r.min_qty),
            "maxQty": self._format_decimal(r.max_qty) if r.max_qty is not None else None,
            "minNotional": self._format_decimal(r.min_notional) if r.min_notional is not None else None,
        }

    def _log_order_attempt(
        self,
        status: str,
        order: OrderEvent,
        ts: datetime,
        ref_price: float,
        reduce_only: bool,
        client_order_id: str,
        qty_str: Optional[str],
        error: Optional[str],
        resp: Optional[Dict[str, Any]],
    ) -> None:
        payload: Dict[str, Any] = {
            "status": status,
            "symbol": order.symbol,
            "side": "BUY" if order.side == Side.BUY else "SELL",
            "reduceOnly": bool(reduce_only),
            "reason": order.reason,
            "ts": ts.isoformat(),
            "ref_price": float(ref_price),
            "raw_qty": float(order.qty),
            "qty_str": qty_str,
            "clientOrderId": client_order_id,
            "rules": self._rules_snapshot(order.symbol),
        }
        if error is not None:
            payload["error"] = error
        if resp is not None:
            payload["resp"] = resp

        # JSONL + 콘솔 동시에
        level = "error" if status in ("reject_precheck", "api_error", "not_filled") else "info"
        jlog(self.log, "order", payload, level=level)

    @staticmethod
    def _make_client_order_id(order: OrderEvent, ts: datetime) -> str:
        t = int(ts.timestamp())
        s = getattr(order, "symbol", "SYM")
        side = "B" if order.side == Side.BUY else "S"
        q = str(getattr(order, "qty", 0.0))
        qh = hashlib.sha1(q.encode("utf-8")).hexdigest()[:6]
        cid = f"QL_{s}_{side}_{t}_{qh}"
        return cid[:36]
