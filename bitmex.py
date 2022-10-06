#https://www.bitmex.com/app/perpetualContractsGuide
#https://www.bitmex.com/app/restAPI
#https://testnet.bitmex.com/app/wsAPI
#https://testnet.bitmex.com/app/restAPI#Request-Rate-Limits
#https://bitmex.freshdesk.com/en/support/solutions/articles/13000080520-execution

try:
    from Tkinter import *		#python2
except ImportError:
    from tkinter import *		#python3
root = Tk()
import time
from bitmex_websocket import BitMEXWebsocket
import logging
from time import sleep
import pymysql
import pymysql.cursors
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from collections import OrderedDict
from random import randint
import pathlib
import sys
from collections import Mapping, Container
#Reserved EMI numbers (reserved_emi) in case of transactions that were made from the Bitmex terminal: 0 - XBTUSD, 10 - ETHUSD, 11 - XRPUSD, 12 - ETHXBT. Reserved numbers: 0, 10-99 for tickers, 1-9, 100-999 for robots.

reserved_emi = {'XBTUSD': 0, 'ETHUSD': 10, 'XRPUSD': 11, 'ETHXBT': 12}
XBt_TO_XBT = 100000000
ticker_list_for_warnings = []	#technical
symbol_list = []		#List from init.ini
positions = []			#Position by isin
orders = OrderedDict()	#All orders

#----------robo tip=1---------
allRoboBuys = dict()   #All buys (orders) by robot (orders mostly averaged). Price is key. The variable is used at any time to have orders sorted by price
allRoboSells = dict()  #All sells (orders) by robot (orders mostly averaged). Price is key. The variable is used at any time to have orders sorted by price
visavi = dict()        #When we are posing a new averaged order to the system, there is a visavi order at the opposite side which is postponed until the next timeframe occurres
#recovery works when there is an unsuccessful order needed to be replaced into the orderbook. Only POST recovery order possible. Only one Buy order and one Sell order
recovery = {'Buy':{'attempt':0, 'emi':0, 'symb_num':0, 'price':0, 'amount':0, 'contracts':0, 'rank':0}, 'Sell':{'attempt':0, 'emi':0, 'symb_num':0, 'price':0, 'amount':0, 'contracts':0, 'rank':0}}
#----------robo tip=1---------

price_rounding = []		#For proper displaying order book prices after dot
robots = OrderedDict()	#All robots parameters from mysql database and additional parameters
accounts = []			#All account parameters
ticker = []				#Prices and parameters by isin 
bg_color = 'gray98'
isin = 0
last_order = int((time.time() - 1591000000) * 10)		#renew last order number
num_pos = 5				#Number of lines in position table
num_book = 19			#Number of lines in order book ------Must be odd-------
num_acc = 2				#Number of lines in account table
num_robots = 15			#Number of lines in robots table
name_pos = ["SYMB", "POS", "ENTRY", "PNL", "MCALL", "STATE", "VOL24h", "FUND"]
name_book = ["   SELL    ", "   PRICE    ", "    BUY    "]
name_acc = ["ACCOUNT", "MARGINBAL", "AVAILABLE", "LEVERAGE", "PNL", "COMISS", "FUNDING", "CONTROL"]
name_robots = ["EMI", "SYMB", "TIP.MAX", "STATUS", "VOL", "PNL", "UNRLZD", "POS", "BUYS", "SELLS", "VISAVI", "CONSI"]
name_instruments = ["isin", "state", "maxPrice", "fundingRate", "tickSize", "lowPrice", "highPrice", "volume24h", "lotSize", "rank"]
book_window_trigger = 'off'		#technical variable for handler_book function
order_window_trigger = 'off'	#technical variable for handler_order function
robots_window_trigger = 'off'	#technical variable for handler_robots function
symb_book = ''		    		#technical variable for orders window
info_display_counter = 0		#technical
trades_display_counter = 0		#technical
funding_display_counter = 0		#technical
last_database_time = datetime(1900, 1, 1, 1, 1)
sum_f = 0; sum_b = 0; sum_s = 0							#need to delete
frames = {}				#all time frames used by robots. {'XBTUSD5': [], 'XBTUSD3': []}
framing = {}			#parameters for 'frames' variable
orders_dict = OrderedDict()	#contains order's 'clOrdID'
orders_dict_value = 0		#value of orders_dict

f9 = 'OFF'
def trade_state(event):
    global f9; global messageStopped
    if f9 == 'ON':
        f9 = 'OFF'
    elif f9 == 'OFF':
        f9 = 'ON'
        messageStopped = ''
        ws.logNumFatal = 0
    print(f9)
root.bind('<F9>',trade_state)

def terminal_reload(event):
    print('RELOAD TERMINAL')
    connection()
root.bind('<F3>',terminal_reload)

def humanFormat(volNow):
    if volNow > 1000000000:
        volNow = '{:.2f}'.format(round(volNow / 1000000000, 2))+'B'
    elif volNow > 1000000:
        volNow = '{:.2f}'.format(round(volNow / 1000000, 2))+'M'
    elif volNow > 1000:
        volNow = '{:.2f}'.format(round(volNow / 1000, 2))+'K'
    return volNow

def setup_logger():
    # Prints logger info to terminal
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Change this to DEBUG if you want a lot more info
    handler = logging.FileHandler('api_bitmex.log')
    ch = logging.StreamHandler()
    #create formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    #add formatter to ch
    ch.setFormatter(formatter)
    handler.setFormatter(formatter)
    logger.addHandler(ch)
    logger.addHandler(handler)
    logger.info('\n\nhello\n')
    pythonAddMoveStart = {}
    return logger

#----------------Warning window-------------------------
def warning_window(message):
    def on_closing():
        warn_window.destroy()
    robots_window_trigger = 'on'
    warn_window = Toplevel(root, pady=5) # , padx=5, pady=5
    warn_window.geometry('400x150+{}+{}'.format(450+randint(0, 7)*15, 300))
    warn_window.title("Warning")
    warn_window.protocol("WM_DELETE_WINDOW", on_closing)
    warn_window.attributes('-topmost', 1)
    tex = Text(warn_window, wrap=WORD)
    tex.insert(INSERT, message)
    tex.pack(expand=1)

#----------------Retry failed orders. Only one order possible and only POST----------------
def retry_orders(orders):
    if f9 == 'ON':
        for side in recovery:
            if recovery[side]['attempt'] > 0:
                recovery[side]['attempt'] += 1
                logger.info('recovery attempt='+str(recovery[side]['attempt'])+' emi='+str(recovery[side]['emi']))
                info_display('recovery attempt='+str(recovery[side]['attempt'])+' emi='+str(recovery[side]['emi']))
                post_order(recovery[side]['symb_num'], recovery[side]['emi'], side, recovery[side]['price'], recovery[side]['amount'], recovery[side]['contracts'], recovery[side]['rank'])

#----------------Calculating sumreal and comission----------------
def calculate(symbol, price, qnty, rate, fund):
    if symbol == 'XBTUSD':
        return { 'sumreal': qnty / price * fund, 'comiss': abs(qnty) / price * rate, 'funding': qnty / price * rate }
    elif symbol == 'ETHUSD':
        return { 'sumreal': -qnty * price * 0.000001 * fund, 'comiss': abs(qnty) * price * rate * 0.000001, 'funding': qnty * price * rate * 0.000001 }
    elif symbol == 'XRPUSD':
        return { 'sumreal': -qnty * price * 0.0002 * fund, 'comiss': abs(qnty) * price * rate * 0.0002, 'funding': qnty * price * rate * 0.0002 }
    elif symbol == 'ETHXBT':
        return { 'sumreal': -qnty * price * fund, 'comiss': abs(qnty) * price * rate, 'funding': qnty * price * rate }
    else:
        logger.error("'Calculate': symbol '%s' is not defined", symbol)
        exit(1)   

#----------------Fills recovery with orders's data for recovery or retry----------------
def get_ready_recovery(symb_num, emi, side, price, amount, contracts, rank):
    recovery[side]['attempt'] = 1
    recovery[side]['emi'] = emi
    recovery[side]['symb_num'] = symb_num
    recovery[side]['price'] = price
    recovery[side]['amount'] = amount
    recovery[side]['contracts'] = contracts
    recovery[side]['rank'] = rank

#----------------Cancels order----------------
def del_order(clOrdID):
    #info_display("Remove clOrdID="+clOrdID+" EMI="+str(orders[clOrdID]['emi']))
    logger.info('Deleting orderID='+orders[clOrdID]['orderID']+' clOrdID='+str(clOrdID))
    ws.remove_order(orders[clOrdID]['orderID'])
    if ws.logNumFatal == 0:
        if orders[clOrdID]['emi'] in robots:
            robots[orders[clOrdID]['emi']]['waitCount'] += 1
        delete_robo_file(orders[clOrdID]['emi'], clOrdID)
    return ws.logNumFatal

#----------------Replaces order----------------
def put_order(clOrdID, price, amount, contracts, rank, alreadyDeleted):
    logger.info('Putting orderID='+orders[clOrdID]['orderID']+' clOrdID='+str(clOrdID)+' price='+str(price)+' amount='+str(amount)+' contracts='+str(contracts)+' rank='+str(rank))
    #variant 1: the order (a) alters its price, but there is already an order (b) in the orderbook with such price: delete order (a); put order (b) with merged amount leaving price unchanged
    #variant 2: the order alters its price and no such price in the orderbook: put order with a new price
    #variant 3: the price is the same. in this case - the order puts with a new amount
    global recovery
    emi = orders[clOrdID]['emi']
    side = orders[clOrdID]['side']
    deleteID = ''
    if price != orders[clOrdID]['price']:#the price alters
        if side == 'Sell':
            if price in allRoboSells[emi]:#variant 1
                if allRoboSells[emi][price]['clOrdID'] != alreadyDeleted:
                    numError = del_order(clOrdID)
                    if numError == 0:#success
                        deleteID = clOrdID#remember deleted order for recovery in case put fails
                        if allRoboSells[emi][price]['rank'] > rank: rank = allRoboSells[emi][price]['rank']
                        amount += allRoboSells[emi][price]['amount']#merge amount
                        contracts += allRoboSells[emi][price]['contracts']#merge contracts
                        clOrdID = allRoboSells[emi][price]['clOrdID']
                    else:#fail => forget and continue. we recover only binded orders (example: delete + put => delete ok, put with error => recover delete)
                        clOrdID = ''
        else:
            if price in allRoboBuys[emi]:#variant 1
                if allRoboBuys[emi][price]['clOrdID'] != alreadyDeleted:
                    numError = del_order(clOrdID)
                    if numError == 0:#success
                        deleteID = clOrdID#remember deleted order for recovery in case put fails
                        if allRoboBuys[emi][price]['rank'] > rank: rank = allRoboBuys[emi][price]['rank']
                        amount += allRoboBuys[emi][price]['amount']#merge amount
                        contracts += allRoboBuys[emi][price]['contracts']#merge contracts
                        clOrdID = allRoboBuys[emi][price]['clOrdID']
                    else:#fail => forget and continue. we recover only binded orders (example: delete + put => delete ok, put with error => recover delete)
                        clOrdID = ''
    if clOrdID != '':
        ws.replace_limit(amount, price, orders[clOrdID]['orderID'], orders[clOrdID]['symbol'])
        if ws.logNumFatal == 0:#success
            orders[clOrdID]['leavesQty'] = amount
            orders[clOrdID]['oldPrice'] = orders[clOrdID]['price']
            orders[clOrdID]['price'] = price
            orders[clOrdID]['contracts'] = contracts
            orders[clOrdID]['rank'] = rank
            orders[clOrdID]['transactTime'] = datetime.utcnow()
            orders[clOrdID]['orderID'] = ws.myOrderID
            if emi in robots:
                robots[emi]['waitCount'] += 1

            symb_num = symbol_list.index(robots[emi]['ISIN'])
            lot = int(orders[clOrdID]['leavesQty'] / orders[clOrdID]['contracts'] / instruments[symb_num]['lotSize']) * instruments[symb_num]['lotSize']
            if lot < instruments[symb_num]['lotSize']:#impossible situation
                lot = instruments[symb_num]['lotSize']
                logger.info("(put_order) Impossible leavesQty for clOrdID=%s", clOrdID)
            #saves also here because there is a possibility the terminal reloads before we come to orders_processing(). in this case the data will not be saved causing error
            save_robo_file(emi, clOrdID, price, orders[clOrdID]['leavesQty'], orders[clOrdID]['contracts'], lot, orders[clOrdID]['rank'], side)
        else:
            if deleteID != '':#recover deleted order
                get_ready_recovery(robots[emi]['SYMB_NUM'], emi, side, orders[deleteID]['price'], orders[deleteID]['leavesQty'], orders[deleteID]['contracts'], orders[deleteID]['rank'])
            clOrdID = ''
    return clOrdID

