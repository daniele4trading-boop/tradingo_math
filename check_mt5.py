import MetaTrader5 as mt5
if not mt5.initialize():
    print("❌ Inizializzazione fallita!")
else:
    print("✅ MT5 Connesso!")
    symbol = "XAUUSD" # O il nome usato dal tuo broker
    tick = mt5.symbol_info_tick(symbol)
    if tick:
        print(f"✅ Prezzo Oro ricevuto: {tick.bid}")
    else:
        print(f"❌ Impossibile leggere il simbolo {symbol}. Verifica il nome!")
    mt5.shutdown()
