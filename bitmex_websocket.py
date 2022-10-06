import sys
import websocket
import threading
import traceback
from time import sleep
import json
import string
import logging
try:
    import urlparse
except ImportError:
    from urllib.parse import urlparse#import urllib.parse#urlparse
    from urllib.parse import urlunparse
import math
from util.actual_kwargs import actual_kwargs
from util.api_key import generate_nonce, generate_signature

import requests
import time
from datetime import datetime
import base64
import uuid
from APIKeyAuthWithExpires import APIKeyAuthWithExpires
#import requests
print(requests.__version__)


# Naive implementation of connecting to BitMEX websocket for streaming realtime data.
# The Marketmaker still interacts with this as if it were a REST Endpoint, but now it can get
# much more realtime data without polling the hell out of the API.
#
# The Websocket offers a bunch of data as raw properties right on the object.
# On connect, it synchronously asks for a push of all this data then returns.
# Right after, the MM can start using its data. It will be updated in realtime, so the MM can
# poll really often if it wants.
class BitMEXWebsocket():

    def __del__(self):
        aa = 0
        #print ("deleted deleted deleted deleted deleted deleted deleted deleted deleted")
        #print ("deleted deleted deleted deleted deleted deleted deleted deleted deleted")
        #print ("deleted deleted deleted deleted deleted deleted deleted deleted deleted")

    # Don't grow a table larger than this amount. Helps cap memory usage.
    MAX_TABLE_LEN = 200

    # We use the actual_kwargs decorator to get all kwargs sent to this method so we can easily pass
    # it to a validator function.
    #def scroll_info_display():
        #print "yes"

    @actual_kwargs()
    def __init__(self, endpoint=None, symbol=None, api_key=None, api_secret=None, info_display=None, recovery=None):
        '''Connect to the websocket and initialize data stores.'''
        self.endpoint = endpoint
        self.api_key = api_key
        self.api_secret = api_secret
        self.symbol_list = symbol
        self.recovery = recovery

        self.info_display = info_display
        self.logger = logging.getLogger(__name__)        
        self.logger.debug("Initializing WebSocket.")
        self.conn_timeout = 5
        self.__validate(self.__init__.actual_kwargs)
        self.__reset(self.__init__.actual_kwargs)
        self.message_counter = 0

        #self.logBmex = {}
        #self.logNum = 0
        #self.stopTrading = 0
        self.logNumFatal = 0#logNumFatal < 1000 => not fatal; 1000 < logNumFatal < 2000 => reload terminal; logNumFatal > 2000 => stop all
        self.maxRetryRest = 3#number of retry attempts for non-trading orders like POST, PUT, DELETE
        self.time_response = 0#used to retry unsuccessful orders
        self.myOrderID = ''
        self.timeoutOccurred = ''

        # We can subscribe right in the connection querystring, so let's build that.
        # Subscribe to all pertinent endpoints
        wsURL = self.__get_url()
        self.logger.info("Connecting to %s" % wsURL)
        self.__connect(wsURL) #If connection is lost then websocket is pending. So if the connection is restored all missed data will be loaded. It could be a large amount of data. Lest to load all data, it might be better to restart websocket
        if self.logNumFatal == 0:
            self.logger.info('Connected to WS.')
            self.info_display('Connected to WS.')
            # Connected. Wait for partials
            self.__wait_for_tables()
            if self.logNumFatal == 0:
                self.logger.info('Got all market data. Starting.')

        # Prepare HTTPS session
        
        self.session = requests.Session()
        #print ('&&&&&&&&&&& session $$$$$$$$$$$$', self.session)
        self.session.headers.update({'user-agent': 'CoinDealer'})
        self.session.headers.update({'content-type': 'application/json'})
        self.session.headers.update({'accept': 'application/json'})
        

    def exit(self):
        '''Call this to exit - will close websocket.'''
        try:
            self.exited = True
            self.ws.close()
        except:
            print("exit exception")

    def place_limit(self, quantity, price, clOrdID, symbol):
        #Place a limit order
        postdict = {
            'symbol': symbol,
            'orderQty': quantity,
            'price': price,
            'clOrdID': clOrdID,
            'ordType': "Limit"
        }
        return self._curl_bitmex(path="order", postdict=postdict, verb="POST")

    def replace_limit(self, quantity, price, orderID, symbol):
        #Replace a limit order
        postdict = {
            'symbol': symbol,
            'price': price,
            'orderID': orderID,
            'leavesQty': abs(quantity),
            'ordType': "Limit"
            #'orderQty': quantity,
        }
        return self._curl_bitmex(path="order", postdict=postdict, verb="PUT")

    def remove_order(self, orderID):
        #Delete an order. Delete order by number
        postdict = {
            'orderID': orderID
        }
        #print(postdict)
        return self._curl_bitmex(path="order", postdict=postdict, verb="DELETE")
    
    def trading_execution(self):
        #execution = self._curl_bitmex(path="execution?count=200&reverse=true", verb="GET")
        #for val in execution 
        return self._curl_bitmex(path="execution?count=20&reverse=true", verb="GET")

    #def trading_history(self, histCount):
    #    return self._curl_bitmex(path="execution/tradeHistory?count=" + str(histCount) + "&reverse=true", verb="GET")

    def trading_history(self, histCount, start):
        return self._curl_bitmex(path="execution/tradeHistory?count=" + str(histCount) + "&start=" + str(start) + "&reverse=false", verb="GET")

    def sample_execution(self):
        filt = '{"execType": "new"}'
        return self._curl_bitmex(path="execution?filter=%7B%22execType%22%3A%20%22New%22%7D&count=100&reverse=false", verb="GET")

    def urgent_announcement(self):
        return self._curl_bitmex(path="/announcement/urgent", verb="GET")

    def _curl_bitmex(self, path, verb, postdict=None, timeout=7, teorPrice=None):
        #Send a request to BitMEX Servers.
        def info_warn_err(whatNow, textNow, codeNow=0):
            if whatNow == "INFO":
                self.logger.info(textNow)
            elif whatNow == "WARN":
                self.logger.warning(textNow)
                #self.logNum += 1; self.logBmex[self.logNum] = textNow
                #if codeNow == 999: self.stopTrading = codeNow
                if codeNow > self.logNumFatal: self.logNumFatal = codeNow
            else:
                self.logger.error(textNow)
                #self.logNum += 1; self.logBmex[self.logNum] = textNow
                #if codeNow == 999: self.stopTrading = codeNow
                if codeNow > self.logNumFatal: self.logNumFatal = codeNow

        url = self.endpoint + path
        cur_retries = 1

        # Auth: API Key/Secret
        auth = APIKeyAuthWithExpires(self.api_key, self.api_secret)
        #print('-----', path, '--auth--', auth)

        while True:
            stop_retries = cur_retries
            # Make the request
            response = None

            python_retry = cur_retries
            if postdict:
                if verb == 'POST':
                    side = 'Buy'
                    if postdict['orderQty'] < 0: side = 'Sell'
                    if self.recovery[side]['attempt'] != 0: python_retry = self.recovery[side]['attempt']
                #python_retry = self.recovery['attempt'] if verb == 'POST' and self.recovery['attempt'] != 0 else cur_retries
                #print('--------postdict------------', postdict)
            try:
                if teorPrice is None:
                    info_warn_err("INFO", "(" + url[0]+url[1]+url[2]+url[3]+url[4] + ") sending(%s) %s to %s: %s" % (python_retry, verb, path, json.dumps(postdict or '')))
                else:
                    info_warn_err("INFO", "(" + url[0]+url[1]+url[2]+url[3]+url[4] + ") sending(%s) %s to %s: %s, teor: %s" % (python_retry, verb, path, json.dumps(postdict or ''), teorPrice))
                try:			# python3
                    req = requests.Request(verb, url, json=postdict, auth=auth, params=None)
                except:			# python2
                    if not postdict: 
                        req = requests.Request(verb, url, data=postdict, auth=auth, params=None)
                    else:
                        req = requests.Request(verb, url, data = json.dumps(postdict), auth=auth, params=None)	#new order
                        
                #
                prepped = self.session.prepare_request(req)
                response = self.session.send(prepped, timeout=timeout)
                # Make non-200s throw
                response.raise_for_status()

            except requests.exceptions.HTTPError as e:
                #print('---------------HTTPError--------------')
                if response is None:
                    raise e

                cur_retries += 1

                # 401 - Auth error. This is fatal.
                if response.status_code == 401:
                    info_warn_err("ERROR", "API Key or Secret incorrect (401): " + response.text, 2001)#stop all

                # 404 - can be thrown if order does not exist
                elif response.status_code == 404:
                    if verb == 'DELETE' and postdict:
                        info_warn_err("WARN", "DELETE orderID=%s: not found (404)" % postdict['orderID'], response.status_code)
                    elif verb == 'PUT' and postdict:
                        info_warn_err("WARN", "PUT orderID=%s: not found (404)" % postdict['orderID'], response.status_code)#DO recovery
                    else:
                        info_warn_err("ERROR", "Unable to contact API (404). %s: %s" % (url, json.dumps(postdict or '')), 1001)#reload terminal, DO recovery

                # 429 - ratelimit. If orders are posted or put too often
                elif response.status_code == 429:
                    info_warn_err("WARN", "Rate limit exceeded (429). %s: %s" % (url, json.dumps(postdict or '')), response.status_code)#DO retry (recovery)
                    time.sleep(1)

                # 503 - BitMEX temporary downtime. Try again
                elif response.status_code == 503:
                    error = response.json()['error']
                    message = error['message'] if error else ''
                    info_warn_err("WARN", message + " (503). %s: %s" % (url, json.dumps(postdict or '')), response.status_code)#DO retry (recovery)

                elif response.status_code == 400:
                    error = response.json()['error']
                    message = error['message'].lower() if error else ''
                    if verb == 'PUT' and 'invalid ordstatus' in message:# move order with origClOrdID does not exist. Probably already executed
                        info_warn_err("WARN", error['message'] + " (400). %s: %s" % (url, json.dumps(postdict or '')), response.status_code)#DO recovery
                    elif verb == 'POST' and 'duplicate clordid' in message:
                        info_warn_err("ERROR", error['message'] + " (400). %s: %s" % (url, json.dumps(postdict or '')), 1)#impossible situation => stop trading
                    elif 'insufficient available balance' in message:
                        info_warn_err("ERROR", error['message'] + " (400). %s: %s" % (url, json.dumps(postdict or '')), 2)#NO retry, stop trading
                    elif 'this request has expired' in message:#This request has expired - `expires` is in the past
                        info_warn_err("WARN", error['message'] + " (400). %s: %s" % (url, json.dumps(postdict or '')), 998)#DO retry (recovery)
                    elif 'too many open orders' in message:#When limit of 200 orders reached
                        info_warn_err("WARN", error['message'] + " (400). %s: %s" % (url, json.dumps(postdict or '')), 5)#NO retry, stop trading
                    else:#Example: wrong parameters set (tickSize, lotSize, etc)
                        errCode = 3 if postdict else 997
                        info_warn_err("ERROR", error['message'] + " (400 else). %s: %s" % (url, json.dumps(postdict or '')), errCode)#NO retry, stop trading
                    #self.exit()
                else:#Unknown error type
                    errCode = 4 if postdict else 996
                    info_warn_err("ERROR", "Unhandled %s: %s. %s: %s" % (e, response.text, url, json.dumps(postdict or '')), errCode)#NO retry, stop trading
                    #self.exit()

            except requests.exceptions.Timeout as e:#sometimes there is no answer during timeout period (currently = 7 sec).
                if postdict:#(POST, PUT or DELETE) => terminal reloads
                    self.timeoutOccurred = 'Timed out on request'#reloads terminal
                    errCode = 0
                else:
                    errCode = 999
                    cur_retries += 1
                info_warn_err("WARN", "Timed out on request. %s: %s" % (url, json.dumps(postdict or '')), errCode)
                self.info_display("Websocket. Timed out on request")

            except requests.exceptions.ConnectionError as e:
                info_warn_err("ERROR", "Unable to contact API: %s. %s: %s" % (e, url, json.dumps(postdict or '')), 1002)#reload terminal, DO recovery
                self.info_display("Websocket. Unable to contact API")
                cur_retries += 1
                #self.exit()

            if postdict:# trading orders (POST, PUT, DELETE)
                if cur_retries == stop_retries:# means no errors
                    if self.timeoutOccurred == '':
                        pos_beg = response.text.find('"orderID":"') + 11
                        pos_end = response.text.find('"', pos_beg)
                        self.myOrderID = response.text[pos_beg:pos_end]
                    else:
                        self.myOrderID = self.timeoutOccurred
                    if self.logNumFatal < 1000: self.logNumFatal = 0
                break
            else:
                if cur_retries > self.maxRetryRest:
                    info_warn_err("ERROR", "Max retries hit. Reboot", 1003)
                    self.info_display("ERROR, Max retries hit. Reboot")
                    #self.exit()
                    break
                if cur_retries == stop_retries:# means no errors
                    if self.logNumFatal < 1000: self.logNumFatal = 0
                    break
            if path == '/announcement/urgent':
                break
            else:
                time.sleep(3)
        #print (response.json())


        #print('-------cur_retries--------', cur_retries)

        #print('-----------------response-------------', response)
        #print('-----------------response.json()-------------', response.json())
        #print(response.json())
        self.time_response = datetime.utcnow()
        if response:
            return response.json()
        else:
            return None












    def get_ticker(self, ticker):
        '''Return a ticker object. Generated from quote and trade.''' 
        for i, symbol in enumerate(self.symbol_list):
            #print(self.data)
            for val in reversed(self.data['quote']):
                if val['symbol'] == symbol:
                    ticker[i]["bid"] = val['bidPrice']
                    ticker[i]["ask"] = val['askPrice']
                    ticker[i]["bidSize"] = val['bidSize']
                    ticker[i]["askSize"] = val['askSize']
                    break
        return ticker
        #return {k: round(float(v or 0), instrument['tickLog']) for k, v in ticker.iteritems()}
    def get_position(self, positions):
        # Return a position object generated from position
        for i, symbol in enumerate(self.symbol_list):
            positions[i]["SYMB"] = symbol          
            for val in self.data['position']:                
                if val['symbol'] == symbol:                    
                    positions[i]["POS"] = val['currentQty']
                    positions[i]["ENTRY"] = val['avgEntryPrice']
                    positions[i]["MCALL"] = val['marginCallPrice']
                    positions[i]["PNL"] = val['unrealisedPnl']
                    break
        return positions
    def get_instrument(self, instruments):
        '''Get the raw instrument data for this symbol.'''
        # Turn the 'tickSize' into 'tickLog' for use in rounding
        for i, symbol in enumerate(self.symbol_list):
            for val in self.data['instrument']:
                if val['symbol'] == symbol:
                    instruments[i]["isin"] = val['symbol']
                    instruments[i]["state"] = val['state']
                    #instruments[i]["maxPrice"] = val['maxPrice']
                    instruments[i]["fundingRate"] = val['fundingRate']
                    instruments[i]["tickSize"] = val['tickSize']
                    #instruments[i]["lowPrice"] = val['lowPrice']
                    #instruments[i]["highPrice"] = val['highPrice']
                    instruments[i]["volume24h"] = val['volume24h']
                    instruments[i]["lotSize"] = val['lotSize']
                    if instruments[i]["rank"] == 0: instruments[i]["rank"] = 1
                    #instruments[i]["fundingTimestamp"] = val['fundingTimestamp']
                    break
        return instruments