#----------------Adds new order----------------
def post_order(symb_num, emi, side, price, amount, contracts, rank):
    logger.info('Posting side='+side+' price='+str(price)+' amount='+str(amount)+' contracts='+str(contracts)+' rank='+str(rank))
    #variant 1: there is already an order with such price in the orderbook. in this case - merge the orders
    #variant 2: the price is vacant in the orderbook. in this case - post a new order
    global last_order; global recovery; global f9
    clOrdID = ''
    if side == "Sell":
        if price in allRoboSells[emi]:#variant 1
            clOrdID = put_order(allRoboSells[emi][price]['clOrdID'], price, allRoboSells[emi][price]['amount'] + amount, allRoboSells[emi][price]['contracts'] + contracts, allRoboSells[emi][price]['rank'], '')
        else:#variant 2
            last_order += 1
            clOrdID = str(last_order)+'.'+str(emi)
            ws.place_limit(-amount, price, clOrdID, symbol_list[symb_num])
            if ws.logNumFatal == 0:#success
                orders[clOrdID] = {'leavesQty': amount, 'price': price, 'symbol': symbol_list[symb_num], 'transactTime': str(datetime.utcnow()), 'side': side, 'emi': emi, 'orderID': ws.myOrderID, 'contracts':contracts, 'rank':rank, 'oldPrice':0}
                if emi in robots:
                    robots[emi]['waitCount'] += 1
            else:
                clOrdID = ''
    else:
        if price in allRoboBuys[emi]:#variant 1
            clOrdID = put_order(allRoboBuys[emi][price]['clOrdID'], price, allRoboBuys[emi][price]['amount'] + amount, allRoboBuys[emi][price]['contracts'] + contracts, allRoboBuys[emi][price]['rank'], '')
        else:#variant 2
            last_order += 1
            clOrdID = str(last_order)+'.'+str(emi)
            ws.place_limit(amount, price, clOrdID, symbol_list[symb_num])
            if ws.logNumFatal == 0:#success
                orders[clOrdID] = {'leavesQty': amount, 'price': price, 'symbol': symbol_list[symb_num], 'transactTime': str(datetime.utcnow()), 'side': side, 'emi': emi, 'orderID': ws.myOrderID, 'contracts':contracts, 'rank':rank, 'oldPrice':0}
                if emi in robots:
                    robots[emi]['waitCount'] += 1
            else:
                clOrdID = ''
    if clOrdID != '':#success
        if recovery[side]['attempt'] > 0:
            recovery[side] = {'attempt':0, 'emi':0, 'symb_num':0, 'price':0, 'amount':0, 'contracts':0, 'rank':0}

        lot = int(orders[clOrdID]['leavesQty'] / orders[clOrdID]['contracts'] / instruments[symb_num]['lotSize']) * instruments[symb_num]['lotSize']
        if lot < instruments[symb_num]['lotSize']:#impossible situation
            lot = instruments[symb_num]['lotSize']
            logger.info("(post_order) Impossible leavesQty for clOrdID=%s", clOrdID)
        #saves also here because there is a possibility the terminal reloads before we come to orders_processing(). in this case the data will not be saved causing error
        save_robo_file(emi, clOrdID, price, orders[clOrdID]['leavesQty'], orders[clOrdID]['contracts'], lot, orders[clOrdID]['rank'], side)
    else:
        if recovery[side]['attempt'] > 0:
            if ws.logNumFatal <= 10:#error may be: (1) duplicate clOrdID, (2) insufficient balance, (3) wrong parameters, (4) unknown error, (5) Too many open orders
                f9 = 'OFF'
    return clOrdID


def deep_getsizeof(o, ids):
    d = deep_getsizeof
    if id(o) in ids:
        return 0 
    r = sys.getsizeof(o)
    ids.add(id(o)) 
    if isinstance(o, str) or isinstance(0, str):
        return r 
    if isinstance(o, Mapping):
        return r + sum(d(k, ids) + d(v, ids) for k, v in o.items()) 
    if isinstance(o, Container):
        return r + sum(d(x, ids) for x in o) 
    return r


#f_leak = open('memory_leak.txt', 'w')
f_leak = open('memory_leak.txt', 'w').close()
#f_leak.truncate()
#f_leak.close()
def save_leak(str_leak):
    with open('memory_leak.txt', 'a') as f:
        f.write(str_leak)

#----------------Saves robot's tip=1 data into file -------------------------
def save_robo_file(emi, clOrdID, price, amount, contracts, lot, rank, side):
    with open(str(emi)+'/'+clOrdID, 'w') as f:
        f.write(str(price)+';'+str(amount)+';'+str(contracts)+';'+str(lot)+';'+str(rank)+';'+side+'\n')
#----------------Delete robot's tip=1 data file -------------------------
def delete_robo_file(emi, clOrdID):
    try:
        file_to_rem = pathlib.Path(str(emi)+'/'+clOrdID)
        file_to_rem.unlink()
    except:
        a = 0
#----------------Saves robot's tip=1 visavi file -------------------------
def save_visavi_file(emi):
    with open('visavi'+str(emi), 'w') as f:
        f.write(str(visavi[emi]['price'])+';'+str(visavi[emi]['amount'])+';'+str(visavi[emi]['contracts'])+';'+str(visavi[emi]['clOrdID'])+';'+str(visavi[emi]['side'])+'\n')
#----------------Delete robot's tip=1 visavi file -------------------------
def delete_visavi_file(emi):
    file_to_rem = pathlib.Path('visavi'+str(emi))
    file_to_rem.unlink()
#----------------Saves robot's data into file -------------------------
def save_robot(emi, timeframe, symb_num, clcl, state):
    if state != 'initial':
    #if True:
        r = price_rounding[symb_num]
        data = str(frames[timeframe][-1]['date'])+';'+noll(str(frames[timeframe][-1]['time']), 6)+';'+'{:.10f}'.format(round(robots[emi]['VOLA_SHORT'], 10))+';'+'{:.10f}'.format(round(robots[emi]['VOLA_LONG'], 10))+';'+str(robots[emi]['scUp'])+';'+str(robots[emi]['scDown'])+';'+'{:.10f}'.format(round(robots[emi]['fixVOLA'], 10))+';'+'{:.10f}'.format(round(robots[emi]['fixEMA'], 10))+';'+add_zeroes(str(clcl),r+1)+';'+str(robots[emi]['MAX'])+';'+'{:.10f}'.format(round(robots[emi]['EMA_SHORT'], 10))+';'+'{:.10f}'.format(round(robots[emi]['EMA_LONG'], 10))+'\n'
        with open('robot'+str(emi)+'.txt', 'a') as f:
            f.write(data)

#----------------Robots-------------------------
def robot1(emi):#, timeframe, cl, state=None):
    pass



def robot2(emi):#, timeframe, cl, state=None):
    pass

robo = {}
robo[1] = robot1
robo[2] = robot2
#robo[4] = robot9
#robo[5] = robot9
#robo[6] = robot9
#robo[7] = robot9

#----------------Closing main window method-------------------------
def on_closing():
    connect_mysql.close()
    root.after_cancel(refresh_var)       
    root.destroy()

#----------------Add noll to month, day, hour, minute, second-------------------------
def noll(val, length):
    r = ''
    for i in range(length - len(val)):
        r = r + '0'
    return r + val

#----------------Load initial data into 'frames'-------------------------


#----------------Initial display trades and funding-------------------------
def initial_display(account):
    global last_database_time; global trades_display_counter; global funding_display_counter

    cursor_mysql.execute("select EMI, TICKER, DIR, AMOUNT, PRICE, TTIME, KOMISS from TRD.coins where DIR=-1 AND account=%s order by id desc limit 121", account)
    data = cursor_mysql.fetchall()
    funding_display_counter = 0
    text_funding.delete('1.0', END)
    for val in reversed(data):
        funding_display(val)

    cursor_mysql.execute("select EMI, TICKER, DIR, AMOUNT, TRADE_PRICE, TTIME, KOMISS, SUMREAL from TRD.coins where DIR<>-1 AND account=%s order by id desc limit 151", account)
    data = cursor_mysql.fetchall()
    trades_display_counter = 0
    text_trades.delete('1.0', END)
    for val in reversed(data):
        trades_display(val)

    cursor_mysql.execute("select max(TTIME) TTIME from TRD.coins where account=%s AND dir=-1", account)
    data = cursor_mysql.fetchall()
    if data[0]['TTIME']:
        last_database_time = datetime.strptime(str(data[0]['TTIME']), '%Y-%m-%d %H:%M:%S')

#----------------Add zeroes to price-------------------------
def add_zeroes(number, rounding):
    dot = number.find('.')
    if dot == -1:
        number = number + '.'
    n = len(number) - 1 - number.find('.')
    for i in range(rounding - n): number = number + '0'
    return number

#----------------Returns rounded price: buy price goes down, sell price goes up according to 'tickSize'------------------
def round_price(instr, price, direction):
    coeff = 1 / instruments[instr]['tickSize']
    result = int(coeff * price) / coeff
    if direction < 0 and result < price: result += instruments[instr]['tickSize']#sell prices
    return result

#----------------Configure price_rounding-------------------------
def rounding(instruments):
    global price_rounding; price_rounding = []
    for instrument in instruments:
        tickSize = str(instrument['tickSize'])
        if tickSize.find('.') > 0:
            price_rounding.append(len(tickSize) - 1 - tickSize.find('.'))
        else:
            price_rounding.append(0)

#----------------Save timeframes -------------------------
def save_timeframes_data(i, timeframe):
    ltm = frames[timeframe][-1]['time']
    date = str(ltm.year) + noll(str(ltm.month), 2)
    r = price_rounding[i]
    bid = str(round(frames[timeframe][-1]['bid'], r))
    ask = str(round(frames[timeframe][-1]['ask'], r))
    hi = str(round(frames[timeframe][-1]['hi'], r))
    lo = str(round(frames[timeframe][-1]['lo'], r))
    funding = '{:.4f}'.format(frames[timeframe][-1]['funding'] * 100)
    data = str(ltm.year)[2:4] + noll(str(ltm.month), 2) + noll(str(ltm.day), 2) + ';' + noll(str(ltm.hour), 2) + noll(str(ltm.minute), 2) + noll(str(ltm.second), 2) + ';' + add_zeroes(bid, r) + ';' + add_zeroes(ask, r) + ';' + add_zeroes(lo, r) + ';' + add_zeroes(hi, r) + ';' + funding + ';'
    with open(timeframe + '_' + date + '.txt', "a") as f:
        f.write(data + '\n')

#----------------Save data every minute-------------------------
def save_minute_data(i, tm, ltm):
    date = str(ltm.year) + noll(str(ltm.month), 2)
    r = price_rounding[i]
    bid = str(round(ticker[i]['open_bid'], r))
    ask = str(round(ticker[i]['open_ask'], r))
    hi = str(round(ticker[i]['hi'], r))
    lo = str(round(ticker[i]['lo'], r))
    funding = '{:.4f}'.format(ticker[i]['fundingRate'] * 100)
    data = str(ltm.year)[2:4] + noll(str(ltm.month), 2) + noll(str(ltm.day), 2) + ';' + noll(str(ltm.hour), 2) + noll(str(ltm.minute), 2) + ';' + add_zeroes(bid, r) + ';' + add_zeroes(ask, r) + ';' + add_zeroes(hi, r) + ';' + add_zeroes(lo, r) + ';' + funding
    with open(symbol_list[i] + '_' + date + '.txt', "a") as f:
        f.write(data + '\n')

#----------------Generate spaces for scroll widgets-------------------------
def gap(length, maximum):
    res = ''
    if maximum >= length:
        for i in range(maximum - length):
            res = res + ' '
    return res

#----------------Add 'SYMB_NUM' in robots-------------------------
def symbol_num_add(robot_isin, robot_emi):
    global robots
    for i, symbol in enumerate(symbol_list):
        if symbol == robot_isin:
            robots[robot_emi]['SYMB_NUM'] = i
            break
    else:
        robots[robot_emi]['SYMB_NUM'] = 'not_in_list'
        logger.error("Robot EMI '%s'. ISIN is not in symbol_list. Cannot calculate 'CONTROL' field", str(robot_emi))
        info_display("Robot EMI="+str(robot_emi)+". ISIN='"+robot_isin+"' is not in symbol_list")
        
#----------------Initialize not in list robot -------------------------         
def not_in_list_init(emi, symbol, time_struct):
    if time_struct < datetime(2021, 5, 31, 4, 30, 0) and symbol == 'XBTUSD': 					#Error patch. 100 XBTUSD min lot after 210531-0430
        emi = 0
    if emi == 0 and reserved_emi[symbol] != 'XBTUSD':					#Error patch. Sometimes non-XBTUSD closed with emi=0
        emi = reserved_emi[symbol]
    if emi not in robots:
        visavi[emi] = {'price':0, 'amount':0, 'contracts':0, 'clOrdID':'', 'side':''}
        robots[emi] = {'STATUS': 'NOT IN LIST', 'TIP': 'None', 'EMI': emi, 'ISIN': symbol, 'POS': 0, 'VOL': 0, 'COMISS': 0, 'SUMREAL': 0, 'LTIME': time_struct, 'PNL': 0, 'MAX': 0, 'sumOfBuyAmount':0, 'sumOfSellAmount':0, 'sumOfBuyContracts':0, 'sumOfSellContracts':0, 'waitCount':0, 'lastDn':999999999, 'lastUp':-999999999, 'roboPart':0, 'unrlzd':0, 'TIMEFR':0}#, 'lotBalance':0
        if emi not in allRoboBuys: allRoboBuys[emi] = dict()
        if emi not in allRoboSells: allRoboSells[emi] = dict()
        symbol_num_add(robots[emi]['ISIN'], robots[emi]['EMI'])
        info_display("Robot EMI=" + str(emi) +". Adding to 'robots' with STATUS='NOT IN LIST'")
        logger.info("Robot EMI=%s. Adding to 'robots' with STATUS='NOT IN LIST'", str(emi))
    return emi


def clear_params():
    #global robots; global orders; global frames; global framing; global allRoboBuys; global allRoboSells; global orders_dict; global orders_dict_value
    robots = OrderedDict()
    orders = OrderedDict()
    frames = {}
    framing = {}
    allRoboBuys = dict()
    allRoboSells = dict()
    for mySymbol in reserved_emi:
        allRoboBuys[reserved_emi[mySymbol]] = dict()
        allRoboSells[reserved_emi[mySymbol]] = dict()
    orders_dict = OrderedDict()
    orders_dict_value = 0

