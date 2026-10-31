"""TUKE OpenLab SDK — starter experiment.

Run against the simulator (safe, nothing real moves):

    uv run main.py

The SDK prints the matching simulator URL, e.g.:
    https://openlab.kpi.fei.tuke.sk/simulator/light/mysterioushf-demo

To drive the real lab instead, swap simulation_env("...") for production_env().
"""

import subprocess
import sys

# Map menu choices to your script filenames
SCRIPTS = {
    "1": "tymofii.py",
    "2": "mark.py",
    "3": "andrii.py"
}

def main():
    while True:
        print("\n" + "="*30)
        print("\t\tLIGHT SHOW CONTROL PANEL")
        print("="*30)
        print("\t[1] Run Test Tymofii")
        print("\t[2] Run Test Mark")
        print("\t[3] Run Test Andrii")
        print("\t[a] All")
        print("\t[q] Quit")
        print("-" * 30)
        
        choice = input("Select a pattern (1-3 or a or q): ").strip().lower()
        
        if choice == 'q':
            print("Exiting light show controller. Goodbye!")
            break
            
        if choice in SCRIPTS:
            script_name = SCRIPTS[choice]
            print(f"\n Launching {script_name}...")
            print(" Tip: Press Ctrl+C at any time to stop the show and return to this menu.\n")
            
            try:
                # Run the chosen script using the current Python environment
                subprocess.run([sys.executable, script_name], check=True)
            except KeyboardInterrupt:
                print(f"\n Stopped {script_name}.")
            except subprocess.CalledProcessError as e:
                print(f"\n Error: {script_name} crashed with exit code {e.returncode}")
            except FileNotFoundError:
                print(f"\n Error: Could not find '{script_name}' in this folder. Make sure the file exists!")
        elif (choice == "a"):
            for i in SCRIPTS:
                subprocess.run([sys.executable, SCRIPTS[i]], check=True)
        else:
            print("\n Invalid choice. Please enter 1, 2, 3, 'a' or 'q'.")

if __name__ == "__main__":
    main()