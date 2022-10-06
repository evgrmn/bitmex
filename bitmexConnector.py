import logging
from bitmex_websocket import BitMEXWebsocket
def setup_logger():
    # Prints logger info to terminal
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Change this to DEBUG if you want a lot more info
    ch = logging.StreamHandler()
    # create formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # add formatter to ch
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

logger = setup_logger()
    # Instantiating the WS will make it connect. Be sure to add your api_key/api_secret.
    # ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1", symbol="XBTUSD", api_key=None, api_secret=None)
ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1", symbol=smb, api_key="j8HtZUBbiGfL44SlJG8oOPOQ", api_secret="9TUT7v0aySyC_3gDHInCFpNJtOZK7mVwgtYNZzdxHMzPUsO1")
logger.info("Instrument data: %s" % ws.get_instrument())
