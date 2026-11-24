"""Fixed-host transport; never log headers, response bodies or transport errors."""
from dataclasses import dataclass, field
from decimal import Decimal
import json
import math
import os
import time
from uuid import uuid4

import requests


class BrokerError(ValueError):
    def __init__(self, message, *, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


@dataclass(frozen=True)
class Config:
    api_key: str = field(repr=False)
    user_key: str = field(repr=False)
    mode: str = 'demo'
    timeout: float = 10
    retries: int = 2

    def __post_init__(self):
        if self.mode != 'demo':
            raise BrokerError('Only ETORO_TRADING_MODE=demo is supported. Real-money execution is disabled.')
        if not math.isfinite(self.timeout) or not 0 < self.timeout <= 60 or not 0 <= self.retries <= 4:
            raise BrokerError('Invalid eToro timeout/retry settings.')

    @classmethod
    def from_env(cls):
        try:
            return cls(os.getenv('ETORO_API_KEY', ''), os.getenv('ETORO_USER_KEY', ''),
                       os.getenv('ETORO_TRADING_MODE', 'demo'),
                       float(os.getenv('ETORO_TIMEOUT_SECONDS', '10')),
                       int(os.getenv('ETORO_MAX_RETRIES', '2')))
        except (TypeError, ValueError) as error:
            if isinstance(error, BrokerError):
                raise
            raise BrokerError('Invalid eToro timeout/retry settings.') from None

    @property
    def configured(self):
        return bool(self.api_key and self.user_key)


class Client:
    def __init__(self, config=None, *, session=None, sleep=time.sleep):
        self.config = config or Config.from_env()
        self.session = session or requests.Session()
        self.sleep = sleep

    def clean(self, value):
        """Redact even a malicious echoed credential before persistence/display."""
        if isinstance(value, dict):
            return {self.clean(k): self.clean(v) for k, v in value.items()
                    if k.lower() not in ('token', 'x-api-key', 'x-user-key', 'authorization')}
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, str):
            for secret in (self.config.api_key, self.config.user_key):
                if secret:
                    value = value.replace(secret, '[REDACTED]')
        return value

    def request(self, method, path, *, params=None, payload=None, request_id=None):
        if self.config.mode != 'demo' or not self.config.configured:
            raise BrokerError('Demo credentials are required.')
        allowed = path.startswith(('/api/v1/market-data/', '/api/v2/market-data/',
                                   '/api/v1/trading/info/demo/', '/api/v2/trading/info/demo/',
                                   '/api/v1/trading/execution/demo/', '/api/v2/trading/execution/demo/'))
        if not allowed or any(x in path for x in ('..', '?', '#', '%', '\\')):
            raise BrokerError('Endpoint is disabled in demo V1.')
        mutation = '/execution/' in path
        attempts = 1 if mutation else self.config.retries + 1
        for attempt in range(attempts):
            headers = {'x-api-key': self.config.api_key, 'x-user-key': self.config.user_key,
                       'x-request-id': request_id or str(uuid4()), 'Content-Type': 'application/json'}
            try:
                response = self.session.request(method, 'https://public-api.etoro.com' + path,
                    headers=headers, params=params, json=payload, timeout=self.config.timeout,
                    allow_redirects=False)
            except requests.RequestException:
                raise BrokerError('eToro timeout or connection failure.', uncertain=mutation) from None
            if response.status_code == 429 and attempt + 1 < attempts:
                try:
                    delay = max(2 ** attempt, float(response.headers.get('Retry-After', 0)))
                except ValueError:
                    delay = 2 ** attempt
                if not math.isfinite(delay) or delay > 30:
                    raise BrokerError('eToro HTTP 429; retry later.')
                self.sleep(delay)
                continue
            if not 200 <= response.status_code < 300:
                raise BrokerError(f'eToro HTTP {response.status_code}.',
                                  uncertain=mutation and (response.status_code >= 500 or response.status_code == 408))
            try:
                result = self.clean(json.loads(response.text, parse_float=Decimal))
                if not isinstance(result, dict):
                    raise ValueError()
                return result
            except (ValueError, TypeError):
                raise BrokerError('Invalid eToro response.', uncertain=mutation) from None