#----------------Load initial data by robots from mySQL-------------------------
def load_robots(symbol_list, account):
    global robots; global emi_list; global frames
    qwr = "select * from TRD.robots where ISIN in ("
    for i, symbol in enumerate(symbol_list):              
        if i == 0:
            c = ''
        else:
            c = ', ' 
        qwr = qwr + c + "'" + symbol + "'"
    qwr = qwr + ") order by SORT"
    cursor_mysql.execute(qwr)
    dat = cursor_mysql.fetchall()
    for robot in dat:
        emi = int(robot['EMI'])
        robots[emi] = robot
        robots[emi]['STATUS'] = 'WORK'
    cursor_mysql.execute("select TICKER ISIN, EMI, POS from (select emi, TICKER, sum(CASE WHEN DIR = 0 THEN AMOUNT WHEN DIR = 1 THEN -AMOUNT ELSE 0 END) POS from TRD.coins where account = %s and dir <> -1 group by EMI, TICKER) res where POS <> 0", account) # and EMI <> 0
    defuncts = cursor_mysql.fetchall()
    for ii, defunct in enumerate(defuncts):
        for i, emi in enumerate(robots):
            if defunct['EMI'] == emi:
                break
        else:
            #if int(defunct['EMI']) == 0:
            #    defunct['ISIN'] = 'None'            
            robots[int(defunct['EMI'])] = {'ISIN': defunct['ISIN'], 'POS': int(defunct['POS']), 'EMI': int(defunct['EMI']), 'STATUS': 'NOT IN LIST', 'TIP': 'None', 'TIMEFR':0, 'SMESH':0, 'PERSHORT':1, 'PERLONG':1, 'PERTHIRD':1, 'PERFOURTH':1, 'MAX':0, 'CAPITAL':0, 'MINCONT':0}
    tm = datetime.utcnow()
    for i, emi in enumerate(robots):
        cursor_mysql.execute("SELECT IFNULL(sum(SUMREAL), 0) SUMREAL, IFNULL(sum(AMOUNT), 0) POS, IFNULL(sum(abs(AMOUNT)), 0) VOL, IFNULL(sum(KOMISS), 0) COMISS, IFNULL(max(TTIME), '1900-01-01 01:01:01') LTIME FROM (SELECT SUMREAL, (CASE WHEN DIR = 0 THEN AMOUNT WHEN DIR = 1 THEN -AMOUNT ELSE 0 END) AMOUNT, KOMISS, TTIME FROM TRD.coins WHERE EMI = %s AND ACCOUNT = %s) aa", (emi, account))
        data = cursor_mysql.fetchall()#taker's commission fee has negative sign in the database
        for row in data:
            for col in row:             
                robots[emi][col] = row[col]   
                if col == 'POS' or col == 'VOL':
                    robots[emi][col] = int(robots[emi][col])
                if col == 'COMISS' or col == 'SUMREAL':
                    robots[emi][col] = float(robots[emi][col])
                if col == 'LTIME':
                    robots[emi][col] = datetime.strptime(str(robots[emi][col]), '%Y-%m-%d %H:%M:%S')
        robots[emi]['PNL'] = 0
        robots[emi]['FRAME'] = robots[emi]['ISIN'] + str(robots[emi]['TIMEFR'])# + noll(str(robots[emi]['SMESH']), 2)
        robots[emi]['EMA_SHORT'] = 0.1
        robots[emi]['EMA_LONG'] = 0.1
        robots[emi]['VOLA_SHORT'] = 0.1
        robots[emi]['VOLA_LONG'] = 0.1
        robots[emi]['ALPHA_SHORT'] = float(2) / (float(robots[emi]['PERSHORT']) + 1)
        robots[emi]['ALPHA_LONG'] = float(2) / (float(robots[emi]['PERLONG']) + 1)
        robots[emi]['A_SHORT'] = float(2) / (float(robots[emi]['PERTHIRD']) + 1)
        robots[emi]['A_LONG'] = float(2) / (float(robots[emi]['PERFOURTH']) + 1)
        robots[emi]['alphaSred'] = float(2) / (float(robots[emi]['PERSHORT'] + robots[emi]['PERLONG']) / 2 + 1)
        robots[emi]['fndCoefSell'] = 0.1
        robots[emi]['fndCoefBuy'] = 0.1
        robots[emi]['scUp'] = 0
        robots[emi]['scDown'] = 0
        robots[emi]['fixCl'] = 0.1
        robots[emi]['fixEMA'] = 0.1
        robots[emi]['fixVOLA'] = 0.1        
        robots[emi]['otstCalc'] = 0.1
        #add new fields also in two places
        robots[emi]['sumOfBuyAmount'] = 0
        robots[emi]['sumOfSellAmount'] = 0
        robots[emi]['sumOfBuyContracts'] = 0
        robots[emi]['sumOfSellContracts'] = 0
        robots[emi]['waitCount'] = 0#if 'waitCount' != 0, this means than some order(s) not processed yet
        robots[emi]['lastDn'] = 999999999#the former bid price of orderbook
        robots[emi]['lastUp'] = -999999999#the former ask price of orderbook
        robots[emi]['roboPart'] = 0#divides robot's algorithm into parts. sometimes we have to wait whilst sent orders being processed, and only then continue with the next part
        robots[emi]['unrlzd'] = 0
        #robots[emi]['lotBalance'] = 0#'lotBalance' shows position in lots. One lot = robots[emi]['MAX']. robots[emi]['MAX'] depends on market price

        #print(robots[emi])
        #print('uuuuuuuuuuuuuuuu', emi, robots[emi]['MINCONT'])
        if emi not in allRoboBuys: allRoboBuys[emi] = dict()
        if emi not in allRoboSells: allRoboSells[emi] = dict()
        symbol_num_add(robots[emi]['ISIN'], robots[emi]['EMI'])
        if robots[emi]['TIMEFR'] != 0:
            #time = datetime(tm.year, tm.month, tm.day, tm.hour, tm.minute - tm.minute % robots[emi]['TIMEFR'], 0, 0)
            time = datetime.utcnow()
            try:
                #print('========== 1', frames)
                frames[robots[emi]['FRAME']]
                #print('========== 2', frames[robots[emi]['FRAME']])
                framing[robots[emi]['FRAME']]['robots'].append(emi)
                #print('========== 3', framing[robots[emi]['FRAME']]['robots'])
            except:
                frames[robots[emi]['FRAME']] = []
                framing[robots[emi]['FRAME']] = {'symbol': robots[emi]['ISIN'], 'period': robots[emi]['TIMEFR'], 'time': time, 'robots': [], 'open': 0, 'trigger': 0}
                framing[robots[emi]['FRAME']]['robots'].append(emi)
                #print('========== 4', framing[robots[emi]['FRAME']]['robots'])
                for num, symbol in enumerate(symbol_list):
                    if symbol == framing[robots[emi]['FRAME']]['symbol']:
                        framing[robots[emi]['FRAME']]['isin'] = num
                        break
                #load_frames(frames, framing, robots[emi]['FRAME'])
            #print(framing[robots[emi]['FRAME']])
        #print('----------', robots[emi])
    #for i in frames:
        #print('----------', i, frames[i])
        #print('----------', i,framing[i])

#----------------Calculate and load account results from mySQL-------------------------
def initial_mysql(account):
    global accounts
    cursor_mysql.execute("select IFNULL(sum(KOMISS),0.0) comiss, IFNULL(sum(SUMREAL),0.0) sumreal, IFNULL((select sum(KOMISS) from TRD.coins where dir < 0 and ACCOUNT = %s),0.0) funding from TRD.coins where dir >= 0 and ACCOUNT = %s", (account, account))
    data = cursor_mysql.fetchall()
    accounts['COMISS'] = float(data[0]['comiss'])
    accounts['PNL'] = float(data[0]['sumreal'])
    accounts['FUNDING'] = float(data[0]['funding'])

#----------------Insert row into database-------------------------
def insert_database(values):
    cursor_mysql.execute("insert into TRD.coins (EXECID,EMI,ISIN,TICKER,IDISIN,DIR,AMOUNT,AMOUNT_REST,PRICE,TEOR_PRICE,TRADE_PRICE,SUMREAL,KOMISS,ELAPSED,CLORDID,TTIME,ACCOUNT) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", values)
    connect_mysql.commit()

#----------------Read row from database-------------------------
def read_database(execID, emi):
    '''if emi == -1:
        cursor_mysql.execute("select EXECID, EMI from TRD.coins where EXECID=%s order by id desc", execID)
    else:
        cursor_mysql.execute("select EXECID, EMI from TRD.coins where EXECID=%s and EMI=%s order by id desc", (execID, emi))
    data = cursor_mysql.fetchall()
    if len(data) > 1:
        logger.error("Database gives more than 1 row by execID: %s", execID)
        exit(1)'''
    cursor_mysql.execute("select EXECID from TRD.coins where EXECID=%s and account=%s", (execID, accounts['ACCOUNT']))
    data = cursor_mysql.fetchall()
    return(data)

