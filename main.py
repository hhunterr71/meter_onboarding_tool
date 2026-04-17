import bitbox_script
import mango_script
import site_model_editor
import building_batch

def show_menu() -> str:
    print("\n=== Meter Onboard Tool ===")
    print("1. Translation Builder (BITBOX)")
    print("2. Translation Builder (MANGO)")
    print("3. Site Model Meter Editor")
    print("4. Building Batch Processor")
    while True:
        choice = input("Select an option (1-4): ").strip()
        if choice in ("1", "2", "3", "4"):
            return choice
        print("Invalid selection. Please enter 1, 2, 3, or 4.")

def run_loop() -> None:
    while True:
        choice = show_menu()
        if choice == "1":
            bitbox_script.main()
        elif choice == "2":
            mango_script.run_mango()
        elif choice == "3":
            site_model_editor.run_site_model_editor()
        elif choice == "4":
            building_batch.run_building_batch()

        again = input("\nRun again? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye!")
            break

if __name__ == "__main__":
    run_loop()
