//+------------------------------------------------------------------+
//| TradinGo Signal Client                                           |
//| Lightweight EA: polls the central VPS API and executes signals.  |
//| The strategy brain remains on the VPS; this EA handles local      |
//| safety checks, order placement, and execution acknowledgements.   |
//+------------------------------------------------------------------+
#property strict

#include <Trade/Trade.mqh>

input string ApiBaseUrl          = "http://127.0.0.1:8080";
input string ApiKey              = "";
input string ClientId            = "client-demo";
input string BrokerName          = "";
input string TradeSymbol         = "XAUUSD";
input bool   EnableLiveTrading   = false;
input int    PollSeconds         = 5;
input int    MagicNumber         = 260607;
input int    MaxSpreadPoints     = 80;
input double MaxRiskPct          = 0.005;
input double FixedLotFallback    = 0.01;
input int    RequestTimeoutMs    = 5000;
input int    PendingExpiryMinutes= 90;
input bool   DebugHttp           = true;

CTrade trade;
string last_signal_id = "";
datetime last_heartbeat = 0;

struct SignalData
{
   string signal_id;
   string symbol;
   string direction;
   string entry_type;
   double entry;
   double sl;
   double tp1;
   double tp2;
   double risk_pct;
   double score;
};

int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   EventSetTimer(MathMax(1, PollSeconds));
   Print("TradinGo Signal Client initialized. LiveTrading=", EnableLiveTrading);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   if(ApiKey == "")
   {
      Print("ApiKey empty: EA paused");
      return;
   }

   if(TimeCurrent() - last_heartbeat >= 30)
   {
      SendHeartbeat("");
      last_heartbeat = TimeCurrent();
   }

   SignalData signal;
   if(!FetchLatestSignal(signal))
      return;

   if(signal.signal_id == "" || signal.signal_id == last_signal_id)
      return;

   string reason = "";
   if(!ValidateSignal(signal, reason))
   {
      SendAck(signal.signal_id, "REJECTED", reason, "");
      last_signal_id = signal.signal_id;
      return;
   }

   if(!EnableLiveTrading)
   {
      Print("Signal received but live trading disabled: ", signal.signal_id);
      SendAck(signal.signal_id, "DRY_RUN", "EnableLiveTrading=false", "");
      last_signal_id = signal.signal_id;
      return;
   }

   string ticket = "";
   bool ok = ExecuteSignal(signal, reason, ticket);
   SendAck(signal.signal_id, ok ? "EXECUTED" : "ERROR", reason, ticket);
   last_signal_id = signal.signal_id;
}

bool FetchLatestSignal(SignalData &signal)
{
   string url = ApiBaseUrl + "/signals/latest?symbol=" + TradeSymbol;
   string response = "";
   int code = HttpRequest("GET", url, "", response);
   if(code != 200)
   {
      Print("FetchLatestSignal failed: ", response);
      return false;
   }
   if(StringFind(response, "\"signal\":null") >= 0)
      return false;

   signal.signal_id = JsonString(response, "signal_id");
   signal.symbol     = JsonString(response, "symbol");
   signal.direction  = JsonString(response, "direction");
   signal.entry_type = JsonString(response, "entry_type");
   signal.entry      = JsonNumber(response, "entry");
   signal.sl         = JsonNumber(response, "sl");
   signal.tp1        = JsonNumber(response, "tp1");
   signal.tp2        = JsonNumber(response, "tp2");
   signal.risk_pct   = JsonNumber(response, "risk_pct");
   signal.score      = JsonNumber(response, "score");
   return signal.signal_id != "";
}

bool ValidateSignal(const SignalData &signal, string &reason)
{
   if(signal.symbol != TradeSymbol)
   {
      reason = "symbol mismatch";
      return false;
   }
   if(signal.direction != "BUY" && signal.direction != "SELL")
   {
      reason = "invalid direction";
      return false;
   }
   if(signal.entry <= 0 || signal.sl <= 0 || signal.tp2 <= 0)
   {
      reason = "invalid prices";
      return false;
   }
   double risk = MathAbs(signal.entry - signal.sl);
   double reward = MathAbs(signal.tp2 - signal.entry);
   if(risk <= 0 || reward / risk < 2.0)
   {
      reason = "RR below 1:2";
      return false;
   }
   if(signal.risk_pct <= 0 || signal.risk_pct > MaxRiskPct)
   {
      reason = "risk_pct outside local limit";
      return false;
   }
   int spread = CurrentSpreadPoints(signal.symbol);
   if(spread > MaxSpreadPoints)
   {
      reason = "spread too high: " + IntegerToString(spread);
      return false;
   }
   reason = "OK";
   return true;
}

bool ExecuteSignal(const SignalData &signal, string &reason, string &ticket)
{
   double lot = CalculateRiskLot(signal.symbol, signal.entry, signal.sl, signal.risk_pct);
   if(lot <= 0)
      lot = FixedLotFallback;

   bool ok = false;
   datetime expiry = TimeCurrent() + PendingExpiryMinutes * 60;
   ENUM_ORDER_TYPE_TIME type_time = ORDER_TIME_SPECIFIED;

   if(signal.entry_type == "MARKET")
   {
      if(signal.direction == "BUY")
         ok = trade.Buy(lot, signal.symbol, 0.0, signal.sl, signal.tp2, "TG_API");
      else
         ok = trade.Sell(lot, signal.symbol, 0.0, signal.sl, signal.tp2, "TG_API");
   }
   else if(signal.direction == "BUY")
   {
      ok = trade.BuyLimit(lot, signal.entry, signal.symbol, signal.sl, signal.tp2, type_time, expiry, "TG_API");
   }
   else
   {
      ok = trade.SellLimit(lot, signal.entry, signal.symbol, signal.sl, signal.tp2, type_time, expiry, "TG_API");
   }

   if(ok)
   {
      ticket = IntegerToString((int)trade.ResultOrder());
      reason = "order accepted";
      return true;
   }

   reason = trade.ResultRetcodeDescription();
   return false;
}