#----------------Orders processing-------------------------
def orders_processing(clOrdID, row):#<-- transaction()<--( trading_history() or get_exec() )
    global orders
    if not clOrdID:                     #Finding clOrdID if the order was placed with Bitmex
        for k, v in orders.items():
            if v['orderID'] == row['orderID']:
                clOrdID = k
                break
    dot = clOrdID.find('.')
    if dot != -1:
        '''for clOrdID in orders:#???????every clOrdID in orders must be unique. Why loop??????
            if orders[clOrdID]['orderID'] == row['orderID']:
                break
        else:
            info_display("Order " + row['orderID'] + " not in 'orders'")
            return'''
        #s = clOrdID.split('.')
        #emi = int(s[1])
        emi = int(clOrdID[dot+1:])
        price = row['price']
        #logger.info('---exec---', row)
        if row['execType'] == 'Canceled':
            info_display(row['execType'] + " " + row['side'] + ": " + clOrdID + " p=" + str(price) + " q=" + str(row['orderQty']-row['cumQty']))
            logger.info(row['execType'] + " %s: orderID=%s clOrdID=%s price=%s qty=%s", row['side'], row['orderID'], clOrdID, str(price), str(row['orderQty']-row['cumQty']))
            if emi in robots:# and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                if row['side'] == "Sell":
                    if price in allRoboSells[emi]:
                        robots[emi]['sumOfSellAmount'] -= allRoboSells[emi][price]['amount']
                        robots[emi]['sumOfSellContracts'] -= allRoboSells[emi][price]['contracts']
                        del allRoboSells[emi][price]
                        delete_robo_file(emi, clOrdID)
                else:
                    if price in allRoboBuys[emi]:
                        robots[emi]['sumOfBuyAmount'] -= allRoboBuys[emi][price]['amount']
                        robots[emi]['sumOfBuyContracts'] -= allRoboBuys[emi][price]['contracts']
                        del allRoboBuys[emi][price]
                        delete_robo_file(emi, clOrdID)
                robots[emi]['waitCount'] -= 1
            del orders[clOrdID]
        elif row['leavesQty'] == 0:
            info_display("Executed " + row['side'] + ": " + clOrdID + " p=" + str(row['lastPx']) + " q=" + str(row['lastQty']))
            logger.info("Executed %s: orderID=%s clOrdID=%s price=%s qty=%s", row['side'], row['orderID'], clOrdID, str(row['lastPx']), str(row['lastQty']))
            if emi in robots:# and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                if row['side'] == "Sell":
                    if price in allRoboSells[emi]:
                        robots[emi]['sumOfSellAmount'] -= allRoboSells[emi][price]['amount']
                        robots[emi]['sumOfSellContracts'] -= allRoboSells[emi][price]['contracts']
                        #robots[emi]['lotBalance'] -= allRoboSells[emi][price]['contracts']
                        del allRoboSells[emi][price]
                        delete_robo_file(emi, clOrdID)
                else:
                    if price in allRoboBuys[emi]:
                        robots[emi]['sumOfBuyAmount'] -= allRoboBuys[emi][price]['amount']
                        robots[emi]['sumOfBuyContracts'] -= allRoboBuys[emi][price]['contracts']
                        #robots[emi]['lotBalance'] += allRoboBuys[emi][price]['contracts']
                        del allRoboBuys[emi][price]
                        delete_robo_file(emi, clOrdID)
            if clOrdID in orders:#orders may be empty if we are here from trading_history()
                del orders[clOrdID]
        else:
            if row['execType'] == 'New':
                info_display(row['execType'] + " " + row['side'] + ": " + clOrdID + " p=" + str(price) + " q=" + str(row['orderQty']))
                logger.info(row['execType'] + " %s: orderID=%s clOrdID=%s price=%s qty=%s", row['side'], row['orderID'], clOrdID, str(price), str(row['orderQty']))
                if emi in robots:# and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                    isinNow = symbol_list.index(robots[emi]['ISIN'])
                    lot = int(row['orderQty'] / orders[clOrdID]['contracts'] / instruments[isinNow]['lotSize']) * instruments[isinNow]['lotSize']
                    if lot < instruments[isinNow]['lotSize']:#impossible situation
                        lot = instruments[isinNow]['lotSize']
                        logger.info("Impossible leavesQty for clOrdID=%s", clOrdID)
                    save_robo_file(emi, clOrdID, price, row['orderQty'], orders[clOrdID]['contracts'], lot, orders[clOrdID]['rank'], row['side'])
                    if row['side'] == "Sell":
                        robots[emi]['sumOfSellAmount'] += row['orderQty']
                        robots[emi]['sumOfSellContracts'] += orders[clOrdID]['contracts']
                        allRoboSells[emi][price] = {'clOrdID':clOrdID, 'amount':row['orderQty'], 'contracts':orders[clOrdID]['contracts'], 'lot':lot, 'rank':orders[clOrdID]['rank']}
                    else:
                        robots[emi]['sumOfBuyAmount'] += row['orderQty']
                        robots[emi]['sumOfBuyContracts'] += orders[clOrdID]['contracts']
                        allRoboBuys[emi][price] = {'clOrdID':clOrdID, 'amount':row['orderQty'], 'contracts':orders[clOrdID]['contracts'], 'lot':lot, 'rank':orders[clOrdID]['rank']}
                    robots[emi]['waitCount'] -= 1
                    if robots[emi]['waitCount'] == 0:#all sent orders are done
                        if robots[emi]['roboPart'] > 0:#robot's part 1 or 2 has been finished
                            robo[robots[emi]['TIP']](emi)#since visavi order (part 1) or merging (part 2) is done, then ready to continue making orders in part 3
            elif row['execType'] == 'Trade':
                info_display(row['execType'] + " " + row['side'] + ": " + clOrdID + " p=" + str(row['lastPx']) + " q=" + str(row['lastQty']))
                logger.info(row['execType'] + " %s: orderID=%s clOrdID=%s price=%s qty=%s", row['side'], row['orderID'], clOrdID, str(row['lastPx']), str(row['lastQty']))
                if emi in robots:# and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                    if row['side'] == "Sell":
                        if price in allRoboSells[emi]:
                            oldContracts = allRoboSells[emi][price]['contracts']
                            allRoboSells[emi][price]['amount'] -= row['lastQty']
                            #allRoboSells[emi][price]['contracts'] = int(allRoboSells[emi][price]['amount'] / allRoboSells[emi][price]['lot'])#неверная реализация
                            allRoboSells[emi][price]['contracts'] -= int(row['lastQty'] / allRoboSells[emi][price]['lot'])
                            if allRoboSells[emi][price]['contracts'] == 0: allRoboSells[emi][price]['contracts'] = 1
                            if clOrdID in orders: orders[clOrdID]['contracts'] = allRoboSells[emi][price]['contracts']
                            save_robo_file(emi, clOrdID, price, allRoboSells[emi][price]['amount'], allRoboSells[emi][price]['contracts'], allRoboSells[emi][price]['lot'], allRoboSells[emi][price]['rank'], row['side'])
                            robots[emi]['sumOfSellAmount'] -= row['lastQty']
                            robots[emi]['sumOfSellContracts'] -= (oldContracts - allRoboSells[emi][price]['contracts'])
                            #robots[emi]['lotBalance'] -= (oldContracts - allRoboSells[emi][price]['contracts'])
                    else:
                        if price in allRoboBuys[emi]:
                            oldContracts = allRoboBuys[emi][price]['contracts']
                            allRoboBuys[emi][price]['amount'] -= row['lastQty']
                            #allRoboBuys[emi][price]['contracts'] = int(allRoboBuys[emi][price]['amount'] / allRoboBuys[emi][price]['lot'])#неверная реализация
                            allRoboBuys[emi][price]['contracts'] -= int(row['lastQty'] / allRoboBuys[emi][price]['lot'])
                            if allRoboBuys[emi][price]['contracts'] == 0: allRoboBuys[emi][price]['contracts'] = 1
                            if clOrdID in orders: orders[clOrdID]['contracts'] = allRoboBuys[emi][price]['contracts']
                            save_robo_file(emi, clOrdID, price, allRoboBuys[emi][price]['amount'], allRoboBuys[emi][price]['contracts'], allRoboBuys[emi][price]['lot'], allRoboBuys[emi][price]['rank'], row['side'])
                            robots[emi]['sumOfBuyAmount'] -= row['lastQty']
                            robots[emi]['sumOfBuyContracts'] -= (oldContracts - allRoboBuys[emi][price]['contracts'])
                            #robots[emi]['lotBalance'] += (oldContracts - allRoboBuys[emi][price]['contracts'])
            elif row['execType'] == 'Replaced':
                info_display(row['execType'] + " " + row['side'] + ": " + clOrdID + " p=" + str(price) + " q=" + str(row['leavesQty']))
                logger.info(row['execType'] + " %s: orderID=%s clOrdID=%s price=%s qty=%s", row['side'], row['orderID'], clOrdID, str(price), str(row['leavesQty']))
                if emi in robots:# and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                    isinNow = symbol_list.index(robots[emi]['ISIN'])
                    lot = int(row['leavesQty'] / orders[clOrdID]['contracts'] / instruments[isinNow]['lotSize']) * instruments[isinNow]['lotSize']
                    if lot < instruments[isinNow]['lotSize']:#impossible situation
                        lot = instruments[isinNow]['lotSize']
                        logger.info("Impossible leavesQty for clOrdID=%s", clOrdID)
                    save_robo_file(emi, clOrdID, price, row['leavesQty'], orders[clOrdID]['contracts'], lot, orders[clOrdID]['rank'], row['side'])
                    oldPrice = orders[clOrdID]['oldPrice']
                    if row['side'] == "Sell":
                        if oldPrice != price:#variant 2: this order goes to a new price
                            if oldPrice in allRoboSells[emi]:
                                robots[emi]['sumOfSellAmount'] -= allRoboSells[emi][oldPrice]['amount']
                                robots[emi]['sumOfSellContracts'] -= allRoboSells[emi][oldPrice]['contracts']
                                del allRoboSells[emi][oldPrice]
                                allRoboSells[emi][price] = {'clOrdID':clOrdID, 'amount':row['leavesQty'], 'contracts':orders[clOrdID]['contracts'], 'lot':lot, 'rank':orders[clOrdID]['rank']}
                                robots[emi]['sumOfSellAmount'] += row['leavesQty']
                                robots[emi]['sumOfSellContracts'] += orders[clOrdID]['contracts']
                        else:#variant 1 or variant 3: the price is the same
                            if price in allRoboSells[emi]:
                                oldAmount = allRoboSells[emi][price]['amount']
                                oldContracts = allRoboSells[emi][price]['contracts']
                                allRoboSells[emi][price]['amount'] = row['leavesQty']
                                allRoboSells[emi][price]['contracts'] = orders[clOrdID]['contracts']
                                allRoboSells[emi][price]['lot'] = lot
                                allRoboSells[emi][price]['rank'] = orders[clOrdID]['rank']
                                robots[emi]['sumOfSellAmount'] += (row['leavesQty'] - oldAmount)
                                robots[emi]['sumOfSellContracts'] += (orders[clOrdID]['contracts'] - oldContracts)
                    else:
                        if oldPrice != price:#variant 2: this order goes to a new price
                            if oldPrice in allRoboBuys[emi]:
                                robots[emi]['sumOfBuyAmount'] -= allRoboBuys[emi][oldPrice]['amount']
                                robots[emi]['sumOfBuyContracts'] -= allRoboBuys[emi][oldPrice]['contracts']
                                del allRoboBuys[emi][oldPrice]
                                allRoboBuys[emi][price] = {'clOrdID':clOrdID, 'amount':row['leavesQty'], 'contracts':orders[clOrdID]['contracts'], 'lot':lot, 'rank':orders[clOrdID]['rank']}
                                robots[emi]['sumOfBuyAmount'] += row['leavesQty']
                                robots[emi]['sumOfBuyContracts'] += orders[clOrdID]['contracts']
                        else:#variant 1 or variant 3: the price is the same
                            if price in allRoboBuys[emi]:
                                oldAmount = allRoboBuys[emi][price]['amount']
                                oldContracts = allRoboBuys[emi][price]['contracts']
                                allRoboBuys[emi][price]['amount'] = row['leavesQty']
                                allRoboBuys[emi][price]['contracts'] = orders[clOrdID]['contracts']
                                allRoboBuys[emi][price]['lot'] = lot
                                allRoboBuys[emi][price]['rank'] = orders[clOrdID]['rank']
                                robots[emi]['sumOfBuyAmount'] += (row['leavesQty'] - oldAmount)
                                robots[emi]['sumOfBuyContracts'] += (orders[clOrdID]['contracts'] - oldContracts)
                    robots[emi]['waitCount'] -= 1
                    if robots[emi]['waitCount'] == 0:#all sent orders are done
                        if robots[emi]['roboPart'] > 0:#robot's part 1 or 2 has been finished
                            robo[robots[emi]['TIP']](emi)#since visavi order (part 1) or merging (part 2) is done, then ready to continue making orders in part 3
            if clOrdID in orders:#orders might be empty if we are here from trading_history()
                orders[clOrdID]['leavesQty'] = row['leavesQty']
    orders_display(clOrdID)

#----------------Calculates maximum lot to open-------------------------
def calculate_max(emi, price):
    if robots[emi]['STATUS'] != 'NOT IN LIST':
        calc = calculate(robots[emi]['ISIN'], price, -float(robots[emi]['POS']), 0, 1)
        capital = float(robots[emi]['CAPITAL']) / XBt_TO_XBT + robots[emi]['SUMREAL'] + calc['sumreal'] - robots[emi]['COMISS']#positive comiss has minus sign
        robots[emi]['MAX'] = int(capital * price * robots[emi]['MARGIN'] / 100)
        if robots[emi]['TIP'] == 1:
            capital = 1.04
            isinNow = symbol_list.index(robots[emi]['ISIN'])
            robots[emi]['MAX'] = int(capital * price / robots[emi]['MAXDAY'] / instruments[isinNow]['lotSize']) * instruments[isinNow]['lotSize']
            if robots[emi]['MAX'] < instruments[isinNow]['lotSize']: robots[emi]['MAX'] = instruments[isinNow]['lotSize']
            #print('-----robots[emi][''MAX'']------', robots[emi]['MAX'])

#----------------Trades and funding processing-------------------------
def transaction(row, param = None):
    time_struct = datetime.strptime(row['transactTime'][0:19], '%Y-%m-%dT%H:%M:%S')
    if row['execType'] == 'Trade':		################## trade ###################
        #print('rrrrrrrrrrrrrr', row)
        dot = row['clOrdID'].find('.')
        clientID = 0
        if dot == -1:					#The transaction was done from Bitmex terminal (clOrdID = '') or clOrdID has no EMI number
            emi = reserved_emi[row['symbol']]
            if row['clOrdID'] == '':
                clientID = 0
            else:
                clientID = int(float(row['clOrdID']))
        else:
            emi = int(row['clOrdID'][dot+1:])
            clientID = int(float(row['clOrdID']))
        #print('emi='+str(emi))                           #emi is not in list of loaded robots				
        emi = not_in_list_init(emi, row['symbol'], time_struct)
        data = read_database(row['execID'], -1)
        if not data:
        #if 0 == 0:
            position = robots[emi]['POS']
            direct = 0
            lastQty = row['lastQty']
            if row['side'] == 'Sell':
                lastQty = -row['lastQty']
                direct = 1
            calc = calculate(row['symbol'], row['lastPx'], float(lastQty), row['commission'], 1)
            robots[emi]['POS'] += lastQty
            robots[emi]['VOL'] += abs(lastQty)
            robots[emi]['COMISS'] += calc['comiss']
            robots[emi]['SUMREAL'] += calc['sumreal']
            robots[emi]['LTIME'] = time_struct
            accounts['COMISS'] += calc['comiss']
            accounts['PNL'] += calc['sumreal']
            #print('------trade------', 'homeNotional='+str(row['homeNotional']), 'sumreal='+str(calc['sumreal']))
            values = [row['execID'], emi, -1, row['symbol'], 99999, direct, abs(lastQty), row['leavesQty'], row['price'], 0, row['lastPx'], calc['sumreal'], calc['comiss'], 0, clientID, row['transactTime'][:-1], accounts['ACCOUNT']]
            insert_database(values)
            message = {'TICKER': row['symbol'], 'TTIME': row['transactTime'], 'DIR': direct, 'TRADE_PRICE': row['lastPx'], 'AMOUNT': abs(lastQty), 'EMI': emi}
            trades_display(message)
            orders_processing(row['clOrdID'], row)
            #if emi != reserved_emi[row['symbol']]:
            #    calculate_max(emi, row['lastPx'])
    elif row['execType'] == 'Funding': 	 ################## funding ###################
        message = {'TICKER': row['symbol'], 'TTIME': row['transactTime'], 'PRICE': row['price']}
        p = 0
        true_position = row['lastQty']
        true_funding = row['commission']
        if row['foreignNotional'] > 0:
            true_position = -true_position
            true_funding = -true_funding
        for n, emi in enumerate(robots):
            #check opened positions by robot, form data to display, write data to database if it absends
            if robots[emi]['ISIN'] == row['symbol'] and robots[emi]['POS'] != 0:
                p += robots[emi]['POS']
                #data = read_database(row['execID'], robots[emi]['EMI'])
                #if not data and time_struct > robots[emi]['LTIME']: #maybe time_struct >= robots[n]['LTIME']              
                if 0 == 0:
                    calc = calculate(row['symbol'], row['price'], float(robots[emi]['POS']), true_funding, 0)
                    message['EMI'] = robots[emi]['EMI']
                    message['AMOUNT'] = robots[emi]['POS']
                    message['KOMISS'] = calc['funding']               
                    values = [row['execID'], robots[emi]['EMI'], -1, row['symbol'], 99999, -1, robots[emi]['POS'], 0, row['price'], 0, row['price'], calc['sumreal'], calc['funding'], 0, 0, row['transactTime'][:-1], accounts['ACCOUNT']]
                    insert_database(values)            
                    #connect_mysql.commit()#????????????????? insert_database() alredy has this command
                    robots[emi]['COMISS'] += calc['funding']
                    robots[emi]['LTIME'] = time_struct
                    accounts['FUNDING'] += calc['funding']
                    funding_display(message)
        diff = true_position - p
        if diff != 0:#robots whith opened positions are took, but still some amount is left
            #data = read_database(row['execID'], 0)
            #if not data and time_struct > last_database_time:
            if 0 == 0:
                calc = calculate(row['symbol'], row['price'], float(diff), true_funding, 0)                   				
                emi = not_in_list_init(reserved_emi[row['symbol']] , row['symbol'], time_struct)      #emi is not in list of loaded robots
                message['EMI'] = robots[emi]['EMI']
                message['AMOUNT'] = diff
                message['KOMISS'] = calc['funding']
                values = [row['execID'], robots[emi]['EMI'], -1, row['symbol'], 99999, -1, diff, 0, row['price'], 0, row['price'], calc['sumreal'], calc['funding'], 0, 0, row['transactTime'][:-1], accounts['ACCOUNT']]
                insert_database(values)
                robots[emi]['COMISS'] += calc['funding']
                robots[emi]['LTIME'] = time_struct
                accounts['FUNDING'] += calc['funding']
                funding_display(message)
    elif row['execType'] == 'New':  ################## new order ###################
        clOrdID = row['clOrdID']
        if row['clOrdID'] == '':					#The order was placed from Bitmex
            global last_order
            last_order += 1
            emi = reserved_emi[row['symbol']]
            clOrdID = 'bitmex_'+str(last_order)+'.'+str(emi)
            not_in_list_init(emi , row['symbol'], time_struct) 
            orders[clOrdID] = {'leavesQty': row['leavesQty'], 'price': row['price'], 'symbol': row['symbol'], 'transactTime': row['transactTime'], 'side': row['side'], 'emi': emi, 'orderID': row['orderID'], 'contracts':1, 'rank':1, 'oldPrice':0}            
        orders_processing(clOrdID, row)
    elif row['execType'] == 'Canceled':     ################## cancel order ###################
        orders_processing(row['clOrdID'], row)
    elif row['execType'] == 'Replaced':     ################## replace order ###################
        orders_processing(row['clOrdID'], row)

