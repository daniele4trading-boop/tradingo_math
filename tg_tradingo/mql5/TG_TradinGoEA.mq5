//+------------------------------------------------------------------+
//| TG_TradinGoEA.mq5                                                |
//| Legge segnali JSON dal bridge Python ed esegue ordini su MT5.    |
//| Distribuibile: ogni utente configura SignalsPath e LotMultiplier |
//+------------------------------------------------------------------+
#property copyright "TradinGo"
#property link      "https://github.com/daniele4trading-boop/tradingo_system"
#property version   "2.01"
#property description "JSON signal executor for TG TradinGo bridge"

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>

//--- inputs
// Default: read signal_ch_*.json from MQL5\\Files (where the bridge writes).
// Set InpUseAbsolutePath=true only for a custom folder outside MQL5\\Files.
input string InpSignalsPath        = "";
input bool   InpUseAbsolutePath    = false;
input string InpChannels           = "gold,forex,oro,stark";
input string InpSymbolSuffix       = "";
input double InpLotMultiplier      = 1.0;
input double InpAddLotFactor       = 0.5;
input int    InpMaxSlippagePoints  = 50;
input int    InpPollMs             = 500;
input int    InpEntryRangeTimeoutSec = 3600;
input bool   InpAutoBreakEvenOnTp1 = true;
input ulong  InpMagicOffset        = 0;

//--- trade objects
CTrade         g_trade;
CPositionInfo  g_pos;
CSymbolInfo    g_sym;

//--- channel state
#define MAX_CHANNELS 16
string g_channelSuffix[MAX_CHANNELS];
string g_channelFile[MAX_CHANNELS];
string g_lastTimestamp[MAX_CHANNELS];
int    g_channelCount = 0;

//--- pending entry range wait
struct PendingRange
  {
   bool     active;
   string   channelFile;
   string   timestamp;
   string   direction;
   string   symbol;
   double   rangeLo;
   double   rangeHi;
   double   sl;
   double   tpLevels[];
   int      trades;
   double   fixedLot;
   int      magicBase;
   datetime started;
  };

PendingRange g_pending;

//+------------------------------------------------------------------+
string Trim(const string s)
  {
   string t = s;
   StringTrimLeft(t);
   StringTrimRight(t);
   return t;
  }

//+------------------------------------------------------------------+
string JsonGetString(const string json, const string key)
  {
   string pat = "\"" + key + "\"";
   int p = StringFind(json, pat);
   if(p < 0)
      return "";
   p = StringFind(json, ":", p);
   if(p < 0)
      return "";
   p++;
   while(p < StringLen(json) && (StringGetCharacter(json, p) == ' ' || StringGetCharacter(json, p) == '\t'))
      p++;
   if(StringGetCharacter(json, p) == '"')
     {
      int q1 = p + 1;
      int q2 = StringFind(json, "\"", q1);
      if(q2 < 0)
         return "";
      return StringSubstr(json, q1, q2 - q1);
     }
   int end = p;
   while(end < StringLen(json))
     {
      ushort c = StringGetCharacter(json, end);
      if(c == ',' || c == '}' || c == '\n' || c == '\r')
         break;
      end++;
     }
   return Trim(StringSubstr(json, p, end - p));
  }

//+------------------------------------------------------------------+
double JsonGetNumber(const string json, const string key)
  {
   string v = JsonGetString(json, key);
   if(v == "" || v == "null")
      return 0.0;
   StringReplace(v, ",", ".");
   return StringToDouble(v);
  }

//+------------------------------------------------------------------+
bool JsonGetBool(const string json, const string key)
  {
   string v = JsonGetString(json, key);
   return (v == "true" || v == "1");
  }

//+------------------------------------------------------------------+
int JsonGetInt(const string json, const string key)
  {
   return (int)JsonGetNumber(json, key);
  }

//+------------------------------------------------------------------+
bool JsonGetNumberArray(const string json, const string key, double &out[])
  {
   ArrayResize(out, 0);
   string pat = "\"" + key + "\"";
   int p = StringFind(json, pat);
   if(p < 0)
      return false;
   p = StringFind(json, "[", p);
   if(p < 0)
      return false;
   int q = StringFind(json, "]", p);
   if(q < 0)
      return false;
   string inner = StringSubstr(json, p + 1, q - p - 1);
   if(Trim(inner) == "")
      return true;
   string parts[];
   int n = StringSplit(inner, ',', parts);
   ArrayResize(out, n);
   for(int i = 0; i < n; i++)
     {
      string v = Trim(parts[i]);
      StringReplace(v, ",", ".");
      out[i] = StringToDouble(v);
     }
   return true;
  }

