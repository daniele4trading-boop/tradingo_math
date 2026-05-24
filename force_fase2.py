import json
import os
import tempfile

JSON_PATH = "C:/tradingo_math/tradingo_state.json"

def force_fase2():
    print("--- TradinGo-Math: Force Phase 2 Activation ---")
    
    if not os.path.exists(JSON_PATH):
        print("Errore: Il file JSON non esiste. Avvia prima i motori!")
        return

    try:
        # 1. Leggi lo stato attuale
        with open(JSON_PATH, 'r') as f:
            state = json.load(f)

        if not state.get('prop_ticket') or not state.get('hedge_ticket'):
            print("Avviso: Non vedo ticket aperti nel JSON. Il test potrebbe non avere effetto sui terminali.")
        
        # 2. Forza i flag della Fase 2
        state['fase2_attiva'] = True
        print(f"Attivazione Fase 2 forzata per i ticket: Prop({state.get('prop_ticket')}) e Hedge({state.get('hedge_ticket')})")

        # 3. Scrittura Atomica con Flush (Bypass Cache Windows)
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(JSON_PATH), text=True)
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, JSON_PATH)

        print("\n✅ FASE 2 INIETTATA NEL JSON!")
        print("Ora controlla le console dei motori e i grafici MT5 per vedere la modifica degli SL.")

    except Exception as e:
        print(f"Errore: {e}")

if __name__ == "__main__":
    force_fase2()