#----------------Event handler Robots-------------------------
def handler_robots(event, y_pos):
    emi = None
    for val in robots:
        if robots[val]['y_position'] == y_pos:
            emi = val
            break
    if emi:
        if robots[emi]['STATUS'] != 'NOT IN LIST':
            global robots_window_trigger
            def callback():
                if robots[emi]['STATUS'] == 'WORK':
                    robots[emi]['STATUS'] = 'OFF'
                else:
                    robots[emi]['STATUS'] = 'WORK'
                on_closing()
            def on_closing():
                global robots_window_trigger; robots_window_trigger = 'off'
                robot_window.destroy()
            if robots_window_trigger == 'off':
                robots_window_trigger = 'on'
                robot_window = Toplevel(root, pady=5) # , padx=5, pady=5
                cx = root.winfo_pointerx()
                cy = root.winfo_pointery()
                robot_window.geometry('180x45+{}+{}'.format(cx-90, cy-10))
                robot_window.title("EMI = "+str(emi))
                robot_window.protocol("WM_DELETE_WINDOW", on_closing)
                robot_window.attributes('-topmost', 1)
                t = 'Disable'
                if robots[emi]['STATUS'] == 'OFF':
                    t = 'Enable'
                status = Button(robot_window, text=t, command=callback)
                status.pack()
                '''label1 = Label(robot_window, justify=LEFT)
                label1['text'] = "number\t" + str(order_number) + "\nsymbol\t" + orders[clOrdID]['symbol'] + "\nside\t" + orders[clOrdID]['side'] +"\nclOrdID\t" + clOrdID + "\nprice\t" + str(orders[clOrdID]['price']) + "\nquantity\t" + str(orders[clOrdID]['leavesQty'])
                label1.pack()
                button = Button(robot_window, text="Delete order", command=callback)
                button.pack()'''

#----------------Event handler Position-------------------------
def handler_pos(event, y_pos):
    global isin;
    if y_pos > len(symbol_list): y_pos = len(symbol_list)
    isin = y_pos-1;    
    for y in enumerate(symbol_list):
        for i in enumerate(label_pos):
            if y[0]+1 == y_pos:                
                label_pos[i[0]][y[0]+1]['bg'] = "yellow" #yellow
            else:
                if y[0]+1 > 0:
                    label_pos[i[0]][y[0]+1]['bg'] = bg_color

#----------------Event handler Order book-------------------------
def handler_book(event, y_pos): 
    global book_window_trigger; global symb_book; symb_book = symbol_list[isin]
    def refresh():
        book_window.title("Place order " + symbol_list[isin])
        global symb_book
        if symb_book != symbol_list[isin]:
            entry_price_ask.delete(0, END)
            entry_price_ask.insert(0, ticker[isin]['ask'])
            entry_price_bid.delete(0, END)
            entry_price_bid.insert(0, ticker[isin]['bid'])
            option_robots['menu'].delete(0, END)
            options = [0]
            for emi in robots:
                if robots[emi]['ISIN'] == symbol_list[isin]:
                    options.append(robots[emi]['EMI'])
            for i in options:
                option_robots['menu'].add_command(label=i, command=lambda v=emi_number, l=i:v.set(l))
            emi_number.set(options[0])
            symb_book = symbol_list[isin]
        book_window.after(500, refresh)        
    def on_closing():
        global book_window_trigger; book_window_trigger = 'off'
        book_window.after_cancel(refresh_var)       
        book_window.destroy()
    def callback_sell_limit():
        global last_order; global orders
        if quantity.get() and price_ask.get():
            try:
                int(quantity.get()); float(price_ask.get())
                t = 'yes'
            except:
                info_display("Adding a new order: fields must be numbers!") 
                t = 'no'
            if t == 'yes' and int(quantity.get()) != 0:
                qw = abs(int(quantity.get()))
                price = round_price(isin, float(price_ask.get()), -qw)
                if qw - int(qw / instruments[isin]['lotSize']) * instruments[isin]['lotSize'] != 0:
                    info_display('The ' + symbol_list[isin] + ' quantity must be multiple to ' + str(instruments[isin]['lotSize']))
                    warning_window('The ' + symbol_list[isin] + ' quantity must be multiple to ' + str(instruments[isin]['lotSize']) + '\n')
                    return
                emi = not_in_list_init(int(emi_number.get()), symbol_list[isin], datetime.utcnow())
                clOrdID = post_order(isin, emi, "Sell", price, qw, 1, instruments[isin]['rank'])
        else:
            info_display("Adding a new order: some field is empty!")
    def callback_buy_limit():
        global last_order; global orders
        if quantity.get() and price_bid.get():
            try:
                int(quantity.get()); float(price_ask.get())
                t = 'yes'
            except:
                info_display("Adding a new order: fields must be numbers!")
                t = 'no'
            if t == 'yes' and int(quantity.get()) != 0:
                qw = abs(int(quantity.get()))
                price = round_price(isin, float(price_bid.get()), qw)
                if qw - int(qw / instruments[isin]['lotSize']) * instruments[isin]['lotSize'] != 0:
                    info_display('The ' + symbol_list[isin] + ' quantity must be multiple to ' + str(instruments[isin]['lotSize']))
                    warning_window('The ' + symbol_list[isin] + ' quantity must be multiple to ' + str(instruments[isin]['lotSize']) + '\n')
                    return
                emi = not_in_list_init(int(emi_number.get()), symbol_list[isin], datetime.utcnow())
                clOrdID = post_order(isin, emi, "Buy", price, qw, 1, instruments[isin]['rank'])
        else:
            info_display("Adding a new order: some field is empty!")
    if book_window_trigger == 'off' and f9 == 'OFF':        
        book_window_trigger = 'on'
        book_window = Toplevel(root, padx=10, pady=20)
        book_window.title("Place order " + symbol_list[isin])
        book_window.protocol("WM_DELETE_WINDOW", on_closing)
        book_window.attributes('-topmost', 1)        
        frame_quantity = Frame(book_window)
        frame_market_ask = Frame(book_window)
        frame_market_bid = Frame(book_window)
        frame_robots = Frame(book_window)
        sell_market = Button(book_window, text="Sell Market", command=callback_sell_limit)
        buy_market = Button(book_window, text="Buy Market", command=callback_buy_limit)
        sell_limit = Button(book_window, text="Sell Limit", command=callback_sell_limit)
        buy_limit = Button(book_window, text="Buy Limit", command=callback_buy_limit)
        quantity = StringVar()
        price_ask = StringVar()
        price_bid = StringVar()
        entry_price_ask = Entry(frame_market_ask, width=10, bg='white', textvariable=price_ask)	#, textvariable = symb
        entry_price_bid = Entry(frame_market_bid, width=10, bg='white', textvariable=price_bid)
        entry_price_ask.insert(0, ticker[isin]['ask'])
        entry_price_bid.insert(0, ticker[isin]['bid'])      
        entry_quantity = Entry(frame_quantity, width=6, bg='white', textvariable=quantity)
        label_ask = Label(frame_market_ask, text = "Price:")
        label_bid = Label(frame_market_bid, text = "Price:")
        label_quantity = Label(frame_quantity, text = "Quantity:")
        sell_market.grid(row=0, column=0, sticky="N"+"S"+"W"+"E", pady=10)
        buy_market.grid(row=0, column=1, sticky="N"+"S"+"W"+"E", pady=10)
        label_robots = Label(frame_robots, text = "EMI:")
        emi_number = StringVar()
        emi_number.set(reserved_emi[symbol_list[isin]])
        options = [reserved_emi[symbol_list[isin]]]
        for emi in robots:
            if robots[emi]['ISIN'] == symbol_list[isin] and robots[emi]['STATUS'] != 'NOT IN LIST':
                options.append(robots[emi]['EMI'])
                #print(robots[emi]['ISIN'], isin)
        option_robots = OptionMenu(frame_robots, emi_number, *options) 
        frame_robots.grid(row=1, column=0, sticky="N"+"S"+"W"+"E", columnspan = 2, padx=10, pady=0)
        label_robots.pack(side=LEFT)
        option_robots.pack()
        frame_quantity.grid(row=2, column=0, sticky="N"+"S"+"W"+"E", columnspan = 2, padx=10, pady=10)
        label_quantity.pack(side=LEFT)
        entry_quantity.pack()
        frame_market_ask.grid(row=3, column=0, sticky="N"+"S"+"W"+"E")
        frame_market_bid.grid(row=3, column=1, sticky="N"+"S"+"W"+"E")
        label_ask.pack(side=LEFT)
        entry_price_ask.pack()
        label_bid.pack(side=LEFT)
        entry_price_bid.pack()
        sell_limit.grid(row=4, column=0, sticky="N"+"S"+"W"+"E", pady=10)
        buy_limit.grid(row=4, column=1, sticky="N"+"S"+"W"+"E", pady=10)
        refresh_var = book_window.after_idle(refresh)

#----------------Event handler Orders-------------------------
def handler_order(event, order_number):
    global order_window_trigger; global orders_dict
    for clOrdID in orders_dict:
        #print(clOrdID, orders_dict[clOrdID]['num'])
        if orders_dict[clOrdID]['num'] == order_number:
            break
    #clOrdID = list(orders_dict.keys())[list(orders_dict.values()).index(dict({'num':order_number}))] 
    def on_closing():
        global order_window_trigger; order_window_trigger = 'off'
        order_window.destroy()
    def delete():
        try:
            orders[clOrdID]
        except:
            info_display("Order " + clOrdID + " does not exist!")
            logger.info("Order %s does not exist!", clOrdID)
            return
        if ws.logNumFatal == 0:
            numError = del_order(clOrdID)
        else:
            info_display("The operation failed. Websocket closed!")
        on_closing()
    def replace():
        for clOrdID in orders_dict:
            #print(clOrdID, orders_dict[clOrdID]['num'])
            if orders_dict[clOrdID]['num'] == order_number:
                break
        global orders
        try:
            orders[clOrdID]            
        except:
            info_display("Order " + clOrdID + " does not exist!")
            logger.info("Order %s does not exist!", clOrdID)
            return
        try:
            float(price_replace.get())
        except:
            info_display("Price must be numeric!") 
            return
        if ws.logNumFatal == 0:
            emi = orders[clOrdID]['emi']
            roundSide = orders[clOrdID]['leavesQty']
            if orders[clOrdID]['side'] == "Sell": roundSide = -roundSide
            price = round_price(symbol_list.index(orders[clOrdID]['symbol']), float(price_replace.get()), roundSide)
            if price == orders[clOrdID]['price']:
                info_display("Price is the same but must be different!")
                return
            if emi in robots and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                oldPrice = orders[clOrdID]['price']
                if orders[clOrdID]['side'] == "Sell":
                    if oldPrice in allRoboSells[emi]:
                        orders[clOrdID]['contracts'] = allRoboSells[emi][oldPrice]['contracts']
                        orders[clOrdID]['rank'] = allRoboSells[emi][oldPrice]['rank']
                else:
                    if oldPrice in allRoboBuys[emi]:
                        orders[clOrdID]['contracts'] = allRoboBuys[emi][oldPrice]['contracts']
                        orders[clOrdID]['rank'] = allRoboBuys[emi][oldPrice]['rank']
            clOrdID = put_order(clOrdID, price, orders[clOrdID]['leavesQty'], orders[clOrdID]['contracts'], orders[clOrdID]['rank'], '')
        else:
            info_display("The operation failed. Websocket closed!")
        on_closing()    
    if order_window_trigger == 'off':
        order_window_trigger = 'on'
        order_window = Toplevel(root, pady=10, padx=10) # , padx=5, pady=5
        cx = root.winfo_pointerx()
        cy = root.winfo_pointery()
        order_window.geometry('380x180+{}+{}'.format(cx-200, cy-50))
        order_window.title("Delete order ")
        order_window.protocol("WM_DELETE_WINDOW", on_closing)
        order_window.attributes('-topmost', 1)
        frame_up = Frame(order_window)
        frame_dn = Frame(order_window)
        label1 = Label(frame_up, justify=LEFT)
        label1['text'] = "number\t" + str(order_number) + "\nsymbol\t" + orders[clOrdID]['symbol'] + "\nside\t" + orders[clOrdID]['side'] +"\nclOrdID\t" + clOrdID + "\nprice\t" + str(orders[clOrdID]['price']) + "\nquantity\t" + str(orders[clOrdID]['leavesQty'])  
        label_price = Label(frame_dn)
        label_price['text'] = 'Price ' 
        label1.pack(side=LEFT)
        button = Button(frame_dn, text="Delete order", command=delete)
        price_replace = StringVar()
        entry_price = Entry(frame_dn, width=10, bg='white', textvariable=price_replace)
        button_replace = Button(frame_dn, text="Replace", command=replace)
        button.pack(side=RIGHT)
        label_price.pack(side=LEFT)
        entry_price.pack(side=LEFT)
        button_replace.pack(side=LEFT)
        frame_up.pack(side=TOP, fill=X)
        frame_dn.pack(side=TOP, fill=X)

#----------------Create main grid, main frames and TOP widget-------------------------
root.title('COIN DEALER')
root.geometry('1000x612+50+50')
root.protocol("WM_DELETE_WINDOW", on_closing)
frame_state = Frame()
label_trading = Label(frame_state, text='  TRADING: ')		#Create label for top row
label_f9 = Label(frame_state, text='OFF', fg = 'white')		#Create label for top row
label_state = Label(frame_state, text='  STATE: ')
label_online = Label(frame_state, fg = 'white')
#label_count = Label(frame_state, text='  (1) ')
label_time = Label()		#Create label for top row
frame_2row_1_2_3col = Frame()
frame_information = Frame(frame_2row_1_2_3col)		#Create frame for info text widget
frame_positions_sub = Frame(frame_2row_1_2_3col)		#Create frame for position table
def positions_width(event, canvas_id):    
    canvas_positions.itemconfig(canvas_id, width=event.width)