//+------------------------------------------------------------------+
string BuildAbsoluteSignalPath(const string fileName)
  {
   string base = InpSignalsPath;
   if(StringLen(base) > 0 && StringGetCharacter(base, StringLen(base) - 1) != '\\')
      base += "\\";
   return base + fileName;
  }

//+------------------------------------------------------------------+
string BuildRelativeSignalPath(const string fileName)
  {
   if(StringLen(InpSignalsPath) == 0)
      return fileName;
   string base = InpSignalsPath;
   if(StringGetCharacter(base, StringLen(base) - 1) != '\\')
      base += "\\";
   return base + fileName;
  }

//+------------------------------------------------------------------+
bool ReadTextFileContent(const string path, string &content)
  {
   content = "";
   int flags = FILE_READ | FILE_TXT | FILE_ANSI | FILE_SHARE_READ;
   ResetLastError();
   int h = FileOpen(path, flags);
   if(h == INVALID_HANDLE)
     {
      ResetLastError();
      h = FileOpen(path, flags | FILE_COMMON);
      if(h == INVALID_HANDLE)
         return false;
     }
   while(!FileIsEnding(h))
     {
      content += FileReadString(h);
      if(!FileIsEnding(h))
         content += "\n";
     }
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
string JoinStrings(const string &parts[], const string sep)
  {
   string out = "";
   for(int i = 0; i < ArraySize(parts); i++)
     {
      if(i > 0)
         out += sep;
      out += parts[i];
     }
   return out;
  }

//+------------------------------------------------------------------+
bool ReadSignalFile(const string fileName, string &content)
  {
   string candidates[];
   int n = 0;

   if(InpUseAbsolutePath && StringLen(InpSignalsPath) > 0)
     {
      ArrayResize(candidates, n + 1);
      candidates[n++] = BuildAbsoluteSignalPath(fileName);
     }

   ArrayResize(candidates, n + 1);
   candidates[n++] = BuildRelativeSignalPath(fileName);

   ArrayResize(candidates, n + 1);
   candidates[n++] = fileName;

   for(int i = 0; i < n; i++)
     {
      if(ReadTextFileContent(candidates[i], content))
         return true;
     }

   Print("[TradinGo] FileOpen failed for ", fileName,
         " | tried: ", JoinStrings(candidates, " ; "),
         " | err=", GetLastError(),
         " | hint: bridge writes to MQL5\\Files of THIS terminal");
   return false;
  }

//+------------------------------------------------------------------+
string ResolveSymbol(const string raw)
  {
   string s = raw;
   StringToUpper(s);
   if(StringLen(InpSymbolSuffix) > 0 && StringFind(s, InpSymbolSuffix) < 0)
      s += InpSymbolSuffix;
   if(!SymbolSelect(s, true))
      Print("[TradinGo] SymbolSelect warning: ", s);
   return s;
  }

//+------------------------------------------------------------------+
ulong TradeMagic(const int magicBase, const int index)
  {
   return (ulong)magicBase + (ulong)index + InpMagicOffset;
  }

//+------------------------------------------------------------------+
bool IsOurPosition(const ulong ticket, const int magicBase, const int maxTrades)
  {
   if(!g_pos.SelectByTicket(ticket))
      return false;
   ulong mg = g_pos.Magic();
   for(int i = 1; i <= maxTrades; i++)
     {
      if(mg == TradeMagic(magicBase, i))
         return true;
     }
   return false;
  }

//+------------------------------------------------------------------+
int CountOurPositions(const string symbol, const int magicBase, const int maxTrades)
  {
   int cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(IsOurPosition(g_pos.Ticket(), magicBase, maxTrades))
         cnt++;
     }
   return cnt;
  }

//+------------------------------------------------------------------+
void CloseOurPositions(const string symbol, const int magicBase, const int maxTrades)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, maxTrades))
         continue;
      g_trade.PositionClose(g_pos.Ticket());
     }
  }

//+------------------------------------------------------------------+
double NormalizeLot(const string symbol, double lot)
  {
   double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step   = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0)
      step = 0.01;
   lot *= InpLotMultiplier;
   lot = MathFloor(lot / step) * step;
   if(lot < minLot)
      lot = minLot;
   if(lot > maxLot)
      lot = maxLot;
   return lot;
  }

