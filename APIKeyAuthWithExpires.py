from requests.auth import AuthBase
import time
from APIKeyAuth import generate_signature


class APIKeyAuthWithExpires(AuthBase):

    """Attaches API Key Authentication to the given Request object. This implementation uses `expires`."""

    def __init__(self, api_key=None, api_secret=None):
        """Init with Key & Secret."""
        self.api_key = api_key
        self.api_secret = api_secret

    def __call__(self, r):
        """
        Called when forming a request - generates api key headers. This call uses `expires` instead of nonce.

        This way it will not collide with other processes using the same API Key if requests arrive out of order.
        For more details, see https://www.bitmex.com/app/apiKeys
        """
        # modify and return the request
        expires = int(round(time.time()) + 5)  # 5s grace period in case of clock skew
        r.headers['api-expires'] = str(expires)
        r.headers['api-key'] = self.api_key
        r.headers['api-signature'] = generate_signature(self.api_secret, r.method, r.url, expires, r.body or '')

        return r