# Call every 10 ms (?). Check existing of new trades 
    def get_exec(self):
        # Return raw execution list
        return self.data['execution']

    def open_orders(self):
        # Return open orders
        return self.data['order']

    def get_funds(self):
        '''Get your margin details.'''
        #print(self.data['margin'][0])
        return self.data['margin'][0]

    def market_depth(self):
        '''Get market depth (orderbook). Returns all levels.'''
        return self.data['orderBookL2']

    def recent_trades(self):
        '''Get recent trades.'''
        return self.data['trade']

    #
    # End Public Methods
    #
    def del_socket(self):
        del self.ws
        del self.wst
        del self.session
        #del self.data
        #del self.keys
        #del self.config
        #del self.exited

    def __connect(self, wsURL):
        try:
            '''Connect to the websocket in a thread.'''
            self.logger.debug("Starting thread")
            self.ws = websocket.WebSocketApp(wsURL,
                                             on_message=self.__on_message,
                                             on_close=self.__on_close,
                                             on_open=self.__on_open,
                                             on_error=self.__on_error,
                                             header=self.__get_auth())
            #del self.ws
            self.wst = threading.Thread(target=lambda: self.ws.run_forever())

            self.wst.daemon = True
            self.wst.start()
            self.logger.debug("Started thread")

            # Wait for connect before continuing
            conn_timeout = 5
            while (not self.ws.sock or not self.ws.sock.connected) and conn_timeout:
                sleep(1)
                conn_timeout -= 1
            if not conn_timeout:
                self.logger.error("Couldn't connect to WS!")
                if self.logNumFatal < 1004: self.logNumFatal = 1004
                #self.logNum += 1; self.logBmex[self.logNum] = "Couldn't connect to WS. Restarting..."
        except:
                self.logger.error("Exception while connecting to WS. Restarting...")
                if self.logNumFatal < 1005: self.logNumFatal = 1005
                #self.logNum += 1; self.logBmex[self.logNum] = "Exception while connecting to WS. Restarting..."

    def __get_auth(self):
        '''Return auth headers. Will use API Keys if present in settings.'''
        try:
            if self.config['api_key']:
                self.logger.info("Authenticating with API Key.")
                # To auth to the WS using an API key, we generate a signature of a nonce and
                # the WS API endpoint.
                nonce = generate_nonce()
                return [
                    "api-nonce: " + str(nonce),
                    "api-signature: " + generate_signature(self.config['api_secret'], 'GET', '/realtime', nonce, ''),
                    "api-key:" + self.config['api_key']
                ]
            else:
                self.logger.info("Not authenticating.")
                return []
        except:
            self.logger.error("Exception while authenticating. Restarting...")
            if self.logNumFatal < 1006: self.logNumFatal = 1006
            #self.logNum += 1; self.logBmex[self.logNum] = "Exception while authenticating. Restarting..."
            return []

    def __get_url(self):
        '''
        Generate a connection URL. We can define subscriptions right in the querystring.
        Most subscription topics are scoped by the symbol we're listening to.
        '''

        # You can sub to orderBookL2 for all levels, or orderBook10 for top 10 levels & save bandwidth