//+------------------------------------------------------------------+
bool OpenMarket(const string symbol, const string direction, const double lot,
                const double sl, const double tp, const ulong magic)
  {
   g_sym.Name(symbol);
   g_sym.RefreshRates();
   g_trade.SetExpertMagicNumber((int)magic);
   g_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   bool ok = false;
   if(direction == "BUY")
      ok = g_trade.Buy(lot, symbol, 0.0, sl > 0 ? sl : 0.0, tp > 0 ? tp : 0.0);
   else
      ok = g_trade.Sell(lot, symbol, 0.0, sl > 0 ? sl : 0.0, tp > 0 ? tp : 0.0);
   if(!ok)
      Print("[TradinGo] Open failed ", symbol, " ", direction, " err=", g_trade.ResultRetcode());
   return ok;
  }

//+------------------------------------------------------------------+
bool ModifyPositionSLTP(const ulong ticket, const double sl, const double tp)
  {
   if(!g_pos.SelectByTicket(ticket))
      return false;
   double curSl = g_pos.StopLoss();
   double curTp = g_pos.TakeProfit();
   double nsl = sl > 0 ? sl : curSl;
   double ntp = tp > 0 ? tp : curTp;
   if(nsl == curSl && ntp == curTp)
      return true;
   return g_trade.PositionModify(ticket, nsl, ntp);
  }

//+------------------------------------------------------------------+
bool PriceInRange(const string symbol, const string direction, const double lo, const double hi)
  {
   g_sym.Name(symbol);
   g_sym.RefreshRates();
   double px = (direction == "BUY") ? g_sym.Ask() : g_sym.Bid();
   return (px >= lo && px <= hi);
  }

//+------------------------------------------------------------------+
void ClearPendingRange()
  {
   g_pending.active = false;
   g_pending.timestamp = "";
   ArrayResize(g_pending.tpLevels, 0);
  }

//+------------------------------------------------------------------+
void SetPendingRange(const string channelFile, const string json,
                     const string direction, const string symbol,
                     const double lo, const double hi, const double sl,
                     const double &tps[], const int trades, const double fixedLot,
                     const int magicBase)
  {
   g_pending.active = true;
   g_pending.channelFile = channelFile;
   g_pending.timestamp = JsonGetString(json, "timestamp");
   g_pending.direction = direction;
   g_pending.symbol = symbol;
   g_pending.rangeLo = lo;
   g_pending.rangeHi = hi;
   g_pending.sl = sl;
   ArrayResize(g_pending.tpLevels, ArraySize(tps));
   ArrayCopy(g_pending.tpLevels, tps);
   g_pending.trades = trades;
   g_pending.fixedLot = fixedLot;
   g_pending.magicBase = magicBase;
   g_pending.started = TimeCurrent();
   Print("[TradinGo] Waiting entry range ", symbol, " ", direction,
         " [", DoubleToString(lo, (int)g_sym.Digits()), ",",
         DoubleToString(hi, (int)g_sym.Digits()), "]");
  }

//+------------------------------------------------------------------+
bool OpenSplitTrades(const string symbol, const string direction,
                     const double lot, const double sl, const double &tps[],
                     const int magicBase)
  {
   int n = ArraySize(tps);
   if(n <= 0)
      n = 1;
   bool any = false;
   for(int i = 0; i < n; i++)
     {
      double tp = (i < ArraySize(tps)) ? tps[i] : 0.0;
      ulong magic = TradeMagic(magicBase, i + 1);
      if(OpenMarket(symbol, direction, lot, sl, tp, magic))
         any = true;
     }
   return any;
  }

//+------------------------------------------------------------------+
bool HandleOpen(const string channelFile, const string json)
  {
   string action = JsonGetString(json, "action");
   string direction = JsonGetString(json, "direction");
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   double sl = JsonGetNumber(json, "sl");
   double tps[];
   JsonGetNumberArray(json, "tp_levels", tps);
   int trades = JsonGetInt(json, "trades");
   if(trades <= 0)
      trades = MathMax(1, ArraySize(tps));
   double fixedLot = JsonGetNumber(json, "fixed_lot");
   if(fixedLot <= 0)
      fixedLot = 0.20;
   double lot = NormalizeLot(symbol, fixedLot);
   if(JsonGetBool(json, "is_add_signal"))
      lot = NormalizeLot(symbol, fixedLot * InpAddLotFactor);

   if(JsonGetBool(json, "inherit_from_first"))
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         if(!g_pos.SelectByIndex(i))
            continue;
         if(g_pos.Symbol() != symbol)
            continue;
         if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
            continue;
         if(sl <= 0)
            sl = g_pos.StopLoss();
         if(ArraySize(tps) == 0)
           {
            double tp = g_pos.TakeProfit();
            ArrayResize(tps, 1);
            tps[0] = tp;
           }
         break;
        }
     }

   double rangeLo = 0, rangeHi = 0;
   double entryRange[];
   if(JsonGetNumberArray(json, "entry_range", entryRange) && ArraySize(entryRange) >= 2)
     {
      rangeLo = MathMin(entryRange[0], entryRange[1]);
      rangeHi = MathMax(entryRange[0], entryRange[1]);
     }

   if(rangeHi > rangeLo)
     {
      if(!PriceInRange(symbol, direction, rangeLo, rangeHi))
        {
         SetPendingRange(channelFile, json, direction, symbol, rangeLo, rangeHi,
                         sl, tps, trades, fixedLot, magicBase);
         return true;
        }
     }

   if(action == "OPEN_NOW")
     {
      return OpenMarket(symbol, direction, lot, 0, 0, TradeMagic(magicBase, 1));
     }

   return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase);
  }

