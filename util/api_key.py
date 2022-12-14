#import time, urlparse, hmac, hashlib
import time, hmac, hashlib
try:
    import urlparse			#python2
except ImportError:    
    from urllib.parse import urlparse		#python3
def generate_nonce():
    return int(round(time.time() * 1000))


# Generates an API signature.
# A signature is HMAC_SHA256(secret, verb + path + nonce + data), hex encoded.
# Verb must be uppercased, url is relative, nonce must be an increasing 64-bit integer
# and the data, if present, must be JSON without whitespace between keys.
#
# For example, in psuedocode (and in real code below):
#
# verb=POST
# url=/api/v1/order
# nonce=1416993995705
# data={"symbol":"XBTZ14","quantity":1,"price":395.01}
# signature = HEX(HMAC_SHA256(secret, 'POST/api/v1/order1416993995705{"symbol":"XBTZ14","quantity":1,"price":395.01}'))
def generate_signature(secret, verb, url, nonce, data):
    """Generate a request signature compatible with BitMEX."""
    # Parse the url so we can remove the base and extract just the path.
    try:
        parsedURL = urlparse.urlparse(url)
    except:
        parsedURL = urlparse(url)
    path = parsedURL.path
    if parsedURL.query:
        path = path + '?' + parsedURL.query

    # print "Computing HMAC: %s" % verb + path + str(nonce) + data
    try:
        message = bytes(verb + path + str(nonce) + data).encode('utf-8')		#python2
        signature = hmac.new(secret, message, digestmod=hashlib.sha256).hexdigest()			#python2
    except:
        message = bytes(verb + path + str(nonce) + data, 'utf-8')		#python3
        signature = hmac.new(secret.encode('utf-8'), message, digestmod=hashlib.sha256).hexdigest()		#python3

    
    
    return signature
