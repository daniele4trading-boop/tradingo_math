//+------------------------------------------------------------------+
//| TG_TradinGoEA.mq5                                                |
//| Legge segnali JSON dal bridge Python ed esegue ordini su MT5.    |
//| Distribuibile: ogni utente configura SignalsPath e LotMultiplier |
//+------------------------------------------------------------------+
#property copyright "TradinGo"
#property link      "https://github.com/daniele4trading-boop/tradingo_system"
#property version   "2.09"
#property description "JSON signal executor for TG TradinGo bridge"

#include <Trade/Trade.mqh>
#include <Trade/PositionInfo.mqh>
#include <Trade/SymbolInfo.mqh>

//--- inputs
// Default: read signal_ch_*.json from MQL5\\Files (where the bridge writes).
// Set InpUseAbsolutePath=true only for a custom folder outside MQL5\\Files.
input string InpSignalsPath        = "";
input bool   InpUseAbsolutePath    = false;
input string InpChannels           = "gold,forex,oro,stark,ivan";
input string InpSymbolSuffix       = "";
input double InpLotMultiplier      = 1.0;
input double InpAddLotFactor       = 0.5;
input int    InpMaxSlippagePoints  = 50;
input int    InpPollMs             = 500;
input int    InpRangeTolerancePoints = 150;
input int    InpOroRangeTolerancePoints = 250; // 0 = use InpRangeTolerancePoints
input bool   InpLogCancelledSignals  = true;
input bool   InpClearSignalAfterProcess = true;
input bool   InpIgnoreExistingOnInit = true; // skip+clear JSON already present at attach
input bool   InpStackOpensIfFlatBusy = true; // honor JSON allow_stack when positions already open
input int    InpStopBufferPoints   = 20;     // extra pts beyond stops/freeze level (avoid 10016)
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

enum EntryRangeDecision
  {
   ENTRY_EXECUTE_IN_RANGE = 0,
   ENTRY_EXECUTE_TOLERANCE = 1,
   ENTRY_CANCELLED = 2
  };

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
bool WriteTextFileContent(const string path, const string content)
  {
   int flags = FILE_WRITE | FILE_TXT | FILE_ANSI;
   ResetLastError();
   int h = FileOpen(path, flags);
   if(h == INVALID_HANDLE)
     {
      ResetLastError();
      h = FileOpen(path, flags | FILE_COMMON);
      if(h == INVALID_HANDLE)
         return false;
     }
   FileWriteString(h, content);
   FileClose(h);
   return true;
  }

//+------------------------------------------------------------------+
bool ClearSignalFile(const string fileName)
  {
   string payload = "{\"action\":\"NONE\"}\n";
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
      if(WriteTextFileContent(candidates[i], payload))
        {
         Print("[TradinGo] Cleared ", fileName, " -> NONE (path=", candidates[i], ")");
         return true;
        }
     }
   Print("[TradinGo] Clear failed for ", fileName, " err=", GetLastError());
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
int RangeToleranceForChannel(const string channelFile, const string json)
  {
   string ch = JsonGetString(json, "channel_id");
   StringToUpper(ch);
   string fileLower = channelFile;
   StringToLower(fileLower);
   bool isOro = (ch == "CH_ORO" || StringFind(fileLower, "oro") >= 0);
   if(isOro && InpOroRangeTolerancePoints > 0)
      return InpOroRangeTolerancePoints;
   return InpRangeTolerancePoints;
  }

//+------------------------------------------------------------------+
void AdjustStopsToMinDistance(const string symbol, const string direction,
                              double &sl, double &tp, const int extraPts = -1)
  {
   // Avoid MT5 retcode 10016 (invalid stops) by enforcing SYMBOL_TRADE_STOPS_LEVEL
   // and forcing SL/TP onto the legal side of the current price.
   g_sym.Name(symbol);
   g_sym.RefreshRates();
   double point = g_sym.Point();
   if(point <= 0.0)
      point = _Point;
   int stopsLevel = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int freezeLevel = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   int bufferPts = (extraPts >= 0) ? extraPts : InpStopBufferPoints;
   if(bufferPts < 0)
      bufferPts = 0;
   int minPts = MathMax(stopsLevel, freezeLevel) + bufferPts;
   if(minPts < 1)
      minPts = 1;
   double minDist = minPts * point;
   int digits = (int)g_sym.Digits();
   // For modifying protective SL use the price that MT5 validates against.
   double price = (direction == "BUY") ? g_sym.Bid() : g_sym.Ask();

   if(direction == "BUY")
     {
      if(sl > 0.0 && sl > price - minDist)
         sl = NormalizeDouble(price - minDist, digits);
      if(tp > 0.0 && tp < price + minDist)
         tp = NormalizeDouble(price + minDist, digits);
     }
   else
     {
      if(sl > 0.0 && sl < price + minDist)
         sl = NormalizeDouble(price + minDist, digits);
      if(tp > 0.0 && tp > price - minDist)
         tp = NormalizeDouble(price - minDist, digits);
     }
  }

