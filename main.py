import udmi_script
import site_model_editor
import building_batch
import yaml_batch_builder

def show_menu() -> str:
    print("\n=== Meter Onboard Tool ===")
    print("1. Translation Builder (UDMI)")
    print("2. Single JSON Site Model Editor (single json input)")
    print("3. Batch Site Model Editor (full site model input)")
    print("4. Batch YAML Export (already-processed site model input)")
    while True:
        choice = input("Select an option (1-4): ").strip()
        if choice in ("1", "2", "3", "4"):
            return choice
        print("Invalid selection. Please enter 1, 2, 3, or 4.")

def run_loop() -> None:
    while True:
        choice = show_menu()
        if choice == "1":
            udmi_script.run_udmi()
        elif choice == "2":
            site_model_editor.run_site_model_editor()
        elif choice == "3":
            building_batch.run_building_batch()
        elif choice == "4":
            yaml_batch_builder.run_yaml_batch_builder()

        again = input("\nRun again? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye!")
            break

if __name__ == "__main__":
    run_loop()
