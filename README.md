# Sample algorithmic trading platform for Bitmex
![Image](https://github.com/evgrmn/bitmex/blob/main/sample.gif)

Working condition tested on Linux:
- Mint 17, Python 3.4
- Debian 9, Python 3.5
- Debian 11, Python 3.9

This software is used for privat purposes only. Although the software has been in use for several years, bugs are possible.

Codes may be redundant. This is due to uncertainties and inconsistencies in the processing of orders and transactions in automatic trading.

Bitmex API-connector is used from https://github.com/BitMEX/api-connectors

MySQL tables:

```SQL
CREATE TABLE `coins` (
  `ID` int NOT NULL AUTO_INCREMENT,
  `EXECID` varchar(45) DEFAULT NULL,
  `EMI` tinyint DEFAULT NULL,
  `ISIN` tinyint DEFAULT NULL,
  `TICKER` varchar(10) DEFAULT NULL,
  `IDISIN` int DEFAULT NULL,
  `DIR` tinyint DEFAULT NULL,
  `AMOUNT` int DEFAULT NULL,
  `AMOUNT_REST` int DEFAULT NULL,
  `PRICE` decimal(10,2) DEFAULT NULL,
  `TEOR_PRICE` decimal(10,2) DEFAULT NULL,
  `TRADE_PRICE` decimal(10,2) DEFAULT NULL,
  `SUMREAL` decimal(19,12) DEFAULT NULL,
  `KOMISS` decimal(19,15) DEFAULT '0.000000000000000',
  `TTIME` timestamp NULL DEFAULT NULL,
  `DAT` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `ELAPSED` int DEFAULT '0',
  `CLORDID` int DEFAULT '0',
  `ACCOUNT` int DEFAULT '0',
  UNIQUE KEY `ID_UNIQUE` (`ID`),
  KEY `EXECID_ix` (`EXECID`),
  KEY `EMI_AMOUNT_ix` (`EMI`,`AMOUNT`),
  KEY `DIR_ix` (`DIR`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

CREATE TABLE `robots` (
  `EMI` tinyint DEFAULT NULL,
  `ISIN` varchar(10) DEFAULT NULL,
  `SORT` tinyint DEFAULT NULL,
  `TIP` tinyint DEFAULT NULL,
  `LOTDAY` int DEFAULT NULL,
  `MAXDAY` int DEFAULT NULL,
  `OTSTUP` tinyint DEFAULT NULL,
  `LOTEVE` int DEFAULT NULL,
  `MAXEVE` int DEFAULT NULL,
  `DAT` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `TIMEFR` tinyint DEFAULT '0',
  `SMESH` int DEFAULT '0',
  `PERSHORT` int DEFAULT '0',
  `PERLONG` int DEFAULT '0',
  `CAPITAL` int DEFAULT '0',
  `MARGIN` int DEFAULT '0',
  `MINCONT` int DEFAULT '0',
  `DOPDEP` int DEFAULT '0',
  `PERTHIRD` int DEFAULT '0',
  `PERFOURTH` int DEFAULT '0',
  `PROCE` int DEFAULT '0',
  `SECUN` int DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
```
- bitmex.py - main file
- init.ini - contains tickers
- history.ini - if the first line is 0, it means downloading the entire trading history from Bitmex for the connected account
- login_details.txt - two lines: api_key and api_secret of an account