#        symbolSubs = ["execution", "instrument", "order", "orderBookL2", "position", "quote", "trade"]
        #symbolSubs = ["execution", "instrument", "order", "position", "quote", "trade"]
        symbolSubs = ["execution", "instrument", "order", "position", "quote"] #, "quote"
        genericSubs = ["margin"]

        '''subscriptions = [sub + ':' + self.config['symbol'] for sub in symbolSubs]
        subscriptions += genericSubs'''
        

        subscriptions = []
        for symbolName in self.config['symbol']:
            for sub in symbolSubs:
                subscriptions += [sub + ':' + symbolName]
                
        subscriptions += genericSubs
        try:		#python 2.7
            urlParts = list(urlparse.urlparse(self.config['endpoint']))
            urlParts[0] = urlParts[0].replace('http', 'ws')
            urlParts[2] = "/realtime?subscribe=" + string.join(subscriptions, ",")
            return urlparse.urlunparse(urlParts)
        except:		#python 3.4
            urlParts = list(urlparse(self.config['endpoint']))
            urlParts[0] = urlParts[0].replace('http', 'ws')
            urlParts[2] = "/realtime?subscribe=" + ",".join(subscriptions)
            return urlunparse(urlParts)

    def __wait_for_tables(self):
        # On subscribe, this data will come down. Wait for the keys to show up from the ws
        wftcount = 0
        while not {'instrument', 'quote', 'execution', 'position', 'margin'} <= set(self.data):
            wftcount += 1
            if wftcount > 20:#fail after 2 seconds
                self.logger.info('(1)Tables are not loaded. Timeout expired')
                if self.logNumFatal < 1007: self.logNumFatal = 1007
                #self.logNum += 1; self.logBmex[self.logNum] = "(1)Tables are not loaded. Timeout expired"
                break
            sleep(0.1)

        wftcount2 = 0
        while (wftcount <= 20) and (len(self.data['instrument']) != len(self.symbol_list)):# or len(self.data['quote']) != len(self.symbol)
            wftcount2 += 1
            if wftcount2 > 20:#fail after 2 seconds
                self.logger.info('(2)Tables are not loaded. Timeout expired')
                if self.logNumFatal < 1008: self.logNumFatal = 1008
                #self.logNum += 1; self.logBmex[self.logNum] = "(2)Tables are not loaded. Timeout expired"
                break
            sleep(0.1)
        #self.logger.info("ddd = %s" % len(self.data['execution']))

    def __wait_for_account(self):
        '''On subscribe, this data will come down. Wait for it.'''
        # Wait for the keys to show up from the ws
