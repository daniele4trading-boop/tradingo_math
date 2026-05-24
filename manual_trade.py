import json
import os
import tempfile
import time

JSON_PATH = "C:/tradingo_math/tradingo_state.json"

def send_manual_signal():
    print("--- TradinGo-Math: Manual Signal Generator ---")
    direction = input("Inserisci direzione (BUY/SELL): ").strip().upper()
    
    if direction not in ['BUY', 'SELL']:
        print("Errore: Inserire solo BUY o SELL.")
        return

    # Genera un ID univoco basato sul timestamp
    signal_id = int(time.time())
    
    try:
        # 1. Leggi lo stato attuale se esiste
        state = {}
        if os.path.exists(JSON_PATH):
            with open(JSON_PATH, 'r') as f:
                try:
                    state = json.load(f)
                except:
                    state = {}

        # 2. Inserisci il segnale e resetta i flag di controllo
        state['signal'] = direction
        state['signal_id'] = signal_id
        state['hedge_ready'] = False  # Forza l'Hedge ad aprire per primo
        state['fase2_attiva'] = False
        state['abort'] = False
        
        # Pulizia dati vecchi per il test di apertura
        state.pop('prop_ticket', None)
        state.pop('hedge_ticket', None)

        # 3. Scrittura Atomica Sicura
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(JSON_PATH), text=True)
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=4)
        os.replace(temp_path, JSON_PATH)

        print(f"\n✅ SEGNALE {direction} INVIATO CORRETTAMENTE!")
        print(f"ID Segnale: {signal_id}")
        print(f"---")
        print(f"Ora osserva i CMD di Hedge e Prop:")
        print(f"1. L'Hedge Engine dovrebbe rilevare il segnale e aprire.")
        print(f"2. Una volta che l'Hedge ha aperto, la Prop dovrebbe seguire.")

    except Exception as e:
        print(f"Errore durante l'invio: {e}")

if __name__ == "__main__":
    send_manual_signal()
