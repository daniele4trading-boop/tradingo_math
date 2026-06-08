//+------------------------------------------------------------------+
//| PriceActionQuantEA.mq5                                           |
//| Price Action + RSI Z-Score + ATR risk model                      |
//| v0.1 - long-first research version, short side already available |
//+------------------------------------------------------------------+
#property strict
#property version   "0.10"
#property description "Bullish/Bearish engulfing with RSI Z-Score, EMA regime filter and ATR SL/TP."

#include <Trade/Trade.mqh>

enum DirectionMode
{
   DIRECTION_LONG_ONLY = 0,
   DIRECTION_SHORT_ONLY = 1,
   DIRECTION_BOTH = 2
};

CTrade trade;

// --- Signal and timeframe
input DirectionMode   InpDirectionMode              = DIRECTION_LONG_ONLY;
input ENUM_TIMEFRAMES InpTimeframe                  = PERIOD_H1;
input long            InpMagic                      = 26060801;
input string          InpOrderComment               = "PAQ_v0.1";

// --- Risk and execution
input bool            InpUseFixedLot                = false;
input double          InpFixedLot                   = 0.10;
input double          InpRiskPercent                = 1.00;
input int             InpMaxSpreadPoints            = 20;
input int             InpDeviationPoints            = 20;
input int             InpStopBufferPoints           = 5;
input int             InpMaxPositionsPerSymbol      = 1;
input double          InpMaxDailyLossPercent        = 3.0;
input int             InpMaxConsecutiveLosses       = 5;
input int             InpTradingStartHour           = 0;
input int             InpTradingEndHour             = 24;

// --- RSI Z-Score
input int             InpRSIPeriod                  = 14;
input int             InpRSIZLookback               = 50;
input double          InpRSIZThresholdLong          = -2.0;
input double          InpRSIZThresholdShort         = 2.0;
input int             InpRSIZRecentBars             = 3;

// --- ATR exits
input int             InpATRPeriod                  = 14;
input double          InpATRStopMultiplier          = 2.0;
input double          InpRewardRiskRatio            = 1.5;

// --- Market regime
input bool            InpEnableRegimeFilter         = true;
input int             InpRegimeEMAPeriod            = 200;
input int             InpRegimeSlopeLookback        = 10;

// --- Engulfing definition
input bool            InpRequirePreviousOpposite    = true;
input bool            InpRequireBodyEngulfing       = true;
input bool            InpRequireCloseBreak          = true;
input double          InpMinBodyATRMultiplier       = 0.0;
input double          InpMaxUpperWickATRMultiplier  = 0.0;
input double          InpMaxLowerWickATRMultiplier  = 0.0;

int      rsi_handle = INVALID_HANDLE;
int      atr_handle = INVALID_HANDLE;
int      ema_handle = INVALID_HANDLE;
datetime last_bar_time = 0;
int      current_day_of_year = -1;
double   day_start_equity = 0.0;
int      consecutive_losses = 0;

//+------------------------------------------------------------------+
//| Expert initialization                                            |
//+------------------------------------------------------------------+
int OnInit()
{
   if(InpRSIPeriod <= 1 || InpRSIZLookback < 10 || InpATRPeriod <= 1)
   {
      Print("Invalid indicator parameters.");
      return INIT_PARAMETERS_INCORRECT;
   }

   rsi_handle = iRSI(_Symbol, InpTimeframe, InpRSIPeriod, PRICE_CLOSE);
   atr_handle = iATR(_Symbol, InpTimeframe, InpATRPeriod);
   ema_handle = iMA(_Symbol, InpTimeframe, InpRegimeEMAPeriod, 0, MODE_EMA, PRICE_CLOSE);

   if(rsi_handle == INVALID_HANDLE || atr_handle == INVALID_HANDLE || ema_handle == INVALID_HANDLE)
   {
      Print("Failed to create indicator handles. Error=", GetLastError());
      return INIT_FAILED;
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviationPoints);
   ResetDailyEquityIfNeeded(true);
   Print("PriceActionQuantEA initialized on ", _Symbol, " timeframe=", EnumToString(InpTimeframe));
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(rsi_handle != INVALID_HANDLE) IndicatorRelease(rsi_handle);
   if(atr_handle != INVALID_HANDLE) IndicatorRelease(atr_handle);
   if(ema_handle != INVALID_HANDLE) IndicatorRelease(ema_handle);
}