//+------------------------------------------------------------------+
bool ModifyPositionSLTP(const ulong ticket, const double sl, const double tp,
                        const int extraPts = -1)
  {
   if(!g_pos.SelectByTicket(ticket))
      return false;
   string symbol = g_pos.Symbol();
   string direction = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   double curSl = g_pos.StopLoss();
   double curTp = g_pos.TakeProfit();
   double nsl = sl > 0 ? sl : curSl;
   double ntp = tp > 0 ? tp : curTp;
   if(nsl > 0.0 || ntp > 0.0)
      AdjustStopsToMinDistance(symbol, direction, nsl, ntp, extraPts);
   if(nsl == curSl && ntp == curTp)
      return true;
   bool ok = g_trade.PositionModify(ticket, nsl, ntp);
   if(!ok)
      Print("[TradinGo] PositionModify failed ticket=", ticket,
            " err=", g_trade.ResultRetcode(),
            " sl=", DoubleToString(nsl, (int)g_sym.Digits()),
            " tp=", DoubleToString(ntp, (int)g_sym.Digits()));
   return ok;
  }

//+------------------------------------------------------------------+
bool ApplyBreakEvenSL(const ulong ticket)
  {
   // Close-half / CHECK_AND_BE: prefer SL=entry; if invalid vs market, clamp to min legal stop.
   // Retry with a wider buffer on 10016 (spread race after half-close).
   if(!g_pos.SelectByTicket(ticket))
      return false;
   string symbol = g_pos.Symbol();
   string direction = (g_pos.PositionType() == POSITION_TYPE_BUY) ? "BUY" : "SELL";
   double be = g_pos.PriceOpen();
   int buffers[3];
   buffers[0] = InpStopBufferPoints;
   buffers[1] = InpStopBufferPoints + 20;
   buffers[2] = InpStopBufferPoints + 50;
   for(int attempt = 0; attempt < 3; attempt++)
     {
      if(!g_pos.SelectByTicket(ticket))
         return false;
      double nsl = be;
      double ntp = g_pos.TakeProfit();
      AdjustStopsToMinDistance(symbol, direction, nsl, ntp, buffers[attempt]);
      if(MathAbs(nsl - be) > g_sym.Point())
         Print("[TradinGo] BE clamped ticket=", ticket,
               " entry=", DoubleToString(be, (int)g_sym.Digits()),
               " -> sl=", DoubleToString(nsl, (int)g_sym.Digits()),
               " (", direction, ") bufPts=", buffers[attempt]);
      if(ModifyPositionSLTP(ticket, nsl, 0, buffers[attempt]))
         return true;
      if(g_trade.ResultRetcode() != 10016)
         return false;
     }
   return false;
  }

//+------------------------------------------------------------------+
string ChannelShortTag(const string channelFile, const string json)
  {
   string cid = JsonGetString(json, "channel_id");
   if(cid != "")
     {
      StringReplace(cid, "CH_", "");
      return cid;
     }
   string f = channelFile;
   StringReplace(f, "signal_ch_", "");
   StringReplace(f, ".json", "");
   StringToUpper(f);
   return f;
  }

//+------------------------------------------------------------------+
string BuildTradeComment(const string channelTag, const int tpIndex)
  {
   if(tpIndex > 0)
      return StringFormat("TG-%s-T%d", channelTag, tpIndex);
   return StringFormat("TG-%s", channelTag);
  }