def positions_config(event):
    canvas_positions.configure(scrollregion=canvas_positions.bbox("all"))
canvas_positions = Canvas(frame_positions_sub, height=50, highlightthickness=0)
v_positions=Scrollbar(frame_positions_sub,orient=VERTICAL)
v_positions.pack(side=RIGHT,fill=Y)
v_positions.config(command=canvas_positions.yview)
canvas_positions.config(yscrollcommand=v_positions.set)
canvas_positions.pack(fill="both", expand=True)
frame_positions = Frame(canvas_positions)				#Create frame for position table
positions_id = canvas_positions.create_window((0,0), window=frame_positions, anchor="nw")
canvas_positions.bind('<Configure>',  lambda event, a = positions_id: positions_width(event, a))
frame_positions.bind("<Configure>", positions_config)
frame_3row_1col = Frame()		#Create frame for trades text widget
#frame_3row_2col = Frame()		#Create frame for the window near order book
frame_3row_3col = Frame(padx=0, pady=2)		#Create frame for order book
frame_3row_4col = Frame()		#Create frame for orders and funding text widget
frame_4row_1_2_3col = Frame()		#Create frame for the account table
frame_5row_1_2_3_4col = Frame()		
def robots_width(event, canvas_id):    
    canvas_robots.itemconfig(canvas_id, width=event.width)
def robots_config(event):
    canvas_robots.configure(scrollregion=canvas_robots.bbox("all"))
canvas_robots = Canvas(frame_5row_1_2_3_4col, height=128, highlightthickness=0)
v_robots=Scrollbar(frame_5row_1_2_3_4col,orient=VERTICAL)
v_robots.pack(side=RIGHT,fill=Y)
v_robots.config(command=canvas_robots.yview)
canvas_robots.config(yscrollcommand=v_robots.set)
canvas_robots.pack(fill="both", expand=True)
frame_robots = Frame(canvas_robots)				#Create frame for the robots table
robots_id = canvas_robots.create_window((0,0), window=frame_robots, anchor="nw")
canvas_robots.bind('<Configure>',  lambda event, a = robots_id: robots_width(event, a))
frame_robots.bind("<Configure>", robots_config)
frame_state.grid(row=0, column=0, sticky="W")
label_state.pack(side=LEFT)
label_online.pack(side=LEFT)
label_trading.pack(side=LEFT)
label_f9.pack(side=LEFT)
#label_count.pack(side=LEFT)
#label_trading.grid(row=0, column=0, sticky="W", columnspan=2)		#Place label into grid
#label_f9.grid(row=0, column=0, sticky="W", columnspan=2)		#Place label into grid
label_time.grid(row=0, column=1, sticky="E", columnspan=2)		#Place label into grid
frame_2row_1_2_3col.grid(row=1, column=0, sticky="N"+"S"+"W"+"E", columnspan=3)		#Place frame into grid
frame_information.grid(row=0, column=0, sticky="N"+"S"+"W"+"E")
frame_positions_sub.grid(row=0, column=1, sticky="N"+"S"+"W"+"E", padx=1, pady=0)		#Place frame into grid  #!!!!!!!!!!!!!!!!!!!!!!!!
frame_3row_1col.grid(row=2, column=0, sticky="N"+"S"+"W"+"E")		#Place frame into grid
#frame_3row_2col.grid(row=2, column=1, sticky="N"+"S"+"W"+"E")		#Place frame into grid
frame_3row_3col.grid(row=2, column=1, sticky="N"+"S"+"W"+"E")		#Place frame into grid
frame_3row_4col.grid(row=2, column=2, sticky="N"+"S"+"W"+"E", rowspan=2)		#Place frame into grid
frame_4row_1_2_3col.grid(row=3, column=0, sticky="S"+"W"+"E", columnspan=2, padx=0, pady=0)		#Place frame into grid
frame_5row_1_2_3_4col.grid(row=4, column=0, sticky="N"+"S"+"W"+"E", columnspan=3)		#Place frame into grid
root.grid_columnconfigure(0, weight=1)		#Grid alignment
root.grid_columnconfigure(1, weight=1)		#Grid alignment
root.grid_columnconfigure(2, weight=1)		#Grid alignment
#root.grid_columnconfigure(3, weight=1)		#Grid alignment
frame_2row_1_2_3col.grid_columnconfigure(0, weight=1)		#Grid alignment
frame_2row_1_2_3col.grid_columnconfigure(1, weight=1)		#Grid alignment

#---------------------Create Information widget-------------------------
scroll_info = Scrollbar(frame_information)		#Create scroll widget for info
text_info = Text(frame_information, height=6, width=40, bg=bg_color, highlightthickness=0)		#Create text widget for information
scroll_info.config(command=text_info.yview)
text_info.config(yscrollcommand=scroll_info.set)
scroll_info.pack(side=RIGHT, fill=Y)
text_info.pack(side=RIGHT, fill=BOTH, expand = YES)

#---------------------Greate Positions widget--------------------------------
label_pos = [[Label(frame_positions, text=i) for y in range(num_pos)] for i in name_pos]		#Create array of labels for position table
for y in range(num_pos):		#Fill array of position table
    for i in range(len(name_pos)):
        if y == 0:
            label_pos[i][y].grid(row=y, column=i, sticky="N"+"S"+"W"+"E", padx=1, pady=0)
        else:
            label_pos[i][y].grid(row=y, column=i,  sticky="N"+"S"+"W"+"E", padx=1, pady=0); label_pos[i][y]['text'] = ""; label_pos[i][y]['bg'] = bg_color
            label_pos[i][y].bind('<Button-1>', lambda event, yy = y: handler_pos(event, yy))
        label_pos[i][y].grid(row=y, column=i)
        frame_positions.grid_columnconfigure(i, weight=1)

#---------------------Create Trades widget--------------------------------
scroll_trades = Scrollbar(frame_3row_1col)		#Create scroll widget for trades
text_trades = Text(frame_3row_1col, height=21, width=38, bg=bg_color, highlightthickness=0)		#Create text widget for trades
scroll_trades.config(command=text_trades.yview)
text_trades.config(yscrollcommand=scroll_trades.set)
scroll_trades.pack(side=RIGHT, fill=Y)
text_trades.pack(side=RIGHT, fill=BOTH, expand=YES)

#---------------------Create Orderbook table--------------------------------
label_book = [[Label(frame_3row_3col, text=i, pady=0) for y in range(num_book)] for i in name_book]		#Create array of labels for position table
for y in range(num_book):		#Fill array of position table
    for i in range(len(name_book)):
        if y == 0:
            label_book[i][y].grid(row=y, column=i, sticky="N"+"S"+"W"+"E", padx=1)
        else:
            if i == 0 or i == 2:
                label_book[i][y]['fg'] = bg_color
            label_book[i][y].grid(row=y, column=i,  sticky="N"+"S"+"W"+"E", padx=1);
            label_book[i][y]['text'] = ""; label_book[i][y]['bg'] = bg_color; label_book[i][y]['height'] = 1
            label_book[i][y].bind('<Button-1>', lambda event, yy = y: handler_book(event, yy))
        label_book[i][y].grid(row=y, column=i)
        frame_3row_3col.grid_columnconfigure(i, weight=1)

#---------------------Create Orders widget--------------------------------
frame_orders = Frame(frame_3row_4col)		#Create sub-frame for orders
frame_orders.pack(fill=BOTH)
scroll_orders = Scrollbar(frame_orders)		#Create scroll widget for orders
text_orders = Text(frame_orders, height=12, width=52, bg=bg_color, cursor='arrow', highlightthickness=0)		#Create text widget for orders
scroll_orders.config(command=text_orders.yview)
text_orders.config(yscrollcommand=scroll_orders.set)
scroll_orders.pack(side=RIGHT, fill=Y)
text_orders.pack(side=RIGHT, fill=BOTH, expand=YES)

#---------------------Create Funding widget--------------------------------
frame_funding = Frame(frame_3row_4col)		#Create sub-frame for funding
frame_funding.pack(fill=BOTH)
scroll_funding = Scrollbar(frame_funding)		#Create scroll widget for funding
text_funding = Text(frame_funding, height=12, width=52, bg=bg_color, highlightthickness=0)		#Create text widget for funding
scroll_funding.config(command=text_funding.yview)
text_funding.config(yscrollcommand=scroll_funding.set)
scroll_funding.pack(side=RIGHT, fill=Y)
text_funding.pack(side=RIGHT, fill=BOTH, expand=YES)

#---------------------Create Account table--------------------------------
label_account = [[Label(frame_4row_1_2_3col, text=i) for y in range(num_acc)] for i in name_acc]		#Array of account labels
for y in range(num_acc):		#Fill account labels
    for i in range(len(name_acc)):
        if y == 0:
            label_account[i][y].grid(row=y, column=i, sticky="N"+"S"+"W"+"E", padx=1, pady=0)
        else:
            label_account[i][y].grid(row=y, column=i,  sticky="N"+"S"+"W"+"E", padx=1, pady=0); label_account[i][y]['text'] = ""; label_account[i][y]['bg'] = bg_color
        label_account[i][y].grid(row=y, column=i)
        frame_4row_1_2_3col.grid_columnconfigure(i, weight=1)

#---------------------Create Robots table--------------------------------
label_robots = [[Label(frame_robots, text=i, pady=0) for y in range(num_robots)] for i in name_robots]		#Array of robots labels
for y in range(num_robots):		#Fill account labels
    for i in range(len(name_robots)):
        if y > 0:
            label_robots[i][y]['text'] = ""
            label_robots[i][y].bind('<Button-1>', lambda event, yy = y: handler_robots(event, yy))
        label_robots[i][y].grid(row=y, column=i, sticky="N"+"S"+"W"+"E")
        frame_robots.grid_columnconfigure(i, weight=1)

#---------------------Display Information--------------------------------
def info_display(message):
    t = datetime.utcnow()
    #text_info.insert('1.0', time.strftime("%X") + ' ' + message +'\n')
    text_info.insert('1.0', noll(str(t.hour), 2) + ':' + noll(str(t.minute), 2) + ':' + noll(str(t.second), 2) + '.' + noll(str(t.microsecond / 1000), 3) + ' ' + message +'\n')
    global info_display_counter; info_display_counter += 1
    if info_display_counter > 40:
        text_info.delete('41.0', END)

#---------------------Display Trades--------------------------------
def trades_display(m):
    t = str(m['TTIME'])
    time = t[2:4] + t[5:7] + t[8:10] +' ' + t[11:19]
    text_trades.insert('1.0',time  + '  ' + m['TICKER'] + '  ' + str(float(m['TRADE_PRICE'])) + gap(len(str(float(m['TRADE_PRICE']))), 9) + "(" + str(m['EMI']) + ') ' + str(m['AMOUNT']) + '\n')
    if m['DIR'] == 1:
        name = 'red' + str(i)
        text_trades.tag_add(name, "1.0", "1.50")    
        text_trades.tag_config(name, foreground="red")
    elif m['DIR'] == 0:
        name = 'green' + str(i)
        text_trades.tag_add(name, "1.0", "1.50")    
        text_trades.tag_config(name, foreground="forest green") #royalBlue3  seaGreen3 forest green
    global trades_display_counter; trades_display_counter += 1
    if trades_display_counter > 150:
        text_trades.delete('151.0', END)

#---------------------Display Funding--------------------------------
def funding_display(m):
    space = ''
    if m['KOMISS'] > 0:
        space = ' '
    t = str(m['TTIME'])
    time = t[2:4] + t[5:7] + t[8:10] +' ' + t[11:16]
    text_funding.insert('1.0',time  + '  ' + m['TICKER'] + '  ' + str(float(m['PRICE'])) + gap(len(str(float(m['PRICE']))), 9) + space + '{:.8f}'.format(m['KOMISS']) + '  (' + str(m['EMI']) + ')' + str(m['AMOUNT']) + '\n')
    '''if m['side'] == 'Sell':
        name = 'red' + str(i)
        text_trades.tag_add(name, "1.0", "1.50")    
        text_trades.tag_config(name, foreground="red")
    elif m['side'] == 'Buy':
        name = 'green' + str(i)
        text_trades.tag_add(name, "1.0", "1.50")    
        text_trades.tag_config(name, foreground="forest green") #royalBlue3  seaGreen3 forest green'''
    global funding_display_counter; funding_display_counter += 1
    if funding_display_counter > 120:
        text_funding.delete('121.0', END)

#---------------------Display Orders--------------------------------
def orders_display(clOrdID):
    global orders_dict_value
    if clOrdID in orders_dict:
        myNum = 0
        for i, myClOrd in enumerate(orders_dict):
            if myClOrd == clOrdID:
                myNum = i
        ordDictPos = abs(myNum + 1 - len(orders_dict)) + 1
        text_orders.delete(str(ordDictPos)+'.0', str(ordDictPos + 1)+'.0')
        robots[orders_dict[clOrdID]['emi']]['unrlzd'] -= orders_dict[clOrdID]['unrlzd']
        del orders_dict[clOrdID]
    if clOrdID in orders:
        emi = orders[clOrdID]['emi']
        if orders[clOrdID]['side'] == 'Sell':
            calc = calculate(robots[emi]['ISIN'], orders[clOrdID]['price'], -orders[clOrdID]['leavesQty'], 0.0001, 1)
            orders_dict[clOrdID] = {'num':orders_dict_value, 'emi':emi, 'unrlzd':calc['sumreal']+calc['comiss']}
        else:
            calc = calculate(robots[emi]['ISIN'], orders[clOrdID]['price'], orders[clOrdID]['leavesQty'], 0.0001, 1)
            orders_dict[clOrdID] = {'num':orders_dict_value, 'emi':emi, 'unrlzd':calc['sumreal']+calc['comiss']}
        robots[emi]['unrlzd'] += orders_dict[clOrdID]['unrlzd']
        t = str(orders[clOrdID]['transactTime'])
        time = t[2:4] + t[5:7] + t[8:10] + ' ' + t[11:23]
        text_insert = time + '  ' + orders[clOrdID]['symbol'] + '  ' + str(float(orders[clOrdID]['price'])) + gap(len(str(float(orders[clOrdID]['price']))), 8) + ' (' + str(orders[clOrdID]['emi']) + ') ' + str(orders[clOrdID]['leavesQty']) + '\n'
        text_orders.insert('1.0', text_insert)
        found_name = 0
        if orders[clOrdID]['side'] == 'Sell':
            name = 'red' + str(orders_dict_value)