#        while not {'margin', 'position', 'order', 'orderBookL2'} <= set(self.data):        
        while not {'margin', 'position', 'order'} <= set(self.data):
            sleep(0.1)

    def __wait_for_symbol(self, symbol):
        '''On subscribe, this data will come down. Wait for it.'''
#        while not {'instrument', 'trade', 'quote'} <= set(self.data):        
        while not {'instrument', 'quote'} <= set(self.data): #, 'quote'
            sleep(0.1)

    def __send_command(self, command, args=[]):
        '''Send a raw command.'''        
        self.ws.send(json.dumps({"op": command, "args": args}))

    def __on_message(self, ws, message):
        
        '''Handler for parsing WS messages.'''
        message = json.loads(message)
        self.logger.debug(json.dumps(message))

        table = message['table'] if 'table' in message else None
        action = message['action'] if 'action' in message else None
        self.message_counter = self.message_counter + 1
        #print "yes", self.message_counter

        try:            
            if 'subscribe' in message:
                self.logger.debug("Subscribed to %s." % message['subscribe'])                
            elif action:
                

                if table not in self.data:
                    self.data[table] = []
                    

                # There are four possible actions from the WS:
                # 'partial' - full table image
                # 'insert'  - new row
                # 'update'  - update row
                # 'delete'  - delete row
                if action == 'partial':
                    self.logger.debug("%s: partial" % table)
                    self.data[table] += message['data']
                    # Keys are communicated on partials to let you know how to uniquely identify
                    # an item. We use it for updates.
                    self.keys[table] = message['keys']
                elif action == 'insert':
                    self.logger.debug('%s: inserting %s' % (table, message['data']))
                    self.data[table] += message['data']

                    # Limit the max length of the table to avoid excessive memory usage.
                    # Don't trim orders because we'll lose valuable state if we do.
                    if len(self.data[table]) > BitMEXWebsocket.MAX_TABLE_LEN:
                        self.data[table] = self.data[table][int(BitMEXWebsocket.MAX_TABLE_LEN / 2):]

                elif action == 'update':
                    self.logger.debug('%s: updating %s' % (table, message['data']))
                    # Locate the item in the collection and update it.
                    for updateData in message['data']:
                        item = findItemByKeys(self.keys[table], self.data[table], updateData)
                        if not item:
                            return  # No item found to update. Could happen before push
                        item.update(updateData)
                        # Remove cancelled / filled orders
                        if table == 'order' and item['leavesQty'] <= 0:
                            self.data[table].remove(item)
                elif action == 'delete':
                    self.logger.debug('%s: deleting %s' % (table, message['data']))
                    # Locate the item in the collection and remove it.
                    for deleteData in message['data']:
                        item = findItemByKeys(self.keys[table], self.data[table], deleteData)
                        self.data[table].remove(item)
                else:
                    raise Exception("Unknown action: %s" % action)
                    
        except:
            self.logger.error(traceback.format_exc())#Error in bitmex_websocket.py. Take a look in api_bitmex.log. Restarting...
            if self.logNumFatal < 1009: self.logNumFatal = 1009
            #self.logNum += 1; self.logBmex[self.logNum] = "Error in bitmex_websocket.py. Take a look in api_bitmex.log. Restarting..."

    def __on_error(self, ws, error):
        '''Called on fatal websocket errors. We exit on these.'''
        if not self.exited:
            self.logger.error("Error : %s" % error)
            if self.logNumFatal < 1010: self.logNumFatal = 1010
            #self.logNum += 1; self.logBmex[self.logNum] = "Fatal websocket error: %s. Restarting..." % error

    def __on_open(self, ws):
        '''Called when the WS opens.'''        
        self.logger.debug("Websocket Opened.")

    def __on_close(self, ws):
        '''Called on websocket close.'''
        self.logger.info('Websocket Closed')
        if self.logNumFatal < 1011: self.logNumFatal = 1011
        #self.logNum += 1; self.logBmex[self.logNum] = "Websocket Closed. Restarting..."
        self.info_display("Websocket Closed. Restarting...")

    def __validate(self, kwargs):
        '''Simple method that ensure the user sent the right args to the method.'''
        if 'symbol' not in kwargs:
            self.logger.error("A symbol must be provided to BitMEXWebsocket()")
            if self.logNumFatal < 2003: self.logNumFatal = 2003
            #self.logNum += 1; self.logBmex[self.logNum] = "Error: A symbol must be provided to BitMEXWebsocket(). Restarting..."
            #self.exit()
            #sys.exit(1)
        if 'endpoint' not in kwargs:
            self.logger.error("An endpoint (BitMEX URL) must be provided to BitMEXWebsocket()")
            if self.logNumFatal < 2004: self.logNumFatal = 2004
            #self.logNum += 1; self.logBmex[self.logNum] = "Error: An endpoint (BitMEX URL) must be provided to BitMEXWebsocket(). Restarting..."
        if 'api_key' not in kwargs:
            self.logger.error("No authentication provided! Unable to connect.")
            if self.logNumFatal < 2005: self.logNumFatal = 2005
            #self.logNum += 1; self.logBmex[self.logNum] = "Error: No authentication provided! Unable to connect. Restarting..."

    def __reset(self, kwargs):
        '''Resets internal datastores.'''
        #print('rrrrrrrrrrrrrrr   Resets internal datastores.  rrrrrrrrrrrrrrrrrrrrr')
        self.data = {}
        self.keys = {}
        self.config = kwargs
        self.exited = False
        


# Utility method for finding an item in the store.
# When an update comes through on the websocket, we need to figure out which item in the array it is
# in order to match that item.
#
# Helpfully, on a data push (or on an HTTP hit to /api/v1/schema), we have a "keys" array. These are the
# fields we can use to uniquely identify an item. Sometimes there is more than one, so we iterate through all
# provided keys.
def findItemByKeys(keys, table, matchData):
    for item in table:
        matched = True
        for key in keys:
            if item[key] != matchData[key]:
                matched = False
        if matched:
            return item