//+------------------------------------------------------------------+
//| Tick handler                                                     |
//+------------------------------------------------------------------+
void OnTick()
{
   ResetDailyEquityIfNeeded(false);

   if(!IsNewBar())
      return;

   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
      return;

   if(!IsTradingHour())
      return;

   if(IsDailyLossLimitReached())
      return;

   if(InpMaxConsecutiveLosses > 0 && consecutive_losses >= InpMaxConsecutiveLosses)
   {
      Print("Trading blocked: max consecutive losses reached: ", consecutive_losses);
      return;
   }

   if(CurrentSpreadPoints() > InpMaxSpreadPoints)
      return;

   if(CountOwnPositions() >= InpMaxPositionsPerSymbol)
      return;

   double atr = 0.0;
   if(!GetBufferValue(atr_handle, 1, atr) || atr <= 0.0 || !MathIsValidNumber(atr))
      return;

   bool buy_signal = false;
   bool sell_signal = false;

   if(InpDirectionMode == DIRECTION_LONG_ONLY || InpDirectionMode == DIRECTION_BOTH)
      buy_signal = HasLongSignal(atr);

   if(InpDirectionMode == DIRECTION_SHORT_ONLY || InpDirectionMode == DIRECTION_BOTH)
      sell_signal = HasShortSignal(atr);

   if(buy_signal && sell_signal)
   {
      Print("Both long and short signals detected on same bar; skipping.");
      return;
   }

   if(buy_signal)
      OpenPosition(ORDER_TYPE_BUY, atr);
   else if(sell_signal)
      OpenPosition(ORDER_TYPE_SELL, atr);
}

//+------------------------------------------------------------------+
//| Trade transaction handler for consecutive loss guard             |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction& trans,
                        const MqlTradeRequest& request,
                        const MqlTradeResult& result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;

   if(!HistoryDealSelect(trans.deal))
      return;

   string symbol = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);

   if(symbol != _Symbol || magic != InpMagic || entry != DEAL_ENTRY_OUT)
      return;

   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);

   if(profit < 0.0)
      consecutive_losses++;
   else if(profit > 0.0)
      consecutive_losses = 0;
}

//+------------------------------------------------------------------+
//| Signal logic                                                     |
//+------------------------------------------------------------------+
bool HasLongSignal(const double atr)
{
   if(!BullishEngulfing(atr))
      return false;

   double z_min = 0.0;
   if(!RecentRsiZMin(z_min))
      return false;

   if(z_min > InpRSIZThresholdLong)
      return false;

   return RegimeAllows(ORDER_TYPE_BUY);
}

bool HasShortSignal(const double atr)
{
   if(!BearishEngulfing(atr))
      return false;

   double z_max = 0.0;
   if(!RecentRsiZMax(z_max))
      return false;

   if(z_max < InpRSIZThresholdShort)
      return false;

   return RegimeAllows(ORDER_TYPE_SELL);
}

bool BullishEngulfing(const double atr)
{
   double o1 = iOpen(_Symbol, InpTimeframe, 1);
   double h2 = iHigh(_Symbol, InpTimeframe, 2);
   double h1 = iHigh(_Symbol, InpTimeframe, 1);
   double c1 = iClose(_Symbol, InpTimeframe, 1);
   double o2 = iOpen(_Symbol, InpTimeframe, 2);
   double c2 = iClose(_Symbol, InpTimeframe, 2);

   if(InpRequirePreviousOpposite && !(c2 < o2))
      return false;
   if(!(c1 > o1))
      return false;
   if(InpRequireBodyEngulfing && !(o1 <= c2 && c1 >= o2))
      return false;
   if(InpRequireCloseBreak && !(c1 > h2))
      return false;

   if(InpMinBodyATRMultiplier > 0.0 && MathAbs(c1 - o1) < atr * InpMinBodyATRMultiplier)
      return false;

   if(InpMaxUpperWickATRMultiplier > 0.0)
   {
      double upper_wick = h1 - MathMax(o1, c1);
      if(upper_wick > atr * InpMaxUpperWickATRMultiplier)
         return false;
   }

   return true;
}