#in order to prevent memory leak we use this construction for tag_bind, that activates only once for every string by number and color
            for tag in text_orders.tag_names():
                if tag == name: found_name = 1
            if found_name == 0:
                text_orders.tag_bind(name, "<Button-1>", lambda event, y = orders_dict_value: handler_order(event, y))
            text_orders.tag_add(name, "1.0", "1.50")    
            text_orders.tag_config(name, foreground="red")                
        elif orders[clOrdID]['side'] == 'Buy':
            name = 'green' + str(orders_dict_value)
#in order to prevent memory leak we use this construction for tag_bind, that activates only once for every string by number and color
            for tag in text_orders.tag_names():
                if tag == name: found_name = 1
            if found_name == 0:
                text_orders.tag_bind(name, "<Button-1>", lambda event, y = orders_dict_value: handler_order(event, y))                       
            text_orders.tag_add(name, "1.0", "1.50")          
            text_orders.tag_config(name, foreground="forest green") #royalBlue3  seaGreen3
        orders_dict_value += 1
    #text_orders.delete('1.0', END)

logger = setup_logger()

#----------------Load init.ini/ Initialize variables-------------------------
tm = datetime.utcnow()
openFile = open('init.ini')
for ii, line in enumerate(openFile):
    val = line.replace('\n','')
    symbol_list.append(val)
    ticker.append({'isin': val, 'bid': 0, 'ask': 0, 'bidSize': 0, 'askSize': 0, 'open_bid': 0, 'open_ask': 0, 'hi': 0, 'lo': 0, 'time': tm})
openFile.close()
positions = [{y: 0 for y in name_pos} for i in range(ii+1)]
instruments = [{y: 0 for y in name_instruments} for i in range(ii+1)]
accounts = {y: -1 for y in name_acc}

