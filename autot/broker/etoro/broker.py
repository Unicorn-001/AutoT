"""Documented demo routes only. Transport acceptance never implies execution."""
from .client import BrokerError
from autot.utils.financial_validation import decimal_value as D

ORDERS = '/api/v2/trading/execution/demo/orders'


class EtoroDemoBroker:
    def __init__(self, client):
        self.client = client

    def account(self):
        return self.client.request('GET', '/api/v1/trading/info/demo/pnl')['clientPortfolio']

    def positions(self):
        return self.account().get('positions', [])

    def close_position(self, position_id, instrument_id, *, request_id, confirmed):
        if confirmed is not True or self.client.config.mode != 'demo':
            raise BrokerError('Explicit manual DEMO confirmation is required.')
        if any(type(value) is not int or value <= 0 for value in (position_id, instrument_id)):
            raise BrokerError('Invalid demo position or instrument ID.')
        return self.client.request('POST',
            f'/api/v1/trading/execution/demo/market-close-orders/positions/{position_id}',
            payload={'InstrumentID': instrument_id}, request_id=request_id)

    def lookup_close(self, order_id):
        if type(order_id) is not int or order_id <= 0:
            raise BrokerError('Invalid close order ID.')
        return self.client.request('GET', f'/api/v1/trading/info/demo/close-orders/{order_id}')

    def lookup(self, *, order_id=None, reference_id=None):
        if (order_id is None) == (reference_id is None):
            raise BrokerError('Exactly one order/reference ID is required.')
        return self.client.request('GET', '/api/v2/trading/info/demo/orders:lookup',
            params={'orderId': order_id} if order_id is not None else {'referenceId': reference_id})

    def require_underlying(self, instrument_id):
        data = self.client.request('POST', '/api/v2/trading/info/demo/eligibility',
                                   payload={'instrumentIds': [instrument_id], 'currency': 'USD'})
        matches = [e for e in data.get('eligibilities', []) if e.get('instrumentId') == instrument_id]
        if len(matches) != 1 or matches[0].get('allowOpenPosition') is not True or not any(
                c.get('settlementType', '').lower() == 'real' and c.get('direction', '').upper() == 'LONG'
                and 1 in c.get('leverageValues', []) and c.get('isPotential') is False
                for c in matches[0].get('leverageConfigs', [])):
            raise BrokerError('Underlying US equity X1 eligibility could not be verified; CFDs disabled.')

    @staticmethod
    def prepare_order(*, instrument_id, quantity, stop, target):
        """Map the supported normalized intent to the broker wire contract."""
        if type(quantity) is not int or quantity <= 0 or type(instrument_id) is not int or instrument_id <= 0:
            raise BrokerError('Positive whole units and instrument ID are required.')
        return dict(action='open', transaction='buy', instrumentId=instrument_id,
                    orderType='mkt', units=quantity, orderCurrency='usd', leverage=1,
                    settlementType='real', stopLossType='fixed',
                    stopLossRate=float(D(stop, positive=True)), takeProfitRate=float(D(target, positive=True)))

    def submit(self, payload, *, request_id, confirmed):
        if confirmed is not True or self.client.config.mode != 'demo':
            raise BrokerError('Explicit manual DEMO confirmation is required.')
        if (payload.get('action'), payload.get('transaction'), payload.get('leverage'),
            payload.get('settlementType'), payload.get('orderType')) != ('open', 'buy', 1, 'real', 'mkt'):
            raise BrokerError('Only underlying BUY MARKET X1 is enabled in demo V1.')
        expected = {'action', 'transaction', 'instrumentId', 'orderType', 'units', 'orderCurrency',
                    'leverage', 'settlementType', 'stopLossType', 'stopLossRate', 'takeProfitRate'}
        if set(payload) != expected or type(payload['units']) is not int or payload['units'] < 1:
            raise BrokerError('Invalid V1 order fields or quantity.')
        return self.client.request('POST', ORDERS, payload=payload, request_id=request_id)
