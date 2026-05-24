import os
from datetime import datetime

def extract_today_logs(log_filename="prop.log"):
    if not os.path.exists(log_filename):
        print(f"Errore: Il file {log_filename} non esiste in questa cartella.")
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    output_filename = f"estratto_logs_{today_str}.txt"
    
    print(f"Analisi di {log_filename} per la data: {today_str}...")
    
    try:
        with open(log_filename, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        # Filtra solo le righe di oggi
        today_logs = [line for line in lines if today_str in line]
        
        if not today_logs:
            print("Nessun log trovato per la data di oggi.")
            # Mostra le ultime 10 righe in generale per capire cosa sta succedendo
            print("\nUltime 10 righe assolute del file:")
            for line in lines[-10:]:
                print(line.strip())
            return

        with open(output_filename, "w", encoding="utf-8") as out:
            out.writelines(today_logs)
            
        print(f"? Estratto creato con successo: {output_filename}")
        print(f"--- Ultime 5 righe di oggi ---")
        for line in today_logs[-5:]:
            print(line.strip())
            
    except Exception as e:
        print(f"Errore durante la lettura: {e}")

if __name__ == "__main__":
    extract_today_logs()