//+------------------------------------------------------------------+
void AppendSignalStat(const string channelFile, const string json,
                      const string symbol, const string direction,
                      const string status,
                      const double rangeLo, const double rangeHi,
                      const double signalEntry, const double fillPrice,
                      const double distancePoints, const int tpIndex,
                      const ulong magic)
  {
   if(!InpLogCancelledSignals)
      return;

   string ch = JsonGetString(json, "channel_id");
   string ts = JsonGetString(json, "timestamp");
   double slippagePts = 0.0;
   if(signalEntry > 0.0 && fillPrice > 0.0)
     {
      g_sym.Name(symbol);
      double point = g_sym.Point();
      if(point <= 0.0)
         point = _Point;
      slippagePts = (fillPrice - signalEntry) / point;
      if(direction == "SELL")
         slippagePts = -slippagePts;
     }

   string line = StringFormat(
      "%s,%s,%s,%s,%s,%s,%.5f,%.5f,%.5f,%.5f,%.1f,%.1f,%d,%s,%s\n",
      TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
      ch,
      channelFile,
      symbol,
      direction,
      status,
      signalEntry,
      rangeLo,
      rangeHi,
      fillPrice,
      slippagePts,
      distancePoints,
      tpIndex,
      IntegerToString(magic),
      ts
   );

   int h = FileOpen("tradingo_signal_stats.csv",
                    FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
     {
      h = FileOpen("tradingo_signal_stats.csv",
                   FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_WRITE);
      if(h != INVALID_HANDLE)
         FileWriteString(h,
            "time,channel_id,channel_file,symbol,direction,status,signal_entry,range_lo,range_hi,fill_price,slippage_points,distance_points,tp_index,magic,telegram_ts\n");
     }
   if(h != INVALID_HANDLE)
     {
      FileSeek(h, 0, SEEK_END);
      FileWriteString(h, line);
      FileClose(h);
     }
  }

//+------------------------------------------------------------------+
double SignalEntryFromJson(const string json, const double rangeLo, const double rangeHi)
  {
   double entry = JsonGetNumber(json, "entry");
   if(entry > 0.0)
      return entry;
   if(rangeHi > rangeLo)
      return (rangeLo + rangeHi) / 2.0;
   return 0.0;
  }

//+------------------------------------------------------------------+
bool StopsOnCorrectSide(const string direction, const double price,
                        const double sl, const double tp)
  {
   if(direction == "BUY")
     {
      if(sl > 0.0 && sl >= price)
         return false;
      if(tp > 0.0 && tp <= price)
         return false;
     }
   else
     {
      if(sl > 0.0 && sl <= price)
         return false;
      if(tp > 0.0 && tp >= price)
         return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
bool OpenMarket(const string symbol, const string direction, const double lot,
                const double sl, const double tp, const ulong magic,
                const string comment,
                const string channelFile, const string json,
                const string entryStatus,
                const double rangeLo, const double rangeHi,
                const double distancePoints, const int tpIndex)
  {
   g_sym.Name(symbol);
   g_sym.RefreshRates();
   g_trade.SetExpertMagicNumber((int)magic);
   g_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   double nsl = sl;
   double ntp = tp;
   if(nsl > 0.0 || ntp > 0.0)
      AdjustStopsToMinDistance(symbol, direction, nsl, ntp);
   double price = (direction == "BUY") ? g_sym.Ask() : g_sym.Bid();
   if((nsl > 0.0 || ntp > 0.0) && !StopsOnCorrectSide(direction, price, nsl, ntp))
     {
      Print("[TradinGo] Open skipped ", symbol, " ", direction,
            " invalid stop side price=", DoubleToString(price, (int)g_sym.Digits()),
            " sl=", DoubleToString(nsl, (int)g_sym.Digits()),
            " tp=", DoubleToString(ntp, (int)g_sym.Digits()),
            " (stale or incoherent signal)");
      return false;
     }
   bool ok = false;
   if(direction == "BUY")
      ok = g_trade.Buy(lot, symbol, 0.0, nsl > 0 ? nsl : 0.0, ntp > 0 ? ntp : 0.0, comment);
   else
      ok = g_trade.Sell(lot, symbol, 0.0, nsl > 0 ? nsl : 0.0, ntp > 0 ? ntp : 0.0, comment);
   if(!ok)
     {
      Print("[TradinGo] Open failed ", symbol, " ", direction, " err=", g_trade.ResultRetcode());
      return false;
     }
   double fillPrice = g_trade.ResultPrice();
   if(fillPrice <= 0.0)
      fillPrice = (direction == "BUY") ? g_sym.Ask() : g_sym.Bid();
   double signalEntry = SignalEntryFromJson(json, rangeLo, rangeHi);
   AppendSignalStat(channelFile, json, symbol, direction, entryStatus,
                    rangeLo, rangeHi, signalEntry, fillPrice, distancePoints,
                    tpIndex, magic);
   Print("[TradinGo] Opened ", comment, " ", symbol, " ", direction,
         " lot=", DoubleToString(lot, 2),
         " fill=", DoubleToString(fillPrice, (int)g_sym.Digits()),
         " status=", entryStatus);
   return true;
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
EntryRangeDecision EvaluateEntryRange(const string symbol, const string direction,
                                      const double lo, const double hi,
                                      const int maxTolerancePoints,
                                      double &outPrice, double &outDistancePoints)
  {
   g_sym.Name(symbol);
   g_sym.RefreshRates();
   outPrice = (direction == "BUY") ? g_sym.Ask() : g_sym.Bid();
   if(outPrice >= lo && outPrice <= hi)
     {
      outDistancePoints = 0.0;
      return ENTRY_EXECUTE_IN_RANGE;
     }
   double distPrice = (outPrice < lo) ? (lo - outPrice) : (outPrice - hi);
   double point = g_sym.Point();
   if(point <= 0.0)
      point = _Point;
   outDistancePoints = distPrice / point;
   if(outDistancePoints <= (double)maxTolerancePoints)
      return ENTRY_EXECUTE_TOLERANCE;
   return ENTRY_CANCELLED;
  }

//+------------------------------------------------------------------+
void LogCancelledSignal(const string channelFile, const string json,
                        const string symbol, const string direction,
                        const double lo, const double hi,
                        const double price, const double distancePoints,
                        const int maxTolerancePoints)
  {
   Print("[TradinGo] SIGNAL_CANCELLED ", JsonGetString(json, "channel_id"), " ", symbol, " ", direction,
         " range=[", DoubleToString(lo, (int)g_sym.Digits()), ",",
         DoubleToString(hi, (int)g_sym.Digits()), "]",
         " price=", DoubleToString(price, (int)g_sym.Digits()),
         " distance_points=", DoubleToString(distancePoints, 1),
         " max_tolerance=", maxTolerancePoints,
         " ts=", JsonGetString(json, "timestamp"));
   AppendSignalStat(channelFile, json, symbol, direction, "CANCELLED_RANGE",
                    lo, hi, SignalEntryFromJson(json, lo, hi), price,
                    distancePoints, 0, 0);
  }

//+------------------------------------------------------------------+
bool TryExecuteWithEntryRange(const string channelFile, const string json,
                              const string symbol, const string direction,
                              const double lo, const double hi,
                              string &outEntryStatus, double &outDistancePoints)
  {
   double price = 0.0;
   outDistancePoints = 0.0;
   int maxTol = RangeToleranceForChannel(channelFile, json);
   EntryRangeDecision decision = EvaluateEntryRange(symbol, direction, lo, hi, maxTol,
                                                    price, outDistancePoints);
   if(decision == ENTRY_EXECUTE_IN_RANGE)
     {
      outEntryStatus = "EXECUTED_IN_RANGE";
      Print("[TradinGo] ENTRY_IN_RANGE ", symbol, " ", direction,
            " price=", DoubleToString(price, (int)g_sym.Digits()),
            " range=[", DoubleToString(lo, (int)g_sym.Digits()), ",",
            DoubleToString(hi, (int)g_sym.Digits()), "]");
      return true;
     }
   if(decision == ENTRY_EXECUTE_TOLERANCE)
     {
      outEntryStatus = "EXECUTED_TOLERANCE";
      Print("[TradinGo] ENTRY_TOLERANCE ", symbol, " ", direction,
            " price=", DoubleToString(price, (int)g_sym.Digits()),
            " distance_points=", DoubleToString(outDistancePoints, 1),
            " max=", maxTol);
      return true;
     }
   LogCancelledSignal(channelFile, json, symbol, direction, lo, hi, price,
                      outDistancePoints, maxTol);
   outEntryStatus = "CANCELLED_RANGE";
   return false;
  }

//+------------------------------------------------------------------+
bool OpenSplitTrades(const string symbol, const string direction,
                     const double lot, const double sl, const double &tps[],
                     const int magicBase,
                     const string channelFile, const string json,
                     const string entryStatus,
                     const double rangeLo, const double rangeHi,
                     const double distancePoints)
  {
   string channelTag = ChannelShortTag(channelFile, json);
   int n = ArraySize(tps);
   if(n <= 0)
      n = 1;
   bool any = false;
   for(int i = 0; i < n; i++)
     {
      double tp = (i < ArraySize(tps)) ? tps[i] : 0.0;
      ulong magic = TradeMagic(magicBase, i + 1);
      string comment = BuildTradeComment(channelTag, i + 1);
      if(OpenMarket(symbol, direction, lot, sl, tp, magic, comment,
                    channelFile, json, entryStatus, rangeLo, rangeHi,
                    distancePoints, i + 1))
         any = true;
     }
   return any;
  }

//+------------------------------------------------------------------+
bool ModifyExistingTrades(const string symbol, const int magicBase,
                          const double sl, const double &tps[])
  {
   int idx = 0;
   bool any = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      double tp = (idx < ArraySize(tps)) ? tps[idx] : 0.0;
      if(ModifyPositionSLTP(g_pos.Ticket(), sl, tp))
         any = true;
      idx++;
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

   string entryStatus = "EXECUTED_DIRECT";
   double distPoints = 0.0;
   if(rangeHi > rangeLo)
     {
      if(!TryExecuteWithEntryRange(channelFile, json, symbol, direction, rangeLo, rangeHi,
                                   entryStatus, distPoints))
         return true;
     }

   string channelTag = ChannelShortTag(channelFile, json);
   if(action == "OPEN_NOW")
     {
      return OpenMarket(symbol, direction, lot, 0, 0, TradeMagic(magicBase, 1),
                        BuildTradeComment(channelTag, 1),
                        channelFile, json, "EXECUTED_OPEN_NOW", rangeLo, rangeHi,
                        distPoints, 1);
     }

   int openCnt = CountOurPositions(symbol, magicBase, 5);
   if(openCnt > 0)
     {
      // Stack only when bridge explicitly sets allow_stack (intentional re-entry).
      // MSG+EDIT of the same Telegram signal must NOT open a second set of trades.
      bool allowStack = InpStackOpensIfFlatBusy && JsonGetBool(json, "allow_stack");
      if(!allowStack)
        {
         Print("[TradinGo] OPEN skipped — ", openCnt,
               " position(s) exist, modifying SL/TP instead",
               " (allow_stack=", (JsonGetBool(json, "allow_stack") ? "true" : "false"), ")");
         return ModifyExistingTrades(symbol, magicBase, sl, tps);
        }
      Print("[TradinGo] OPEN stack — ", openCnt,
            " position(s) already open, opening additional trade(s)");
     }

   return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase,
                          channelFile, json, entryStatus, rangeLo, rangeHi, distPoints);
  }

//+------------------------------------------------------------------+
bool HandleUpdateOpen(const string channelFile, const string json)
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
      double rangeLo = 0, rangeHi = 0;
      double entryRange[];
      string entryStatus = "EXECUTED_DIRECT";
      double distPoints = 0.0;
      if(JsonGetNumberArray(json, "entry_range", entryRange) && ArraySize(entryRange) >= 2)
        {
         rangeLo = MathMin(entryRange[0], entryRange[1]);
         rangeHi = MathMax(entryRange[0], entryRange[1]);
         if(!TryExecuteWithEntryRange(channelFile, json, symbol, direction, rangeLo, rangeHi,
                                      entryStatus, distPoints))
            return true;
        }
      Print("[TradinGo] UPDATE_OPEN but no positions — opening fresh");
      return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase,
                             channelFile, json, entryStatus, rangeLo, rangeHi, distPoints);
     }

   if(openCnt == 1 && trades > 1)
     {
      Print("[TradinGo] UPDATE_OPEN split: close 1 reopen ", trades);
      CloseOurPositions(symbol, magicBase, 5);
      return OpenSplitTrades(symbol, direction, lot, sl, tps, magicBase,
                             channelFile, json, "EXECUTED_DIRECT", 0, 0, 0);
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
   Print("[TradinGo] CLOSE_HALF_BE ", symbol, " — close 50% + SL to entry (clamped if needed)");
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      if(!g_pos.SelectByIndex(i))
         continue;
      if(g_pos.Symbol() != symbol)
         continue;
      if(!IsOurPosition(g_pos.Ticket(), magicBase, 5))
         continue;
      ulong ticket = g_pos.Ticket();
      double vol = g_pos.Volume();
      double half = NormalizeLot(symbol, vol / 2.0);
      if(half >= SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN))
        {
         if(!g_trade.PositionClosePartial(ticket, half))
            Print("[TradinGo] CLOSE_HALF partial failed ticket=", ticket,
                  " err=", g_trade.ResultRetcode());
         else
            Print("[TradinGo] CLOSE_HALF ok ticket=", ticket,
                  " closed=", DoubleToString(half, 2));
        }
      // Re-select: after partial the ticket remains for the leftover volume.
      ApplyBreakEvenSL(ticket);
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
      ApplyBreakEvenSL(g_pos.Ticket());
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

   bool handled = false;
   if(action == "OPEN" || action == "OPEN_NOW")
      handled = HandleOpen(channelFile, json);
   else if(action == "UPDATE_OPEN")
      handled = HandleUpdateOpen(channelFile, json);
   else if(action == "UPDATE_TP")
      handled = HandleUpdateTp(json);
   else if(action == "UPDATE_SL")
      handled = HandleUpdateSl(json);
   else if(action == "CHECK_AND_CLOSE")
      handled = HandleCheckAndClose(json);
   else if(action == "CLOSE_ALL_SYMBOL")
      handled = HandleCloseAllSymbol(json);
   else if(action == "BREAK_EVEN_PRICE")
      handled = HandleBreakEvenPrice(json);
   else if(action == "CLOSE_HALF_BE")
      handled = HandleCloseHalfBe(json);
   else if(action == "CHECK_AND_BE")
      handled = HandleCheckAndBe(json);
   else if(action == "CHECK_AND_CLOSE_TP")
      handled = HandleCheckAndCloseTp(json);
   else
      Print("[TradinGo] Unknown action: ", action);

   // Clear after any recognized action attempt (including cancelled range / failed open)
   // so a restart cannot replay the same JSON.
   if(InpClearSignalAfterProcess && action != "" && action != "NONE")
      ClearSignalFile(channelFile);
   return handled;
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
void SeedAndClearExistingSignals()
  {
   // Critical: on attach/recompile, do NOT execute leftover JSON from hours/days ago.
   for(int i = 0; i < g_channelCount; i++)
     {
      string json;
      if(!ReadSignalFile(g_channelFile[i], json))
         continue;
      string action = JsonGetString(json, "action");
      string ts = JsonGetString(json, "timestamp");
      if(ts != "")
         g_lastTimestamp[i] = ts;
      if(action == "" || action == "NONE")
         continue;
      Print("[TradinGo] Init skip stale ", g_channelFile[i],
            " action=", action, " ts=", ts, " -> NONE (no exec)");
      ClearSignalFile(g_channelFile[i]);
     }
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   ParseChannels();
   g_trade.SetDeviationInPoints(InpMaxSlippagePoints);
   EventSetMillisecondTimer(InpPollMs);
   Print("[TradinGo] EA v2.09 started | channels=", g_channelCount,
         " path=", (StringLen(InpSignalsPath) > 0 ? InpSignalsPath : "<MQL5\\Files>"),
         " abs=", InpUseAbsolutePath,
         " range_tolerance_pts=", InpRangeTolerancePoints,
         " oro_tolerance_pts=", InpOroRangeTolerancePoints,
         " ignore_existing_on_init=", InpIgnoreExistingOnInit,
         " stack_opens=", InpStackOpensIfFlatBusy,
         " (requires JSON allow_stack)",
         " stop_buffer_pts=", InpStopBufferPoints);
   for(int i = 0; i < g_channelCount; i++)
      Print("[TradinGo]  watch ", g_channelFile[i]);
   if(InpIgnoreExistingOnInit)
      SeedAndClearExistingSignals();
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
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // timer-driven; tick hook for future BE-on-TP1 monitor
  }
//+------------------------------------------------------------------+