//+------------------------------------------------------------------+
bool HandleUpdateOpen(const string json)
  {
   string direction = JsonGetString(json, "direction");
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   double sl = JsonGetNumber(json, "sl");
   double tps[];
   JsonGetNumberArray(json, "tp_levels", tps);
   int trades = JsonGetInt(json, "trades");
   if(trades <= 0)
      trades = MathMax(1, ArraySize(tps));
   double fixedLot = JsonGetNumber(json, "fixed_lot");
   if(fixedLot <= 0)
      fixedLot = 0.10;
   double lot = NormalizeLot(symbol, fixedLot);

   int openCnt = CountOurPositions(symbol, magicBase, 5);
   if(openCnt == 0)
     {
      Print("[TradinGo] UPDATE_OPEN but no positions — opening fresh");
      return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase);
     }

   if(openCnt == 1 && trades > 1)
     {
      Print("[TradinGo] UPDATE_OPEN split: close 1 reopen ", trades);
      CloseOurPositions(symbol, magicBase, 5);
      return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase);
     }

   int idx = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      double tp = (idx < ArraySize(tps)) ? tps[idx] : 0.0;
      ModifyPositionSLTP(g_pos.Ticket(), sl, tp);
      idx++;
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleUpdateTp(const string json)
  {
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   double newTp = JsonGetNumber(json, "new_tp");
   if(newTp <= 0)
     {
      double tps[];
      JsonGetNumberArray(json, "tp_levels", tps);
      if(ArraySize(tps) > 0)
         newTp = tps[0];
     }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      ModifyPositionSLTP(g_pos.Ticket(), 0, newTp);
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleUpdateSl(const string json)
  {
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   double newSl = JsonGetNumber(json, "new_sl");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      ModifyPositionSLTP(g_pos.Ticket(), newSl, 0);
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleCheckAndClose(const string json)
  {
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   string direction = JsonGetString(json, "direction");
   int magicBase = JsonGetInt(json, "magic_base");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      string pdir = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      if(pdir == direction)
         g_trade.PositionClose(g_pos.Ticket());
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleCloseAllSymbol(const string json)
  {
   string symRaw = JsonGetString(json, "symbol");
   int magicBase = JsonGetInt(json, "magic_base");
   if(symRaw == "")
     {
      for(int i = PositionsTotal() - 1; i >= 0; i--)
        {
         if(!g_pos.SelectByIndex(i))
            continue;
         if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
            continue;
         g_trade.PositionClose(g_pos.Ticket());
        }
      return true;
     }
   string symbol = ResolveSymbol(symRaw);
   CloseOurPositions(symbol, magicBase, 5);
   return true;
  }

//+------------------------------------------------------------------+
bool HandleBreakEvenPrice(const string json)
  {
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   double be = JsonGetNumber(json, "be_price");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      ModifyPositionSLTP(g_pos.Ticket(), be, 0);
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleCloseHalfBe(const string json)
  {
   string symbol = ResolveSymbol(JsonGetString(json, "symbol"));
   int magicBase = JsonGetInt(json, "magic_base");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      double vol = g_pos.Volume();
      double half = NormalizeLot(symbol, vol / 2.0);
      if(half < SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN))
         continue;
      g_trade.PositionClosePartial(g_pos.Ticket(), half);
      double be = g_pos.PriceOpen();
      ModifyPositionSLTP(g_pos.Ticket(), be, 0);
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleCheckAndBe(const string json)
  {
   int magicBase = JsonGetInt(json, "magic_base");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      double be = g_pos.PriceOpen();
      ModifyPositionSLTP(g_pos.Ticket(), be, 0);
     }
   return true;
  }

//+------------------------------------------------------------------+
bool HandleCheckAndCloseTp(const string json)
  {
   int magicBase = JsonGetInt(json, "magic_base");
   int tpIndex = JsonGetInt(json, "tp_index");
   if(tpIndex <= 0)
      tpIndex = 1;
   ulong targetMagic = TradeMagic(magicBase, tpIndex);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if((ulong)g_pos.Magic() != targetMagic)
         continue;
      g_trade.PositionClose(g_pos.Ticket());
     }
   return true;
  }

//+------------------------------------------------------------------+
bool ProcessSignalJson(const string channelFile, const string json)
  {
   string action = JsonGetString(json, "action");
   if(action == "" || action == "NONE")
      return false;

   string ts = JsonGetString(json, "timestamp");
   for(int c = 0; c < g_channelCount; c++)
     {
      if(g_channelFile[c] == channelFile)
        {
         if(ts != "" && ts == g_lastTimestamp[c])
            return false;
         if(ts != "")
            g_lastTimestamp[c] = ts;
         break;
        }
     }

   Print("[TradinGo] ", channelFile, " action=", action,
         " sym=", JsonGetString(json, "symbol"),
         " ts=", ts);

   if(action == "OPEN" || action == "OPEN_NOW")
      return HandleOpen(channelFile, json);
   if(action == "UPDATE_OPEN")
      return HandleUpdateOpen(json);
   if(action == "UPDATE_TP")
      return HandleUpdateTp(json);
   if(action == "UPDATE_SL")
      return HandleUpdateSl(json);
   if(action == "CHECK_AND_CLOSE")
      return HandleCheckAndClose(json);
   if(action == "CLOSE_ALL_SYMBOL")
      return HandleCloseAllSymbol(json);
   if(action == "BREAK_EVEN_PRICE")
      return HandleBreakEvenPrice(json);
   if(action == "CLOSE_HALF_BE")
      return HandleCloseHalfBe(json);
   if(action == "CHECK_AND_BE")
      return HandleCheckAndBe(json);
   if(action == "CHECK_AND_CLOSE_TP")
      return HandleCheckAndCloseTp(json);

   Print("[TradinGo] Unknown action: ", action);
   return false;
  }

//+------------------------------------------------------------------+
void PollChannel(const int index)
  {
   string json;
   if(!ReadSignalFile(g_channelFile[index], json))
      return;
   ProcessSignalJson(g_channelFile[index], json);
  }

//+------------------------------------------------------------------+
void PollPendingRange()
  {
   if(!g_pending.active)
      return;
   if(InpEntryRangeTimeoutSec > 0 &&
      (TimeCurrent() - g_pending.started) > InpEntryRangeTimeoutSec)
     {
      Print("[TradinGo] Entry range timeout ", g_pending.symbol);
      ClearPendingRange();
      return;
     }
   if(!PriceInRange(g_pending.symbol, g_pending.direction,
                    g_pending.rangeLo, g_pending.rangeHi))
      return;

   double lot = NormalizeLot(g_pending.symbol, g_pending.fixedLot);
   OpenSplitTrades(g_pending.symbol, g_pending.direction, lot,
                   g_pending.sl, g_pending.tpLevels, g_pending.magicBase);
   ClearPendingRange();
  }

//+------------------------------------------------------------------+
void ParseChannels()
  {
   g_channelCount = 0;
   string parts[];
   int n = StringSplit(InpChannels, ',', parts);
   for(int i = 0; i < n && g_channelCount < MAX_CHANNELS; i++)
     {
      string suf = Trim(parts[i]);
      if(suf == "")
         continue;
      g_channelSuffix[g_channelCount] = suf;
      g_channelFile[g_channelCount] = "signal_ch_" + suf + ".json";
      g_lastTimestamp[g_channelCount] = "";
      g_channelCount++;
     }
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   ParseChannels();
   ClearPendingRange();
   g_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   EventSetMillisecondTimer(InpPollMs);
   Print("[TradinGo] EA v2.01 started | channels=", g_channelCount,
         " path=", (StringLen(InpSignalsPath) > 0 ? InpSignalsPath : "<MQL5\\Files>"),
         " abs=", InpUseAbsolutePath);
   for(int i = 0; i < g_channelCount; i++)
      Print("[TradinGo]  watch ", g_channelFile[i]);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   for(int i = 0; i < g_channelCount; i++)
      PollChannel(i);
   PollPendingRange();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // timer-driven; tick hook for future BE-on-TP1 monitor
  }
//+------------------------------------------------------------------+