bool BearishEngulfing(const double atr)
{
   double o1 = iOpen(_Symbol, InpTimeframe, 1);
   double l2 = iLow(_Symbol, InpTimeframe, 2);
   double l1 = iLow(_Symbol, InpTimeframe, 1);
   double c1 = iClose(_Symbol, InpTimeframe, 1);
   double o2 = iOpen(_Symbol, InpTimeframe, 2);
   double c2 = iClose(_Symbol, InpTimeframe, 2);

   if(InpRequirePreviousOpposite && !(c2 > o2))
      return false;
   if(!(c1 < o1))
      return false;
   if(InpRequireBodyEngulfing && !(o1 >= c2 && c1 <= o2))
      return false;
   if(InpRequireCloseBreak && !(c1 < l2))
      return false;

   if(InpMinBodyATRMultiplier > 0.0 && MathAbs(c1 - o1) < atr * InpMinBodyATRMultiplier)
      return false;

   if(InpMaxLowerWickATRMultiplier > 0.0)
   {
      double lower_wick = MathMin(o1, c1) - l1;
      if(lower_wick > atr * InpMaxLowerWickATRMultiplier)
         return false;
   }

   return true;
}

bool RegimeAllows(const ENUM_ORDER_TYPE order_type)
{
   if(!InpEnableRegimeFilter)
      return true;

   double ema_now = 0.0;
   double ema_past = 0.0;
   if(!GetBufferValue(ema_handle, 1, ema_now))
      return false;
   if(!GetBufferValue(ema_handle, 1 + InpRegimeSlopeLookback, ema_past))
      return false;

   double close1 = iClose(_Symbol, InpTimeframe, 1);
   if(order_type == ORDER_TYPE_BUY)
      return close1 > ema_now && ema_now >= ema_past;

   return close1 < ema_now && ema_now <= ema_past;
}

//+------------------------------------------------------------------+
//| RSI Z helpers                                                    |
//+------------------------------------------------------------------+
bool RecentRsiZMin(double &z_min)
{
   z_min = DBL_MAX;
   int bars = MathMax(1, InpRSIZRecentBars);
   for(int shift = 1; shift <= bars; shift++)
   {
      double z = 0.0;
      if(!RsiZAtShift(shift, z))
         return false;
      if(z < z_min)
         z_min = z;
   }
   return z_min != DBL_MAX;
}

bool RecentRsiZMax(double &z_max)
{
   z_max = -DBL_MAX;
   int bars = MathMax(1, InpRSIZRecentBars);
   for(int shift = 1; shift <= bars; shift++)
   {
      double z = 0.0;
      if(!RsiZAtShift(shift, z))
         return false;
      if(z > z_max)
         z_max = z;
   }
   return z_max != -DBL_MAX;
}

bool RsiZAtShift(const int shift, double &z)
{
   double current = 0.0;
   if(!GetBufferValue(rsi_handle, shift, current))
      return false;

   double sum = 0.0;
   double values[];
   ArrayResize(values, InpRSIZLookback);

   for(int i = 0; i < InpRSIZLookback; i++)
   {
      double value = 0.0;
      if(!GetBufferValue(rsi_handle, shift + i, value))
         return false;
      values[i] = value;
      sum += value;
   }

   double mean = sum / InpRSIZLookback;
   double variance = 0.0;
   for(int i = 0; i < InpRSIZLookback; i++)
      variance += MathPow(values[i] - mean, 2.0);

   double std = MathSqrt(variance / InpRSIZLookback);
   if(std <= 0.0)
      return false;

   z = (current - mean) / std;
   return MathIsValidNumber(z);
}

bool GetBufferValue(const int handle, const int shift, double &value)
{
   double buffer[];
   ArrayResize(buffer, 1);
   if(CopyBuffer(handle, 0, shift, 1, buffer) != 1)
      return false;
   value = buffer[0];
   return MathIsValidNumber(value);
}