double CalculateRiskLot(string symbol, double entry, double sl, double risk_pct)
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity * risk_pct;
   double tick_size = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
   double min_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_lot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double loss_per_lot = MathAbs(entry - sl) / tick_size * tick_value;
   if(loss_per_lot <= 0 || step <= 0)
      return 0.0;

   double raw_lot = risk_money / loss_per_lot;
   double stepped = MathFloor(raw_lot / step) * step;
   return MathMax(min_lot, MathMin(max_lot, NormalizeDouble(stepped, 2)));
}

int CurrentSpreadPoints(string symbol)
{
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   if(point <= 0)
      return 999999;
   return (int)MathRound((ask - bid) / point);
}

void SendHeartbeat(string last_error)
{
   string payload = "{";
   payload += "\"client_id\":\"" + JsonEscape(ClientId) + "\",";
   payload += "\"broker\":\"" + JsonEscape(BrokerName) + "\",";
   payload += "\"account_login\":\"" + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)) + "\",";
   payload += "\"balance\":" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + ",";
   payload += "\"equity\":" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + ",";
   payload += "\"symbol\":\"" + JsonEscape(TradeSymbol) + "\",";
   payload += "\"open_positions\":" + IntegerToString(PositionsTotal()) + ",";
   payload += "\"daily_pnl\":0,";
   payload += "\"last_error\":\"" + JsonEscape(last_error) + "\"";
   payload += "}";
   string response = "";
   int code = HttpRequest("POST", ApiBaseUrl + "/accounts/heartbeat", payload, response);
   if(code != 200)
      Print("Heartbeat failed: ", response);
}

void SendAck(string signal_id, string status, string message, string order_ticket)
{
   string payload = "{";
   payload += "\"signal_id\":\"" + JsonEscape(signal_id) + "\",";
   payload += "\"client_id\":\"" + JsonEscape(ClientId) + "\",";
   payload += "\"status\":\"" + JsonEscape(status) + "\",";
   payload += "\"broker\":\"" + JsonEscape(BrokerName) + "\",";
   payload += "\"account_login\":\"" + IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN)) + "\",";
   payload += "\"order_ticket\":\"" + JsonEscape(order_ticket) + "\",";
   payload += "\"message\":\"" + JsonEscape(message) + "\"";
   payload += "}";
   string response = "";
   int code = HttpRequest("POST", ApiBaseUrl + "/signals/ack", payload, response);
   if(code != 200)
      Print("Ack failed: ", response);
}

int HttpRequest(string method, string url, string payload, string &response)
{
   char post[];
   StringToCharArray(payload, post, 0, WHOLE_ARRAY, CP_UTF8);
   if(payload == "")
      ArrayResize(post, 0);

   char result[];
   string result_headers = "";
   string headers = "X-API-Key: " + ApiKey + "\r\nContent-Type: application/json\r\n";
   ResetLastError();
   int code = WebRequest(method, url, headers, RequestTimeoutMs, post, result, result_headers);
   int err = GetLastError();
   string body = CharArrayToString(result, 0, ArraySize(result), CP_UTF8);
   if(code == -1)
   {
      response = "WebRequest failed method=" + method
               + " url=" + url
               + " mt5err=" + IntegerToString(err)
               + " headers=" + ShortenForLog(result_headers)
               + " body=" + ShortenForLog(body)
               + ". Add API URL in MT5: Tools > Options > Expert Advisors > Allow WebRequest.";
      Print(response);
      return -1;
   }
   response = body;
   if(DebugHttp && code != 200)
   {
      response = "HTTP code=" + IntegerToString(code)
               + " method=" + method
               + " url=" + url
               + " mt5err=" + IntegerToString(err)
               + " response_headers=" + ShortenForLog(result_headers)
               + " body=" + ShortenForLog(body);
   }
   return code;
}

string ShortenForLog(string value)
{
   StringReplace(value, "\r", " ");
   StringReplace(value, "\n", " ");
   if(StringLen(value) > 500)
      return StringSubstr(value, 0, 500) + "...";
   return value;
}

string JsonString(string json, string key)
{
   string token = "\"" + key + "\":";
   int p = StringFind(json, token);
   if(p < 0)
      return "";
   p += StringLen(token);
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ')
      p++;
   if(p >= StringLen(json) || StringGetCharacter(json, p) != '"')
      return "";
   p++;
   int end = StringFind(json, "\"", p);
   if(end < 0)
      return "";
   return StringSubstr(json, p, end - p);
}

double JsonNumber(string json, string key)
{
   string token = "\"" + key + "\":";
   int p = StringFind(json, token);
   if(p < 0)
      return 0.0;
   p += StringLen(token);
   while(p < StringLen(json) && StringGetCharacter(json, p) == ' ')
      p++;
   int end = p;
   while(end < StringLen(json))
   {
      ushort ch = StringGetCharacter(json, end);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-')
         end++;
      else
         break;
   }
   return StringToDouble(StringSubstr(json, p, end - p));
}

string JsonEscape(string value)
{
   StringReplace(value, "\\", "\\\\");
   StringReplace(value, "\"", "\\\"");
   return value;
}