#----------------Initialize mysql connection-------------------------
try:
    connect_mysql = pymysql.connect('localhost', 'root', '12345', 'TRD', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
    cursor_mysql = connect_mysql.cursor()
except:
    logger.error("No connection to mySQL database")
    exit(1)

#----------------Initialize websocket-------------------------
print (sys.version)
ws = None
connect_time = datetime.utcnow()
connect_count = 0
import gc
def connection():
    global ws; global ticker    
    global connect_mysql; global accounts; global instruments; global orders; global connect_time; global connect_count
    if ws:
        #if ws.logNumFatal == 0:
        ws.exit()
        ws.del_socket()
    with open('login_details.txt', 'r') as f:
        login_details = f.read().split()
    ws = BitMEXWebsocket(endpoint='https://testnet.bitmex.com/api/v1/', symbol=symbol_list, api_key=login_details[0], api_secret=login_details[1], info_display=info_display, recovery=recovery) 
    if ws.logNumFatal == 0:
        connect_count += 1
        connect_time = datetime.utcnow()
        handler_pos(1, isin+1)
        accounts['ACCOUNT'] = ws.get_funds()['account']
        rounding(ws.get_instrument(instruments))
        global last_order
        clear_params()
        sumOfOrderSellAmount = dict()
        sumOfOrderBuyAmount = dict()
        if 0 == 0:
#----------------Load robots from SQL-------------------
            load_robots(symbol_list, accounts['ACCOUNT'])
#------------------------Fills 'allRoboBuys', 'allRoboSells' and 'visavi' with initial data-------------------------the first thing in the loading process----------
            for emi in robots:
                if emi not in sumOfOrderSellAmount:
                    sumOfOrderSellAmount[emi] = 0
                    sumOfOrderBuyAmount[emi] = 0

                visavi[emi] = {'price':0, 'amount':0, 'contracts':0, 'clOrdID':'', 'side':''}
                if robots[emi]['STATUS'] != 'NOT IN LIST' and robots[emi]['TIP'] == 1 and robots[emi]['TIMEFR'] != 0:
                    try:
                        symb_num = robots[emi]['SYMB_NUM']
                        #print('#1---------------rank-------------', instruments[symb_num]['rank'])
                        myRank = 999999999
                        for fileNow in pathlib.Path(str(emi)+'/').iterdir():
                            with open(str(fileNow), 'r') as f:
                                for line in f:
                                    #print(fileNow.name, line)
                                    s = line.replace('\n','').split(';')
                                    price = float(s[0])
                                    amount = int(s[1])
                                    contracts = int(s[2])
                                    lot = int(s[3])
                                    rank = int(s[4])
                                    side = s[5]
                                    #print(fileNow.name+' price='+str(price)+' amount='+str(amount)+' contracts='+str(contracts)+' lot='+str(lot)+' rank='+str(rank)+' side='+side)
                                    if side == "Buy":
                                        robots[emi]['sumOfBuyAmount'] += amount
                                        robots[emi]['sumOfBuyContracts'] += contracts
                                        allRoboBuys[emi][price] = {'clOrdID':fileNow.name, 'amount':amount, 'contracts':contracts, 'lot':lot, 'rank':rank}
                                    else:
                                        robots[emi]['sumOfSellAmount'] += amount
                                        robots[emi]['sumOfSellContracts'] += contracts
                                        allRoboSells[emi][price] = {'clOrdID':fileNow.name, 'amount':amount, 'contracts':contracts, 'lot':lot, 'rank':rank}
                                    if rank < myRank: myRank = rank
                                    #print(rank, myRank)
                        if myRank != 999999999:
                            instruments[symb_num]['rank'] = myRank
#print('#2---------------rank-------------', instruments[symb_num]['rank'])
                    except Exception as e:
                        logger.error("Error while filling initial data. " + str(e))
                        exit(1)
                    from pathlib import Path
                    if Path('visavi'+str(emi)).is_file():
                        with open('visavi'+str(emi), 'r') as f:
                            for line in f:
                                s = line.replace('\n','').split(';')
                                visavi[emi]['price'] = float(s[0])
                                visavi[emi]['amount'] = int(s[1])
                                visavi[emi]['contracts'] = int(s[2])
                                visavi[emi]['clOrdID'] = s[3]
                                visavi[emi]['side'] = s[4]

#----------------Load trading history (if any)-------------------the second thing in the loading process----------
        start = 0
        history = ['any']
        t = None
        with open('history.ini', 'r') as f:
            try:
                start = int(f.readline()) - 100
                if start < 0: start = 0
            except:
                logger.error("No number or date in history.ini")        
        while history:
            history = ws.trading_history(500, start)
            if history != None and history != []:
                t = datetime.strptime(history[len(history)-1]['transactTime'][0:19], '%Y-%m-%dT%H:%M:%S')
                for row in history:
                    data = read_database(row['execID'], -1)
                    #if data: print(len(data), data)
                    if not data:
                        transaction(row)
                start += len(history)
        if ws.logNumFatal == 0:
            with open('history.ini', 'w') as f:
                f.write(str(start) + '\n' + str(t))

#----------------Load Orders (if any)-------------------the third thing in the loading process----------
        myOrders = ws.open_orders()
        orders = OrderedDict()
        text_orders.delete('1.0', END)
        errMissing = 0
        for val in myOrders:
            if val['leavesQty'] != 0:
                clOrdID = val['clOrdID']
                emi = reserved_emi[val['symbol']]
                if emi not in robots:
                    sumOfOrderSellAmount[emi] = 0
                    sumOfOrderBuyAmount[emi] = 0
                    emi = not_in_list_init(emi, symbol_list[isin], datetime.strptime(val['transactTime'][0:19], '%Y-%m-%dT%H:%M:%S'))           
                if val['clOrdID'] == '':							#The order was placed from the Bitmex platform
                    last_order += 1
                    clOrdID = 'bitmex_'+str(last_order)+'.'+str(emi)
                    info_display("Outside placement: price=" + str(val['price']) + " side=" + val['side'] + ". Assigned clOrdID=" + clOrdID)
                else:
                    s = clOrdID.split('.')
                    emi = int(s[1])
                orders[clOrdID] = {}
                orders[clOrdID]['emi'] = emi
                orders[clOrdID]['leavesQty'] = val['leavesQty']
                orders[clOrdID]['transactTime'] = val['transactTime']
                orders[clOrdID]['price'] = val['price']
                orders[clOrdID]['symbol'] = val['symbol']
                orders[clOrdID]['side'] = val['side']
                orders[clOrdID]['orderID'] = val['orderID']
                orders[clOrdID]['oldPrice'] = 0
                orders[clOrdID]['contracts'] = 0
                orders[clOrdID]['rank'] = 0
                orders_display(clOrdID)
                if val['side'] == 'Buy':
                    sumOfOrderBuyAmount[emi] += val['leavesQty']
                elif val['side'] == 'Sell':
                    sumOfOrderSellAmount[emi] += val['leavesQty']
                else:
                    print('Unknown order side')
                    exit(0)
                if val['side'] == 'Sell':
                    if val['price'] in allRoboSells[emi]:
                        orders[clOrdID]['contracts'] = allRoboSells[emi][val['price']]['contracts']
                        orders[clOrdID]['rank'] =  allRoboSells[emi][val['price']]['rank']
                    else:
                        if robots[emi]['TIP'] == 1:
                            logger.info('The corresponding allRoboSells not found. emi='+str(emi)+' clOrdID='+clOrdID+' price='+str(val['price'])+' amount='+str(val['leavesQty']))
                            logger.info('    Check(create) file '+clOrdID+' in /'+str(emi)+' directory. File contents: price;amount;contracts;lot;rank;side')
                            logger.info('    price='+str(val['price'])+' amount='+str(val['leavesQty'])+' rank='+str(instruments[symb_num]['rank'])+' side='+val['side'])
                            logger.info('    Number of contracts and lot must be calculated manually')
                            errMissing += 1
                else:
                    if val['price'] in allRoboBuys[emi]:
                        orders[clOrdID]['contracts'] = allRoboBuys[emi][val['price']]['contracts']
                        orders[clOrdID]['rank'] =  allRoboBuys[emi][val['price']]['rank']
                    else:
                        if robots[emi]['TIP'] == 1:
                            logger.info('The corresponding allRoboBuys not found. emi='+str(emi)+' clOrdID='+clOrdID+' price='+str(val['price'])+' amount='+str(val['leavesQty']))
                            logger.info('    Check(create) file '+clOrdID+' in /'+str(emi)+' directory. File contents: price;amount;contracts;lot;rank;side')
                            logger.info('    price='+str(val['price'])+' amount='+str(val['leavesQty'])+' rank='+str(instruments[symb_num]['rank'])+' side='+val['side'])
                            logger.info('    Number of contracts and lot must be calculated manually')
                            errMissing += 1
        if errMissing != 0:
            exit(0)
        errMissing = 0
        for emi in robots:
            if robots[emi]['TIP'] == 1:
                logger.info('emi='+str(emi)+': POS = '+str(robots[emi]['POS'])+', sumOfBuyAmount = '+str(robots[emi]['sumOfBuyAmount'])+' / '+str(sumOfOrderBuyAmount[emi])+', sumOfSellAmount = '+str(robots[emi]['sumOfSellAmount'])+' / '+str(sumOfOrderSellAmount[emi]))
                if robots[emi]['sumOfBuyAmount'] != sumOfOrderBuyAmount[emi]:
                    logger.info('Consistency violated for '+str(emi)+': sumOfBuyAmount <> sumOfOrderBuyAmount')
                    errMissing += 1
                if robots[emi]['sumOfSellAmount'] != sumOfOrderSellAmount[emi]:
                    logger.info('Consistency violated for '+str(emi)+': sumOfSellAmount <> sumOfOrderSellAmount')
                    errMissing += 1
                for price in allRoboSells[emi]:
                    if allRoboSells[emi][price]['clOrdID'] not in orders:
                        logger.info('The corresponding sell order not found. emi='+str(emi)+' clOrdID='+allRoboSells[emi][price]['clOrdID']+' price='+str(price)+' amount='+str(allRoboSells[emi][price]['amount']))
                        logger.info('    Delete '+allRoboSells[emi][price]['clOrdID']+' file from /'+str(emi)+' directory. Pay attention to balaces and number of contracts.')
                        logger.info('    Example: POS + sumOfBuyAmount - sumOfSellAmount = 0')
                        errMissing += 1
                for price in allRoboBuys[emi]:
                    if allRoboBuys[emi][price]['clOrdID'] not in orders:
                        logger.info('The corresponding buy order not found. emi='+str(emi)+' clOrdID='+allRoboBuys[emi][price]['clOrdID']+' price='+str(price)+' amount='+str(allRoboBuys[emi][price]['amount']))
                        logger.info('    Delete '+allRoboBuys[emi][price]['clOrdID']+' file from /'+str(emi)+' directory. Pay attention to balaces and number of contracts.')
                        logger.info('    Example: POS + sumOfBuyAmount - sumOfSellAmount = 0')
                        errMissing += 1
        if errMissing != 0:
            exit(0)
        initial_mysql(accounts['ACCOUNT'])
        initial_display(accounts['ACCOUNT'])
        ticker = ws.get_ticker(ticker)		#first prices and volumes
        instruments = ws.get_instrument(instruments)	#state, fundingRate.....
        for emi in robots:
            if robots[emi]['STATUS'] == 'WORK':
                calculate_max(emi, ticker[robots[emi]['SYMB_NUM']]['bid'])
        utc = datetime.utcnow()
        for i in range(len(symbol_list)):
            #print('------iiii----', i, ticker[i]['bid'])
            ticker[i]['open_ask'] = ticker[i]['ask']
            ticker[i]['open_bid'] = ticker[i]['bid']
            ticker[i]['hi'] = ticker[i]['ask']
            ticker[i]['lo'] = ticker[i]['bid']
            ticker[i]['fundingRate'] = instruments[i]['fundingRate']
            #for ii, emi in enumerate(robots):
            for emi in robots:
                if robots[emi]['TIMEFR'] != 0:
                    frameNow = robots[emi]['FRAME']                    
                    if i == framing[frameNow]['isin']:
                        framing[frameNow]['open'] = (ticker[i]['bid'] + ticker[i]['ask']) / 2
                        if len(frames[frameNow]) == 0:
                            date = int(str(utc.year - 2000) + noll(str(utc.month), 2) + noll(str(utc.day), 2))
                            frames[frameNow].append({'date':date, 'time': utc, 'bid': ticker[i]['bid'], 'lo': ticker[i]['bid'], 'ask': ticker[i]['ask'], 'hi': ticker[i]['ask'], 'funding': ticker[i]['fundingRate']})
refresh_sec = tm.second
refresh_minute = tm.minute
refresh_hour = tm.hour
message_time = datetime.utcnow()
connection()
message_point = ws.message_counter
message2000 = ''
messageStopped = ''

#----------------Main loop refresh-------------------------
def refresh():
    global refresh_sec; global refresh_hour; global orders; global ticker; global positions; global instruments
    global message_point; global message_time; global connect_time; global refresh_minute; global f9
    utc = datetime.utcnow()
    '''if ws.logNumFatal > 0 and ws.logNumFatal < 1004:# and utc > connect_time + timedelta(seconds=3):
        if ws.logNumFatal == 2000:#???????????????????????????????????????????????
            info_display("Insufficient available balance! Trading stopped")
            f9 = 'OFF'
        else:
            print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!', ws.logNumFatal)
            exit(0)
            connection()'''
    if ws.logNumFatal > 2000:
        global message2000
        if message2000 == '':
            message2000 = 'Fatal error='+str(ws.logNumFatal)+'. Terminal is frozen'
            info_display(message2000)
        sleep(1)
    elif ws.logNumFatal > 1000 or ws.timeoutOccurred != '':#reload terminal
        connection()
    else:
        if ws.logNumFatal > 0 and ws.logNumFatal <= 10:
            global messageStopped
            if messageStopped == '':
                messageStopped = 'Error='+str(ws.logNumFatal)+'. Trading stopped'
                info_display(messageStopped)
                if ws.logNumFatal == 2: info_display('Insufficient available balance!')
            f9 = 'OFF'

        ticker = ws.get_ticker(ticker)		#first prices and volumes
        instruments = ws.get_instrument(instruments)	#state, fundingRate.....

#----------------min/max price and save data in file-------------------------
        '''for i in range(len(symbol_list)):            
            if utc.minute != ticker[i]['time'].minute and instruments[i]['state'] == 'Open':
                if utc.hour == ticker[i]['time'].hour:
                    ticker[i]['fundingRate'] = instruments[i]['fundingRate']
                save_minute_data(i, utc, ticker[i]['time'])
                ticker[i]['hi'] = ticker[i]['ask']
                ticker[i]['lo'] = ticker[i]['bid']
                ticker[i]['open_ask'] = ticker[i]['ask']
                ticker[i]['open_bid'] = ticker[i]['bid']
                ticker[i]['time'] = utc
            else:
                if ticker[i]['ask'] > ticker[i]['hi']:
                    ticker[i]['hi'] = ticker[i]['ask']
                if ticker[i]['bid'] < ticker[i]['lo']:
                    ticker[i]['lo'] = ticker[i]['bid']'''

#----------------Robots timeframes-------------------------# - timedelta(seconds=robots[emi]['TIMEFR'])

#----------------Get execution-------------------------  
        while ws.get_exec():
            transaction(ws.get_exec()[0], 'execution')
            del ws.data['execution'][0]

#----------------Update information every second-------------------------
        if utc.second != refresh_sec:
        #if not True:
            #print('len(orders)', len(orders))
            refresh_sec = utc.second
            if utc.hour != refresh_hour:#only to embolden MySQL in order to avoid 'MySQL server has gone away' error
                cursor_mysql.execute("select count(*) from TRD.robots")
                data = cursor_mysql.fetchall()
                refresh_hour = utc.hour
                logger.info("Emboldening MySQL")

            label_time['text'] = '('+str(connect_count)+')  '+time.ctime()
            label_f9['text'] = str(f9)
            if f9 == 'ON':
                label_f9.config(bg='green3')
            else:
                label_f9.config(bg='orange red')
            if ws.logNumFatal == 0:
                if utc > message_time + timedelta(seconds=10):
                    if ws.message_counter == message_point:
                        info_display("No data within 10 sec")
                        label_online['text'] = 'NO DATA'; label_online.config(bg='yellow2')
                        ws.urgent_announcement()
                        #if ws.logNumFatal == 1004:
                        #    ws.urgent_announcement()
                    message_time = utc
                    message_point = ws.message_counter
            if ws.message_counter != message_point:
                label_online['text'] = 'ONLINE'; label_online.config(bg='green3')
            if ws.logNumFatal != 0:
                label_online['text'] = 'error ' + str(ws.logNumFatal); label_online.config(bg='orange red')            
            if utc > ws.time_response + timedelta(seconds=3):
                retry_orders(orders)

#----------------Get funds---------------------------------
            funds = ws.get_funds();
            #print('----funds----', funds)
            accounts['MARGINBAL'] = float(funds['marginBalance']) / XBt_TO_XBT
            accounts['AVAILABLE'] = float(funds['availableMargin']) / XBt_TO_XBT
            accounts['LEVERAGE'] = funds['marginLeverage']
            accountSumreal = accounts['PNL']

#----------------Display positions-------------------------
            positions = ws.get_position(positions)
            for num, p in enumerate(symbol_list):
                positions[num]['STATE'] = instruments[num]['state']
                positions[num]['VOL24h'] = instruments[num]['volume24h']
                positions[num]['FUND'] = round(instruments[num]['fundingRate'] * 100, 6)
                label_pos[0][num+1]['text'] = p+'.'+str(instruments[num]['rank'])
                label_pos[1][num+1]['text'] = positions[num]['POS'] if positions[num]['POS'] is not None else 0
                label_pos[2][num+1]['text'] = round(positions[num]['ENTRY'], price_rounding[num]) if positions[num]['ENTRY'] is not None else 0
                label_pos[3][num+1]['text'] = positions[num]['PNL'] if positions[num]['PNL'] is not None else 0
                label_pos[4][num+1]['text'] = str(positions[num]['MCALL']).replace('100000000', 'inf') if positions[num]['MCALL'] is not None else 0
                label_pos[5][num+1]['text'] = positions[num]['STATE']
                label_pos[6][num+1]['text'] = humanFormat(positions[num]['VOL24h'])
                label_pos[7][num+1]['text'] = positions[num]['FUND']
                if positions[num]['POS'] > 0:
                    calc = calculate(symbol_list[num], ticker[num]['bid'], -float(positions[num]['POS']), 0, 1)
                    accountSumreal += calc['sumreal']
                elif positions[num]['POS'] < 0:
                    calc = calculate(symbol_list[num], ticker[num]['ask'], -float(positions[num]['POS']), 0, 1)
                    accountSumreal += calc['sumreal']

#----------------Display order book-------------------------
            def display_order(p, qnty):            
                for clOrdID in orders:
                    if orders[clOrdID]['price'] == p:
                        qnty += orders[clOrdID]['leavesQty']
                return qnty
            r = int(num_book / 2)
            label_book[2][r]['text'] = ticker[isin]['askSize']; label_book[0][r + 1]['text'] = ticker[isin]['bidSize']
            label_book[2][r]['fg'] = 'black'; label_book[0][r + 1]['fg'] = 'black'
            first_price_sell = ticker[isin]['ask'] + r * instruments[isin]['tickSize'] - instruments[isin]['tickSize']
            first_price_buy = ticker[isin]['bid']        
            for i in range(num_book-1):
                if (i < r):
                    p = str(round(first_price_sell - i * instruments[isin]['tickSize'], price_rounding[isin]))
                    p = add_zeroes(p, price_rounding[isin])                
                    label_book[1][i+1]['text'] = p
                    qnty = 0
                    if orders: qnty = display_order(float(p), qnty)
                    if qnty:
                        label_book[0][i+1]['text'] = qnty; label_book[0][i+1]['bg'] = 'orange red';
                    else:
                        label_book[0][i+1]['text'] = ''; label_book[0][i+1]['bg'] = bg_color;
                else:
                    p = str(round(first_price_buy - (i - r) * instruments[isin]['tickSize'], price_rounding[isin]))
                    p = add_zeroes(p, price_rounding[isin])                
                    label_book[1][i+1]['text'] = p
                    qnty = 0
                    if orders: qnty = display_order(float(p), qnty)
                    if qnty:
                        label_book[2][i+1]['text'] = qnty; label_book[2][i+1]['bg'] = 'green2';
                    else:
                        label_book[2][i+1]['text'] = ''; label_book[2][i+1]['bg'] = bg_color;

#----------------Display robots table-------------------------
            robot_in_use = set()
            for v in orders.values():
                robot_in_use.add(v['emi'])                
            for num, emi in enumerate(robots):
                if robots[emi]['STATUS'] == 'NOT IN LIST' and robots[emi]['POS'] == 0 and emi not in robot_in_use:
                    info_display("Robot EMI="+str(emi)+". Deleting from 'robots'")
                    del robots[emi]
                    del visavi[emi]
                    del allRoboBuys[emi]
                    del allRoboSells[emi]              
                else:
                    unrlzd = 0
                    if robots[emi]['SYMB_NUM'] != 'not_in_list':
                        close = ticker[robots[emi]['SYMB_NUM']]['bid'] 
                        if robots[emi]['POS'] < 0:
                            close = ticker[robots[emi]['SYMB_NUM']]['ask']
                        calc = calculate(robots[emi]['ISIN'], close, -float(robots[emi]['POS']), 0, 1)
                        robots[emi]['PNL'] = robots[emi]['SUMREAL'] + calc['sumreal'] - robots[emi]['COMISS']
                        unrlzd = robots[emi]['unrlzd'] - calc['sumreal']
                    if visavi[emi]['side'] == 'Sell':
                        calc = calculate(robots[emi]['ISIN'], visavi[emi]['price'], -visavi[emi]['amount'], 0.0001, 1)
                        unrlzd += calc['sumreal']+calc['comiss']
                    elif visavi[emi]['side'] == 'Buy':
                        calc = calculate(robots[emi]['ISIN'], visavi[emi]['price'], visavi[emi]['amount'], 0.0001, 1)
                        unrlzd += calc['sumreal']+calc['comiss']
                    label_robots[0][num+1]['text'] = robots[emi]['EMI']
                    label_robots[1][num+1]['text'] = robots[emi]['ISIN']+'.'+str(len(allRoboBuys[emi])+len(allRoboSells[emi]))
                    if robots[emi]['TIP'] != 'None':
                        label_robots[2][num+1]['text'] = str(robots[emi]['TIP'])+'.'+str(robots[emi]['MAX'])
                    else:
                        label_robots[2][num+1]['text'] = robots[emi]['TIP']
                    label_robots[3][num+1]['text'] = robots[emi]['STATUS']
                    label_robots[4][num+1]['text'] = humanFormat(robots[emi]['VOL'])
                    label_robots[5][num+1]['text'] = '{:.8f}'.format(robots[emi]['PNL'])
                    label_robots[6][num+1]['text'] = '{:.8f}'.format(unrlzd)
                    label_robots[7][num+1]['text'] = robots[emi]['POS']
                    label_robots[8][num+1]['text'] = str(robots[emi]['sumOfBuyAmount'])+'.'+str(robots[emi]['sumOfBuyContracts'])
                    label_robots[9][num+1]['text'] = str(robots[emi]['sumOfSellAmount'])+'.'+str(robots[emi]['sumOfSellContracts'])
                    visaviAmnt = 0
                    if emi in visavi:
                        if visavi[emi]['clOrdID'] != '':
                            if visavi[emi]['side'] == 'Sell':
                                label_robots[10][num+1]['text'] = '-'+str(visavi[emi]['amount'])+'.'+str(visavi[emi]['contracts'])
                                visaviAmnt = -visavi[emi]['amount']
                            else:
                                label_robots[10][num+1]['text'] = str(visavi[emi]['amount'])+'.'+str(visavi[emi]['contracts'])
                                visaviAmnt = visavi[emi]['amount']
                        else:
                            label_robots[10][num+1]['text'] = '0.0'
                    else:
                        label_robots[10][num+1]['text'] = '0.0'
                    label_robots[11][num+1]['text'] = str(robots[emi]['POS']+robots[emi]['sumOfBuyAmount']-robots[emi]['sumOfSellAmount']+visaviAmnt)+'.'+str(robots[emi]['waitCount'])
                    robots[emi]['y_position'] = num+1
                    if robots[emi]['STATUS'] == 'WORK':
                        label_robots[3][num+1]['fg'] = '#212121'
                    else:
                        label_robots[3][num+1]['fg'] ='red'
            else:
                if label_robots[0][num+2]['text'] != '':
                    for i in range(num+2, num_robots):
                        for k in range(12):
                             label_robots[k][i]['text'] = ''

#----------------Display account-------------------------
            label_account[0][1]['text'] = accounts['ACCOUNT']
            label_account[1][1]['text'] = '{:.6f}'.format(accounts['MARGINBAL'])
            label_account[2][1]['text'] = '{:.6f}'.format(accounts['AVAILABLE'])
            label_account[3][1]['text'] = '{:.3f}'.format(accounts['LEVERAGE'])
            label_account[4][1]['text'] = '{:.6f}'.format(accountSumreal)
            label_account[5][1]['text'] = '{:.6f}'.format(-accounts['COMISS'])
            label_account[6][1]['text'] = '{:.6f}'.format(-accounts['FUNDING'])
            label_account[7][1]['text'] = '{:.6f}'.format(accounts['MARGINBAL'] - accountSumreal + accounts['COMISS'] + accounts['FUNDING'])

    root.after(10, refresh)
refresh_var = root.after_idle(refresh)
mainloop()