//+------------------------------------------------------------------+
//| Order placement and risk                                         |
//+------------------------------------------------------------------+
bool OpenPosition(const ENUM_ORDER_TYPE order_type, const double atr)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ask <= 0.0 || bid <= 0.0)
      return false;

   double price = (order_type == ORDER_TYPE_BUY) ? ask : bid;
   double min_stop_distance = MinimumStopDistance();
   double risk_distance = MathMax(atr * InpATRStopMultiplier, min_stop_distance);
   if(risk_distance <= 0.0)
      return false;

   double sl = 0.0;
   double tp = 0.0;
   if(order_type == ORDER_TYPE_BUY)
   {
      sl = price - risk_distance;
      tp = price + risk_distance * InpRewardRiskRatio;
   }
   else
   {
      sl = price + risk_distance;
      tp = price - risk_distance * InpRewardRiskRatio;
   }

   sl = NormalizeDouble(sl, _Digits);
   tp = NormalizeDouble(tp, _Digits);

   double volume = CalculateVolume(risk_distance);
   if(volume <= 0.0)
      return false;

   if(!HasEnoughMargin(order_type, volume, price))
      return false;

   bool ok = false;
   if(order_type == ORDER_TYPE_BUY)
      ok = trade.Buy(volume, _Symbol, 0.0, sl, tp, InpOrderComment);
   else
      ok = trade.Sell(volume, _Symbol, 0.0, sl, tp, InpOrderComment);

   if(!ok)
   {
      Print("Order failed. Retcode=", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      return false;
   }

   Print("Order opened: ", EnumToString(order_type), " volume=", DoubleToString(volume, 2),
         " SL=", DoubleToString(sl, _Digits), " TP=", DoubleToString(tp, _Digits));
   return true;
}

double CalculateVolume(const double risk_distance)
{
   if(InpUseFixedLot)
      return NormalizeVolume(InpFixedLot);

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_money = equity * InpRiskPercent / 100.0;
   double tick_size = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);

   if(risk_money <= 0.0 || risk_distance <= 0.0 || tick_size <= 0.0 || tick_value <= 0.0)
      return NormalizeVolume(InpFixedLot);

   double loss_per_lot = (risk_distance / tick_size) * tick_value;
   if(loss_per_lot <= 0.0)
      return NormalizeVolume(InpFixedLot);

   return NormalizeVolume(risk_money / loss_per_lot);
}

double NormalizeVolume(const double requested)
{
   double min_vol = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double max_vol = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(step <= 0.0)
      step = 0.01;

   double volume = MathMax(min_vol, MathMin(max_vol, requested));
   volume = MathFloor(volume / step) * step;

   int digits = 2;
   if(step < 1.0)
      digits = (int)MathMin(8, MathMax(0, MathRound(-MathLog10(step))));

   return NormalizeDouble(volume, digits);
}

bool HasEnoughMargin(const ENUM_ORDER_TYPE order_type, const double volume, const double price)
{
   double margin = 0.0;
   if(!OrderCalcMargin(order_type, _Symbol, volume, price, margin))
      return false;

   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(margin > free_margin)
   {
      Print("Insufficient margin. Required=", margin, " free=", free_margin);
      return false;
   }
   return true;
}

double MinimumStopDistance()
{
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   return (double)(stops_level + InpStopBufferPoints) * _Point;
}

//+------------------------------------------------------------------+
//| Guards                                                           |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime bar_time = iTime(_Symbol, InpTimeframe, 0);
   if(bar_time <= 0)
      return false;
   if(last_bar_time == 0)
   {
      last_bar_time = bar_time;
      return false;
   }
   if(bar_time == last_bar_time)
      return false;

   last_bar_time = bar_time;
   return true;
}

int CurrentSpreadPoints()
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(ask <= 0.0 || bid <= 0.0)
      return INT_MAX;
   return (int)MathRound((ask - bid) / _Point);
}

int CountOwnPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;

      if(PositionGetString(POSITION_SYMBOL) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == InpMagic)
      {
         count++;
      }
   }
   return count;
}

bool IsTradingHour()
{
   if(InpTradingStartHour == 0 && InpTradingEndHour == 24)
      return true;

   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hour = dt.hour;

   if(InpTradingStartHour < InpTradingEndHour)
      return hour >= InpTradingStartHour && hour < InpTradingEndHour;

   return hour >= InpTradingStartHour || hour < InpTradingEndHour;
}

void ResetDailyEquityIfNeeded(const bool force)
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);

   if(force || current_day_of_year != dt.day_of_year)
   {
      current_day_of_year = dt.day_of_year;
      day_start_equity = AccountInfoDouble(ACCOUNT_EQUITY);
      consecutive_losses = 0;
      Print("Daily guards reset. Day start equity=", day_start_equity);
   }
}

bool IsDailyLossLimitReached()
{
   if(InpMaxDailyLossPercent <= 0.0 || day_start_equity <= 0.0)
      return false;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double loss_pct = (day_start_equity - equity) / day_start_equity * 100.0;
   if(loss_pct >= InpMaxDailyLossPercent)
   {
      Print("Trading blocked: daily loss limit reached. Loss%=", DoubleToString(loss_pct, 2));
      return true;
   }
   return false;
}
